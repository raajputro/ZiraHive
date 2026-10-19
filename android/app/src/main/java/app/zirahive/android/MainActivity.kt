package app.zirahive.android

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.lifecycleScope
import app.zirahive.android.backup.Backup
import app.zirahive.android.notify.NotificationPoller
import app.zirahive.android.player.PlayerEvents
import app.zirahive.android.update.Updater
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.launch
import org.json.JSONObject

/** ZiraHive itself: the web app, in a built-in browser, with the phone's extras added. */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var progress: ProgressBar
    private lateinit var offline: View
    private lateinit var root: FrameLayout
    private var base: String? = null
    private var pendingFiles: ValueCallback<Array<Uri>>? = null
    private var pendingPermission: PermissionRequest? = null
    private var fullscreenView: View? = null
    private var fullscreenCallback: WebChromeClient.CustomViewCallback? = null
    private var checkedUpdate = false

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pendingFiles?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
        pendingFiles = null
    }

    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { _ ->
        val req = pendingPermission ?: return@registerForActivityResult
        pendingPermission = null
        val allowed = req.resources.filter {
            (it == PermissionRequest.RESOURCE_VIDEO_CAPTURE && has(Manifest.permission.CAMERA)) ||
                (it == PermissionRequest.RESOURCE_AUDIO_CAPTURE && has(Manifest.permission.RECORD_AUDIO))
        }
        if (allowed.isEmpty()) req.deny() else req.grant(allowed.toTypedArray())
    }

    private fun has(p: String) = ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Server.isSetUp(this)) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }
        WindowCompat.setDecorFitsSystemWindows(window, false)

        root = FrameLayout(this).apply { setBackgroundColor(getColor(R.color.indigo_night)) }
        web = WebView(this)
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = 100
            progressTintList = android.content.res.ColorStateList.valueOf(getColor(R.color.jute))
        }
        offline = offlineView()
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(progress, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)))
        root.addView(offline, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            if (fullscreenView == null) v.updatePadding(top = bars.top, bottom = bars.bottom, left = bars.left, right = bars.right)
            insets
        }

        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(web, false)
        }
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            loadWithOverviewMode = true
            useWideViewPort = true
            setSupportZoom(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            userAgentString = "$userAgentString ${Server.userAgent()}"
        }
        web.addJavascriptInterface(WebBridge(this), "ZiraHiveApp")
        web.webViewClient = Client()
        web.webChromeClient = Chrome()
        web.setDownloadListener { url, ua, disposition, mime, _ -> download(url, ua, disposition, mime) }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    fullscreenView != null -> fullscreenCallback?.onCustomViewHidden()
                    web.canGoBack() -> web.goBack()
                    else -> { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
                }
            }
        })

        PlayerEvents.listener = { result -> deliverPlayerResult(result) }
        if (savedInstanceState != null) web.restoreState(savedInstanceState) else start(intent.getStringExtra(EXTRA_PATH))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_PATH)?.let { path -> base?.let { web.loadUrl(it + path) } ?: start(path) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        PlayerEvents.listener = { result -> deliverPlayerResult(result) }
        PlayerEvents.takePending()?.let { deliverPlayerResult(it) }
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
        // the web page keeps running (music keeps playing while you use another app)
    }

    override fun onDestroy() {
        if (PlayerEvents.listener != null) PlayerEvents.listener = null
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }

    /** Pick the address (home or away) and open ZiraHive there. */
    private fun start(path: String?) {
        offline.visibility = View.GONE
        lifecycleScope.launch {
            val b = Server.base(this@MainActivity, fresh = true) ?: return@launch
            base = b
            web.loadUrl(b + (path ?: "/"))
        }
    }

    fun reload() = start(web.url?.let { u -> base?.let { b -> u.removePrefix(b) } })

    private fun isOurs(url: Uri): Boolean {
        val origin = "${url.scheme}://${url.host}${if (url.port > 0) ":${url.port}" else ""}"
        return origin.equals(Server.home(this), true) || origin.equals(Server.away(this), true) || url.scheme == "blob"
    }

    private inner class Client : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            if (isOurs(url)) return false
            // links to other sites (Tailscale help, Docker, a movie's page) open in the phone's browser
            return try { startActivity(Intent(Intent.ACTION_VIEW, url)); true } catch (e: Exception) { true }
        }

        override fun onPageFinished(view: WebView, url: String) {
            progress.visibility = View.GONE
            view.evaluateJavascript(BLOB_SAVER, null)
            if (Server.isSignedIn(this@MainActivity)) {
                base?.let { b -> lifecycleScope.launch { Server.ensureDeviceToken(this@MainActivity, b) } }
                Backup.schedule(this@MainActivity)
                NotificationPoller.schedule(this@MainActivity)
                if (!checkedUpdate) { checkedUpdate = true; Updater.checkAndOffer(this@MainActivity) }
            }
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame) {
                offline.visibility = View.VISIBLE
                // maybe we moved between home and away: look again next time
                lifecycleScope.launch { Server.base(this@MainActivity, fresh = true) }
            }
        }
    }

    private inner class Chrome : WebChromeClient() {
        override fun onProgressChanged(view: WebView, newProgress: Int) {
            progress.visibility = if (newProgress < 100) View.VISIBLE else View.GONE
            progress.progress = newProgress
        }

        override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
            pendingFiles?.onReceiveValue(null)
            pendingFiles = callback
            return try {
                val intent = params.createIntent().apply {
                    if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }
                pickFiles.launch(intent)
                true
            } catch (e: Exception) {
                pendingFiles = null
                false
            }
        }

        override fun onPermissionRequest(request: PermissionRequest) {
            val wanted = mutableListOf<String>()
            if (PermissionRequest.RESOURCE_VIDEO_CAPTURE in request.resources) wanted += Manifest.permission.CAMERA
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE in request.resources) wanted += Manifest.permission.RECORD_AUDIO
            runOnUiThread {
                if (wanted.all { has(it) }) {
                    request.grant(request.resources.filter {
                        it == PermissionRequest.RESOURCE_VIDEO_CAPTURE || it == PermissionRequest.RESOURCE_AUDIO_CAPTURE
                    }.toTypedArray())
                } else {
                    pendingPermission = request
                    askPermissions.launch(wanted.toTypedArray())
                }
            }
        }

        override fun onShowCustomView(view: View, callback: CustomViewCallback) {
            fullscreenView = view
            fullscreenCallback = callback
            root.updatePadding(0, 0, 0, 0)
            root.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            WindowInsetsControllerCompat(window, root).apply {
                hide(WindowInsetsCompat.Type.systemBars())
                systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        }

        override fun onHideCustomView() {
            fullscreenView?.let { root.removeView(it) }
            fullscreenView = null
            fullscreenCallback = null
            WindowInsetsControllerCompat(window, root).show(WindowInsetsCompat.Type.systemBars())
            ViewCompat.requestApplyInsets(root)
        }
    }

    /** Files the server hands out (downloads, offline copies) go to the phone's Downloads folder. */
    private fun download(url: String, ua: String, disposition: String?, mime: String?) {
        if (url.startsWith("blob:") || url.startsWith("data:")) return  // handled by BLOB_SAVER
        try {
            val name = URLUtil.guessFileName(url, disposition, mime)
            val req = DownloadManager.Request(Uri.parse(url))
                .setTitle(name)
                .setMimeType(mime)
                .addRequestHeader("User-Agent", ua)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            CookieManager.getInstance().getCookie(url)?.let { req.addRequestHeader("Cookie", it) }
            getSystemService(DownloadManager::class.java).enqueue(req)
            Toast.makeText(this, getString(R.string.saved_to_downloads, name), Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, e.message ?: "Download failed", Toast.LENGTH_LONG).show()
        }
    }

    /** Tell the page the native player closed, and where it stopped. */
    private fun deliverPlayerResult(result: JSONObject) {
        if (!::web.isInitialized) return
        val js = "window.dispatchEvent(new CustomEvent('zirahive:player-closed', {detail: $result}))"
        web.post { web.evaluateJavascript(js, null) }
    }

    private fun offlineView(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(32), dp(32), dp(32), dp(32))
            setBackgroundColor(getColor(R.color.indigo_night))
            visibility = View.GONE
            isClickable = true
        }
        box.addView(TextView(this).apply {
            text = getString(R.string.offline_title); textSize = 22f; setTextColor(getColor(R.color.ink)); gravity = Gravity.CENTER
        })
        box.addView(TextView(this).apply {
            text = getString(R.string.offline_body); textSize = 15f; setTextColor(getColor(R.color.muted))
            gravity = Gravity.CENTER; setPadding(0, dp(8), 0, dp(24))
        })
        box.addView(MaterialButton(this).apply { text = getString(R.string.retry); setOnClickListener { reload() } })
        box.addView(MaterialButton(this, null, com.google.android.material.R.attr.borderlessButtonStyle).apply {
            text = getString(R.string.change_address)
            setTextColor(Color.WHITE)
            setOnClickListener { startActivity(Intent(this@MainActivity, SetupActivity::class.java)) }
        })
        return box
    }

    companion object {
        const val EXTRA_PATH = "path"

        /** Saving a file the page made itself (the vault decrypts in the browser): read the blob
         *  and hand it to the app, which puts it in Downloads. */
        private val BLOB_SAVER = """
            (function () {
              if (window.__zhBlobSaver) return; window.__zhBlobSaver = true;
              document.addEventListener('click', function (e) {
                var a = e.target && e.target.closest ? e.target.closest('a[download]') : null;
                if (!a || !/^(blob|data):/.test(a.href)) return;
                e.preventDefault(); e.stopPropagation();
                fetch(a.href).then(function (r) { return r.blob(); }).then(function (b) {
                  var reader = new FileReader();
                  reader.onload = function () {
                    var s = String(reader.result); var comma = s.indexOf(',');
                    ZiraHiveApp.saveFile(a.getAttribute('download') || 'file', b.type || 'application/octet-stream', s.slice(comma + 1));
                  };
                  reader.readAsDataURL(b);
                });
              }, true);
            })();
        """.trimIndent()
    }
}
