package app.zirahive.android.share

import android.content.Context
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import app.zirahive.android.R
import app.zirahive.android.Server
import app.zirahive.android.SignedOut
import app.zirahive.android.Uploader
import app.zirahive.android.ZiraHiveApp
import app.zirahive.android.backup.BackupWorker
import java.io.File

/** Sends files shared from other apps into a folder in Files. */
class ShareUploadWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun getForegroundInfo(): ForegroundInfo = progress(0, 0)

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        val dir = File(inputData.getString(KEY_DIR) ?: return Result.failure())
        val folder = inputData.getString(KEY_FOLDER) ?: "/From phone"
        val files = dir.listFiles()?.sortedBy { it.name } ?: return Result.failure()
        val base = Server.base(ctx, fresh = true) ?: return Result.retry()
        try { setForeground(progress(0, files.size)) } catch (e: Exception) { }
        val up = Uploader(ctx, base)
        var sent = 0
        var failed = 0
        for ((i, f) in files.withIndex()) {
            try { setForeground(progress(i + 1, files.size)) } catch (e: Exception) { }
            try {
                up.send(name = f.name, size = f.length(), sha256 = Uploader.sha256(f.inputStream()), folder = folder,
                    open = { f.inputStream() }, dedupe = false)
                sent++
                f.delete()
            } catch (e: SignedOut) {
                failed += files.size - i
                break
            } catch (e: Exception) {
                failed++
            }
        }
        if (failed > 0 && runAttemptCount < 3) return Result.retry()  // the files are still there
        dir.deleteRecursively()
        val path = "/files" + folder.split("/").joinToString("/") { Uri.encode(it) }
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_UPLOADS)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(if (failed == 0) ctx.getString(R.string.share_done, sent) else ctx.getString(R.string.share_failed))
            .setContentText(folder)
            .setAutoCancel(true)
            .setContentIntent(BackupWorker.openApp(ctx, path))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(id.hashCode(), n) } catch (e: SecurityException) { }
        return Result.success()
    }

    private fun progress(done: Int, total: Int): ForegroundInfo {
        val ctx = applicationContext
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_UPLOADS)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(ctx.getString(R.string.share_title))
            .setContentText(if (total > 0) ctx.getString(R.string.share_progress, done, total) else ctx.getString(R.string.share_preparing))
            .setOngoing(true)
            .setSilent(true)
            .setProgress(total, done, total == 0)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ForegroundInfo(NOTIFY_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else ForegroundInfo(NOTIFY_ID, n)
    }

    companion object {
        const val KEY_DIR = "dir"
        const val KEY_FOLDER = "folder"
        private const val NOTIFY_ID = 201
    }
}
