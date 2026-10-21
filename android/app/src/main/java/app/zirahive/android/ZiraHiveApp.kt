package app.zirahive.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import app.zirahive.android.backup.Backup
import app.zirahive.android.notify.NotificationPoller

class ZiraHiveApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // background extras: if one fails on some device, the app still opens
        safely { channels(this) }
        if (Server.isSetUp(this)) {
            safely { Backup.schedule(this) }
            safely { NotificationPoller.schedule(this) }
        }
        safely { app.zirahive.android.prayer.PrayerAlarms.schedule(this) }
    }

    private inline fun safely(block: () -> Unit) {
        try { block() } catch (t: Throwable) { android.util.Log.w("ZiraHive", "startup", t) }
    }

    companion object {
        const val CH_BACKUP = "backup"
        const val CH_NEWS = "news"
        const val CH_UPLOADS = "uploads"
        const val CH_PRAYER = "prayer"

        fun channels(ctx: Context) {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannels(listOf(
                NotificationChannel(CH_BACKUP, ctx.getString(R.string.channel_backup), NotificationManager.IMPORTANCE_LOW),
                NotificationChannel(CH_NEWS, ctx.getString(R.string.channel_news), NotificationManager.IMPORTANCE_DEFAULT),
                NotificationChannel(CH_UPLOADS, ctx.getString(R.string.channel_uploads), NotificationManager.IMPORTANCE_LOW),
                NotificationChannel(CH_PRAYER, ctx.getString(R.string.channel_prayer), NotificationManager.IMPORTANCE_HIGH),
            ))
        }
    }
}
