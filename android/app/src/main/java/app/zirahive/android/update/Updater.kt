package app.zirahive.android.update

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import app.zirahive.android.BuildConfig
import app.zirahive.android.R
import app.zirahive.android.Server
import app.zirahive.android.ZiraHiveApp
import app.zirahive.android.backup.BackupWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request
import org.json.JSONObject
import java.io.File

/**
 * Updates come from your own ZiraHive: the admin puts a new version there (Settings > Android
 * app), and every phone offers to install it. No app store involved.
 */
object Updater {

    private suspend fun latest(base: String): JSONObject? = withContext(Dispatchers.IO) {
        try {
            Server.http.newCall(Request.Builder().url("$base/api/app/android").header("User-Agent", Server.userAgent()).build())
                .execute().use { r -> if (r.isSuccessful) JSONObject(r.body!!.string()) else null }
        } catch (e: Exception) { null }
    }

    /** On opening the app: if the server has a newer version, ask (once per version). */
    fun checkAndOffer(activity: AppCompatActivity) {
        activity.lifecycleScope.launch {
            val base = Server.base(activity) ?: return@launch
            val info = latest(base) ?: return@launch
            val code = info.optInt("version_code")
            if (code <= BuildConfig.VERSION_CODE) return@launch
            val prefs = activity.getSharedPreferences("update", Context.MODE_PRIVATE)
            if (prefs.getInt("dismissed", 0) == code) return@launch
            AlertDialog.Builder(activity)
                .setTitle(activity.getString(R.string.update_title, info.optString("version_name")))
                .setMessage(R.string.update_body)
                .setPositiveButton(R.string.update_now) { _, _ -> install(activity, base) }
                .setNegativeButton(R.string.update_later) { _, _ -> prefs.edit().putInt("dismissed", code).apply() }
                .show()
        }
    }

    /** From the background check: a notification, so nobody misses it. */
    suspend fun notifyIfNewer(ctx: Context, base: String) {
        val info = latest(base) ?: return
        val code = info.optInt("version_code")
        if (code <= BuildConfig.VERSION_CODE) return
        val prefs = ctx.getSharedPreferences("update", Context.MODE_PRIVATE)
        if (prefs.getInt("notified", 0) == code) return
        prefs.edit().putInt("notified", code).apply()
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_NEWS)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(ctx.getString(R.string.update_title, info.optString("version_name")))
            .setAutoCancel(true)
            .setContentIntent(BackupWorker.openApp(ctx, "/"))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(301, n) } catch (e: SecurityException) { }
    }

    fun install(activity: AppCompatActivity, base: String) {
        val pm = activity.packageManager
        if (!pm.canRequestPackageInstalls()) {
            Toast.makeText(activity, R.string.update_allow, Toast.LENGTH_LONG).show()
            activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${activity.packageName}")))
            return
        }
        val wait = AlertDialog.Builder(activity).setMessage(R.string.update_downloading).setCancelable(false).show()
        activity.lifecycleScope.launch {
            val file = withContext(Dispatchers.IO) {
                try {
                    val dir = File(activity.cacheDir, "updates").apply { mkdirs() }
                    val out = File(dir, "zirahive.apk")
                    Server.http.newCall(Request.Builder().url("$base/api/app/android/apk")
                        .header("User-Agent", Server.userAgent()).build()).execute().use { r ->
                        if (!r.isSuccessful) return@withContext null
                        out.outputStream().use { r.body!!.byteStream().copyTo(it) }
                    }
                    out
                } catch (e: Exception) { null }
            }
            wait.dismiss()
            if (file == null) { Toast.makeText(activity, R.string.update_failed, Toast.LENGTH_LONG).show(); return@launch }
            val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", file)
            activity.startActivity(Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    @Suppress("unused")
    private fun Activity.alive() = !isFinishing && !isDestroyed
}
