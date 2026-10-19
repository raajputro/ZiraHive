package app.zirahive.android

import android.content.ContentValues
import android.content.Intent
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import android.widget.Toast
import app.zirahive.android.backup.Backup
import app.zirahive.android.backup.BackupSettingsActivity
import app.zirahive.android.player.PlayerActivity
import org.json.JSONObject
import java.io.File

/**
 * What the ZiraHive web pages can ask the app to do, as `window.ZiraHiveApp` (see web/src/native.ts).
 * Called on a background thread, so anything touching the screen goes through runOnUiThread.
 */
class WebBridge(private val activity: MainActivity) {

    @JavascriptInterface
    fun version(): String = JSONObject()
        .put("name", BuildConfig.VERSION_NAME)
        .put("code", BuildConfig.VERSION_CODE)
        .put("device", Server.deviceName())
        .toString()

    /** Play in the native player. `spec`: {url, title, subtitle?, poster?, start?, live?, mediaId?,
     *  subtitles?: [{url, label, language}], playlist?: [{url, title, live?}], index?} */
    @JavascriptInterface
    fun play(spec: String) {
        JSONObject(spec)  // fail here, in the page, if it isn't JSON
        activity.runOnUiThread {
            activity.startActivity(Intent(activity, PlayerActivity::class.java).putExtra(PlayerActivity.EXTRA_SPEC, spec))
        }
    }

    /** The page signed out: stop background work under that account. */
    @JavascriptInterface
    fun signedOut() {
        Server.forgetDeviceToken(activity)
    }

    @JavascriptInterface
    fun openBackupSettings() {
        activity.runOnUiThread { activity.startActivity(Intent(activity, BackupSettingsActivity::class.java)) }
    }

    @JavascriptInterface
    fun openAddressSettings() {
        activity.runOnUiThread { activity.startActivity(Intent(activity, SetupActivity::class.java)) }
    }

    /** {enabled, running, lastRun (ms or 0), uploaded} for the web Settings page. */
    @JavascriptInterface
    fun backupStatus(): String = Backup.status(activity).toString()

    /** A file the page made itself (a decrypted vault file): put it in Downloads. */
    @JavascriptInterface
    fun saveFile(name: String, mime: String, base64: String) {
        val bytes = Base64.decode(base64, Base64.DEFAULT)
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { "file" }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, safe)
                    put(MediaStore.Downloads.MIME_TYPE, mime)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri = activity.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: error("couldn't create the file")
                activity.contentResolver.openOutputStream(uri)!!.use { it.write(bytes) }
            } else {
                @Suppress("DEPRECATION")
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                dir.mkdirs()
                File(dir, safe).writeBytes(bytes)
            }
            activity.runOnUiThread {
                Toast.makeText(activity, activity.getString(R.string.saved_to_downloads, safe), Toast.LENGTH_SHORT).show()
            }
        } catch (e: Exception) {
            activity.runOnUiThread { Toast.makeText(activity, e.message ?: "Couldn't save", Toast.LENGTH_LONG).show() }
        }
    }
}
