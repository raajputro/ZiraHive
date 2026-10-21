package app.zirahive.android.backup

import android.app.PendingIntent
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import app.zirahive.android.MainActivity
import app.zirahive.android.R
import app.zirahive.android.Server
import app.zirahive.android.SignedOut
import app.zirahive.android.Uploader
import app.zirahive.android.ZiraHiveApp
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import java.io.IOException
import java.time.Instant

/**
 * One backup run: finds photos and videos this phone hasn't backed up yet, skips the ones the
 * server already has (by SHA-256, so a photo is never stored twice), and uploads the rest,
 * newest first. Then it tells the server how it went, which becomes a ZiraHive notification.
 */
class BackupWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    private data class Item(val key: String, val uri: Uri, val name: String, val size: Long,
                            val takenMs: Long, val video: Boolean, val id: Long)

    override suspend fun getForegroundInfo(): ForegroundInfo = foreground(applicationContext.getString(R.string.backup_checking), 0, 0)

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        try {
            if (!Backup.enabled(ctx) || !Backup.canRead(ctx) || !Server.isSetUp(ctx)) return Result.success()
            running.withLock { run(ctx) }
        } finally {
            if (inputData.getBoolean(KEY_TRIGGERED, false)) Backup.watchForNewMedia(ctx, replace = true)
        }
        return Result.success()
    }

    private suspend fun run(ctx: Context) {
        val base = Server.base(ctx, fresh = true) ?: return
        if (!Server.answers(base)) return  // not at home and no away address: try again later
        if (!Server.isSignedIn(ctx)) { signedOutNotice(ctx); return }

        val store = BackupStore(ctx)
        val done = store.doneItems()
        val todo = findNew(ctx, done)
        if (todo.isEmpty()) {
            Backup.prefs(ctx).edit().putLong("last_run", System.currentTimeMillis()).apply()
            return
        }
        try { setForeground(foreground(ctx.getString(R.string.backup_checking), 0, 0)) } catch (e: Exception) { /* not allowed right now */ }

        val up = Uploader(ctx, base)
        val folder = "/Phone/" + Server.deviceName()
        var uploaded = 0
        var skipped = 0
        var failed = 0
        var failedInARow = 0
        var position = 0
        try {
            for (batch in todo.chunked(40)) {
                if (isStopped) break
                // hash this batch (or reuse the hash from an unfinished earlier try)
                val hashes = mutableMapOf<String, String>()
                for (it in batch) {
                    if (isStopped) break
                    val sha = store.partial(it.key)?.second ?: try {
                        Uploader.sha256(open(ctx, it.uri))
                    } catch (e: Exception) { null }
                    if (sha != null) hashes[it.key] = sha else failed++
                }
                val existing = up.alreadyBackedUp(hashes.values.toList())
                for (it in batch) {
                    if (isStopped) break
                    position++
                    val sha = hashes[it.key] ?: continue
                    if (sha in existing) { store.markDone(it.key, sha); skipped++; continue }
                    try { setForeground(foreground(ctx.getString(R.string.backup_progress, position, todo.size), position, todo.size)) } catch (e: Exception) { }
                    try {
                        val r = up.send(
                            name = it.name, size = it.size, sha256 = sha, folder = folder,
                            open = { open(ctx, it.uri) },
                            takenAt = it.takenMs.takeIf { t -> t > 0 }?.let { t -> Instant.ofEpochMilli(t).toString() },
                            deviceAssetId = "android:${if (it.video) "video" else "image"}:${it.id}",
                            resumeId = store.partial(it.key)?.first,
                            onStarted = { id -> store.markPartial(it.key, id, sha) },
                        )
                        store.markDone(it.key, sha)
                        if (r.existed) skipped++ else uploaded++
                        failedInARow = 0
                    } catch (e: SignedOut) {
                        throw e
                    } catch (e: IOException) {
                        failed++
                        failedInARow++
                        if (failedInARow >= 3) throw e  // the connection is gone: try again later
                    }
                }
            }
        } catch (e: SignedOut) {
            Server.forgetDeviceToken(ctx)
            signedOutNotice(ctx)
        } catch (e: IOException) {
            // left for the next run
        } finally {
            Backup.prefs(ctx).edit().putLong("last_run", System.currentTimeMillis()).apply()
            if (uploaded + failed > 0) {
                try {
                    Server.postJson(ctx, base, "/api/events/backup", JSONObject()
                        .put("uploaded", uploaded).put("skipped", skipped).put("failed", failed)
                        .put("device", Server.deviceName()))
                } catch (e: Exception) { }
            }
        }
    }

    /** Gallery items not backed up yet, newest first, minus excluded folders. */
    private fun findNew(ctx: Context, done: Set<String>): List<Item> {
        val excluded = Backup.excludedFolders(ctx)
        val since = if (Backup.existing(ctx)) 0L else Backup.since(ctx)
        val out = mutableListOf<Item>()
        val kinds = buildList {
            add(MediaStore.Images.Media.EXTERNAL_CONTENT_URI to false)
            if (Backup.videos(ctx)) add(MediaStore.Video.Media.EXTERNAL_CONTENT_URI to true)
        }
        for ((collection, video) in kinds) {
            val cols = arrayOf(MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.DATE_TAKEN, MediaStore.MediaColumns.DATE_ADDED, MediaStore.MediaColumns.BUCKET_DISPLAY_NAME)
            val where = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) "${MediaStore.MediaColumns.IS_PENDING} = 0" else null
            ctx.contentResolver.query(collection, cols, where, null, "${MediaStore.MediaColumns.DATE_ADDED} DESC")?.use { c ->
                while (c.moveToNext()) {
                    val id = c.getLong(0)
                    val size = c.getLong(2)
                    if (size <= 0) continue
                    val key = "${if (video) "v" else "i"}:$id:$size"
                    if (key in done) continue
                    val bucket = c.getString(5) ?: ""
                    if (bucket in excluded) continue
                    val added = c.getLong(4) * 1000
                    if (since > 0 && added < since) continue
                    out += Item(key, ContentUris.withAppendedId(collection, id), c.getString(1) ?: "$id", size,
                        c.getLong(3).takeIf { it > 0 } ?: added, video, id)
                }
            }
        }
        return out.sortedByDescending { it.takenMs }
    }

    /** Opens the original, with the place it was taken still in it (Android hides GPS otherwise). */
    private fun open(ctx: Context, uri: Uri) = try {
        val original = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) MediaStore.setRequireOriginal(uri) else uri
        ctx.contentResolver.openInputStream(original)
    } catch (e: Exception) {
        null
    } ?: ctx.contentResolver.openInputStream(uri) ?: throw IOException("can't open $uri")

    private fun foreground(text: String, done: Int, total: Int): ForegroundInfo {
        val ctx = applicationContext
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_BACKUP)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(ctx.getString(R.string.backup_title))
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .setProgress(total, done, total == 0)
            .setContentIntent(openApp(ctx, "/photos"))
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ForegroundInfo(NOTIFY_PROGRESS, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else ForegroundInfo(NOTIFY_PROGRESS, n)
    }

    private fun signedOutNotice(ctx: Context) {
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_NEWS)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(ctx.getString(R.string.backup_title))
            .setContentText(ctx.getString(R.string.backup_signed_out))
            .setAutoCancel(true)
            .setContentIntent(openApp(ctx, "/"))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(NOTIFY_SIGNED_OUT, n) } catch (e: SecurityException) { }
    }

    companion object {
        const val KEY_TRIGGERED = "triggered"
        private const val NOTIFY_PROGRESS = 101
        private const val NOTIFY_SIGNED_OUT = 102
        private val running = Mutex()

        fun openApp(ctx: Context, path: String): PendingIntent = PendingIntent.getActivity(ctx, path.hashCode(),
            Intent(ctx, MainActivity::class.java).putExtra(MainActivity.EXTRA_PATH, path)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }
}
