package app.zirahive.android.player

import android.app.PendingIntent
import android.app.PictureInPictureParams
import android.app.RemoteAction
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Rational
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import app.zirahive.android.MainActivity
import app.zirahive.android.R
import app.zirahive.android.Server
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * Plays films, episodes and TV channels with Android's own player: it handles more formats than
 * the browser (often no converting needed), keeps playing in a floating window while you use the
 * rest of ZiraHive or other apps, and saves where you stopped.
 */
@OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {

    private lateinit var view: PlayerView
    private lateinit var titleBar: LinearLayout
    private lateinit var titleText: TextView
    private var player: ExoPlayer? = null
    private var spec = JSONObject()
    private var saver: Job? = null
    private var videoRatio = Rational(16, 9)
    private var closing = false
    private var reported = false
    private var usedFallback = false

    private val pipControls = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val p = player ?: return
            if (p.isPlaying) p.pause() else p.play()
            updatePip()
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        view = PlayerView(this).apply {
            keepScreenOn = true
            setShowSubtitleButton(true)
            setControllerVisibilityListener(PlayerView.ControllerVisibilityListener { visibility ->
                if (!isInPip()) titleBar.visibility = visibility
            })
        }
        root.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        titleBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(8), dp(12))
            setBackgroundColor(0x88000000.toInt())
        }
        titleText = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 16f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
        }
        titleBar.addView(titleText, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (supportsPip()) {
            titleBar.addView(ImageButton(this).apply {
                setImageResource(R.drawable.ic_pip)
                setBackgroundColor(Color.TRANSPARENT)
                contentDescription = getString(R.string.float_window)
                setOnClickListener { floatAndBrowse() }
            }, LinearLayout.LayoutParams(dp(48), dp(48)))
        }
        root.addView(titleBar, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP))
        setContentView(root)
        immersive()

        ContextCompat.registerReceiver(this, pipControls, IntentFilter(ACTION_TOGGLE), ContextCompat.RECEIVER_NOT_EXPORTED)
        load(intent.getStringExtra(EXTRA_SPEC))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // something else was chosen while this one played (also from the floating window)
        reportAndSave()
        load(intent.getStringExtra(EXTRA_SPEC))
    }

    private fun load(json: String?) {
        spec = try { JSONObject(json ?: "{}") } catch (e: Exception) { JSONObject() }
        reported = false
        usedFallback = false
        if (!spec.has("url") && !spec.has("playlist")) { finish(); return }
        player?.release()

        val base = Server.home(this) ?: ""
        val headers = mutableMapOf<String, String>()
        Server.cookie(this, spec.optString("url").let { originOf(it) ?: base })?.let { headers["Cookie"] = it }
        Server.deviceToken(this)?.let { headers["Authorization"] = "Bearer $it" }
        val http = DefaultHttpDataSource.Factory()
            .setUserAgent(Server.userAgent())
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
            .setDefaultRequestProperties(headers)
        val p = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setHandleAudioBecomingNoisy(true)
            .build()
        player = p
        view.player = p

        val items = mutableListOf<MediaItem>()
        val list = spec.optJSONArray("playlist")
        if (list != null && list.length() > 0) {
            for (i in 0 until list.length()) items += itemFrom(list.getJSONObject(i))
        } else {
            items += itemFrom(spec)
        }
        val index = spec.optInt("index", 0).coerceIn(0, items.size - 1)
        val startMs = (spec.optDouble("start", 0.0) * 1000).toLong()
        p.setMediaItems(items, index, if (isLive()) C.TIME_UNSET else startMs)
        p.addListener(object : Player.Listener {
            override fun onMediaMetadataChanged(m: MediaMetadata) { titleText.text = m.title ?: "" }
            override fun onVideoSizeChanged(size: VideoSize) {
                if (size.width > 0 && size.height > 0) {
                    videoRatio = Rational(size.width, size.height).let {
                        // Android only allows floating windows between 1:2.39 and 2.39:1
                        if (it.toFloat() > 2.39f) Rational(239, 100) else if (it.toFloat() < 0.42f) Rational(100, 239) else it
                    }
                    requestedOrientation = if (size.height > size.width) ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
                    else ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                    updatePip()
                }
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) { updatePip() }
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_ENDED && !isLive() && (list == null || p.currentMediaItemIndex >= items.size - 1)) {
                    reportAndSave(finished = true)
                    finish()
                }
            }
            override fun onPlayerError(error: PlaybackException) {
                // a format this phone can't play: switch to the server's converted stream once
                val fallback = spec.optString("fallbackUrl")
                if (!usedFallback && fallback.isNotBlank() && list == null) {
                    usedFallback = true
                    val at = p.currentPosition
                    p.setMediaItem(itemFrom(JSONObject(spec.toString()).put("url", fallback)), if (isLive()) C.TIME_UNSET else at)
                    p.prepare()
                    p.play()
                    return
                }
                Toast.makeText(this@PlayerActivity, getString(R.string.player_error, error.errorCodeName), Toast.LENGTH_LONG).show()
            }
        })
        val playlist = items.size > 1
        view.setShowNextButton(playlist)
        view.setShowPreviousButton(playlist)
        titleText.text = items[index].mediaMetadata.title ?: ""
        p.prepare()
        p.playWhenReady = true
        startSaving()
    }

    private fun itemFrom(o: JSONObject): MediaItem {
        val url = o.optString("url")
        val subs = mutableListOf<MediaItem.SubtitleConfiguration>()
        val list: JSONArray? = o.optJSONArray("subtitles")
        if (list != null) for (i in 0 until list.length()) {
            val s = list.getJSONObject(i)
            subs += MediaItem.SubtitleConfiguration.Builder(Uri.parse(s.getString("url")))
                .setMimeType(MimeTypes.TEXT_VTT)
                .setLanguage(s.optString("language").ifBlank { null })
                .setLabel(s.optString("label").ifBlank { null })
                .build()
        }
        val hls = url.contains(".m3u8") || o.optString("content_type").contains("mpegurl", true)
        return MediaItem.Builder()
            .setUri(url)
            .apply { if (hls) setMimeType(MimeTypes.APPLICATION_M3U8) }
            .setSubtitleConfigurations(subs)
            .setMediaMetadata(MediaMetadata.Builder()
                .setTitle(listOf(o.optString("title"), o.optString("subtitle")).filter { it.isNotBlank() }.joinToString(" · "))
                .build())
            .build()
    }

    private fun isLive() = spec.optBoolean("live", false)

    private fun originOf(url: String): String? = try {
        val u = Uri.parse(url); "${u.scheme}://${u.host}${if (u.port > 0) ":${u.port}" else ""}"
    } catch (e: Exception) { null }

    /** Library titles: save the position on the server every 10 seconds, like the web player. */
    private fun startSaving() {
        saver?.cancel()
        val mediaId = spec.optString("mediaId").ifBlank { null } ?: return
        if (isLive()) return
        saver = lifecycleScope.launch {
            while (true) {
                delay(10_000)
                saveProgress(mediaId)
            }
        }
    }

    private fun saveProgress(mediaId: String, finished: Boolean = false) {
        val p = player ?: return
        val pos = p.currentPosition / 1000.0
        val dur = p.duration.takeIf { it > 0 }?.let { it / 1000.0 }
        if (pos < 1 && !finished) return
        val ctx = applicationContext
        val origin = originOf(spec.optString("url")) ?: Server.home(ctx) ?: return
        val body = JSONObject().put("position", if (finished && dur != null) dur else pos)
        if (dur != null) body.put("duration", dur)
        CoroutineScope(Dispatchers.IO).launch {
            try { Server.putJson(ctx, origin, "/api/media/$mediaId/progress", body) } catch (e: Exception) { /* next time */ }
        }
    }

    /** Where we stopped, for the web page (it remembers IPTV positions itself) and the server.
     *  Once per title: when it ends, is closed, or something else is chosen. */
    private fun reportAndSave(finished: Boolean = false) {
        val p = player ?: return
        if (reported) return
        reported = true
        spec.optString("mediaId").ifBlank { null }?.let { if (!isLive()) saveProgress(it, finished) }
        PlayerEvents.closed(JSONObject()
            .put("position", p.currentPosition / 1000.0)
            .put("duration", if (p.duration > 0) p.duration / 1000.0 else JSONObject.NULL)
            .put("index", p.currentMediaItemIndex)
            .put("finished", finished)
            .put("mediaId", spec.optString("mediaId").ifBlank { JSONObject.NULL })
            .put("key", spec.optString("key").ifBlank { JSONObject.NULL }))
    }

    // ------------------------------------------------------------- floating window

    private fun supportsPip() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
        packageManager.hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)

    private fun isInPip() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && isInPictureInPictureMode

    private fun pipParams(): PictureInPictureParams {
        val playing = player?.isPlaying == true
        val action = RemoteAction(
            Icon.createWithResource(this, if (playing) R.drawable.ic_pause else R.drawable.ic_play),
            getString(if (playing) R.string.pause else R.string.play),
            getString(if (playing) R.string.pause else R.string.play),
            PendingIntent.getBroadcast(this, 1, Intent(ACTION_TOGGLE).setPackage(packageName),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        val b = PictureInPictureParams.Builder().setAspectRatio(videoRatio).setActions(listOf(action))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) b.setAutoEnterEnabled(playing).setSeamlessResizeEnabled(true)
        return b.build()
    }

    private fun updatePip() {
        if (supportsPip()) try { setPictureInPictureParams(pipParams()) } catch (e: Exception) { /* not allowed now */ }
    }

    /** The floating-window button: keep watching in a small window and go back to ZiraHive. */
    private fun floatAndBrowse() {
        if (!supportsPip()) return
        if (enterPictureInPictureMode(pipParams())) {
            startActivity(Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
    }

    /** Pressing Home while something plays (older Android; newer ones float by themselves). */
    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (supportsPip() && Build.VERSION.SDK_INT < Build.VERSION_CODES.S && player?.isPlaying == true) {
            enterPictureInPictureMode(pipParams())
        }
    }

    override fun onPictureInPictureModeChanged(inPip: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(inPip, newConfig)
        view.useController = !inPip
        titleBar.visibility = if (inPip) View.GONE else View.VISIBLE
        if (!inPip && !lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            // the floating window was closed (dragged away / X)
            close()
        }
    }

    override fun onStop() {
        super.onStop()
        if (!isInPip()) {
            player?.pause()
            spec.optString("mediaId").ifBlank { null }?.let { if (!isLive()) saveProgress(it) }
        }
    }

    override fun finish() {
        if (!closing) { closing = true; reportAndSave() }
        super.finish()
    }

    private fun close() {
        if (!closing) { closing = true; reportAndSave() }
        player?.pause()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) finishAndRemoveTask() else super.finish()
    }

    override fun onDestroy() {
        saver?.cancel()
        try { unregisterReceiver(pipControls) } catch (e: Exception) { }
        player?.release()
        player = null
        super.onDestroy()
    }

    private fun immersive() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    companion object {
        const val EXTRA_SPEC = "spec"
        private const val ACTION_TOGGLE = "app.zirahive.android.PIP_TOGGLE"
    }
}
