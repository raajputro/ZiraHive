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
        channels(this)
        if (Server.isSetUp(this)) {
            Backup.schedule(this)
            NotificationPoller.schedule(this)
        }
    }

    companion object {
        const val CH_BACKUP = "backup"
        const val CH_NEWS = "news"
        const val CH_UPLOADS = "uploads"

        fun channels(ctx: Context) {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannels(listOf(
                NotificationChannel(CH_BACKUP, ctx.getString(R.string.channel_backup), NotificationManager.IMPORTANCE_LOW),
                NotificationChannel(CH_NEWS, ctx.getString(R.string.channel_news), NotificationManager.IMPORTANCE_DEFAULT),
                NotificationChannel(CH_UPLOADS, ctx.getString(R.string.channel_uploads), NotificationManager.IMPORTANCE_LOW),
            ))
        }
    }
}
