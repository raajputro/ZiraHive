package app.zirahive.android.notify

import android.content.Context
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.zirahive.android.R
import app.zirahive.android.Server
import app.zirahive.android.SignedOut
import app.zirahive.android.ZiraHiveApp
import app.zirahive.android.backup.BackupWorker
import app.zirahive.android.update.Updater
import java.util.concurrent.TimeUnit

/**
 * ZiraHive's own notifications (backups done, a shared album, new movies, a watch party
 * invite) shown as phone notifications. Android lets apps check at most every 15 minutes in the
 * background, so that is how often it looks. Once a day it also looks for an app update.
 */
class NotificationPoller(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        if (!Server.isSetUp(ctx) || !Server.isSignedIn(ctx)) return Result.success()
        val base = Server.base(ctx) ?: return Result.success()
        if (!Server.answers(base)) return Result.success()
        val prefs = ctx.getSharedPreferences("notify", Context.MODE_PRIVATE)
        try {
            val list = Server.getJson(ctx, base, "/api/notifications").optJSONArray("items")
            if (list != null) {
                val seen = prefs.getString("seen", null)
                var newest = seen
                val fresh = mutableListOf<org.json.JSONObject>()
                for (i in 0 until list.length()) {
                    val n = list.getJSONObject(i)
                    val at = n.optString("created_at")
                    if (newest == null || at > newest) newest = at
                    if (seen != null && at > seen && n.isNull("read_at")) fresh += n
                }
                // the first time, just remember where we are instead of showing old ones
                prefs.edit().putString("seen", newest ?: "").apply()
                for (n in fresh.take(5).reversed()) show(ctx, n)
            }
        } catch (e: SignedOut) {
            return Result.success()
        } catch (e: Exception) {
            return Result.success()
        }
        val day = 24 * 3600_000L
        if (System.currentTimeMillis() - prefs.getLong("update_checked", 0) > day) {
            prefs.edit().putLong("update_checked", System.currentTimeMillis()).apply()
            Updater.notifyIfNewer(ctx, base)
        }
        return Result.success()
    }

    private fun show(ctx: Context, n: org.json.JSONObject) {
        val link = n.optString("link").takeIf { it.startsWith("/") } ?: "/"
        val notification = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_NEWS)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(n.optString("title"))
            .setContentText(n.optString("body").takeIf { it.isNotBlank() && it != "null" })
            .setStyle(NotificationCompat.BigTextStyle().bigText(n.optString("body").takeIf { it != "null" }))
            .setAutoCancel(true)
            .setContentIntent(BackupWorker.openApp(ctx, link))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(n.optString("id").hashCode(), notification) } catch (e: SecurityException) { }
    }

    companion object {
        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<NotificationPoller>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("notifications", ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}
