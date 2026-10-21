package app.zirahive.android.backup

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.provider.MediaStore
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Phone backup settings and scheduling. The work itself is [BackupWorker]. */
object Backup {
    private const val PREFS = "backup"
    private const val PERIODIC = "backup-periodic"
    private const val ON_NEW = "backup-on-new-media"
    const val NOW = "backup-now"

    fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun enabled(ctx: Context) = prefs(ctx).getBoolean("enabled", false)
    fun wifiOnly(ctx: Context) = prefs(ctx).getBoolean("wifi", true)
    fun chargingOnly(ctx: Context) = prefs(ctx).getBoolean("charging", false)
    fun videos(ctx: Context) = prefs(ctx).getBoolean("videos", true)
    /** Photos taken before backup was turned on are skipped when this is false. */
    fun existing(ctx: Context) = prefs(ctx).getBoolean("existing", true)
    fun since(ctx: Context) = prefs(ctx).getLong("since", 0L)
    fun excludedFolders(ctx: Context): Set<String> = prefs(ctx).getStringSet("excluded", emptySet()) ?: emptySet()
    fun lastRun(ctx: Context) = prefs(ctx).getLong("last_run", 0L)

    fun set(ctx: Context, key: String, value: Boolean) {
        val e = prefs(ctx).edit().putBoolean(key, value)
        if (key == "enabled" && value && since(ctx) == 0L) e.putLong("since", System.currentTimeMillis())
        e.apply()
        schedule(ctx, settingsChanged = true)
    }

    fun setExcluded(ctx: Context, folders: Set<String>) {
        prefs(ctx).edit().putStringSet("excluded", folders).apply()
    }

    fun mediaPermissions(): Array<String> = when {
        Build.VERSION.SDK_INT >= 34 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED, Manifest.permission.ACCESS_MEDIA_LOCATION)
        Build.VERSION.SDK_INT >= 33 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.ACCESS_MEDIA_LOCATION)
        Build.VERSION.SDK_INT >= 29 -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.ACCESS_MEDIA_LOCATION)
        else -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    private fun granted(ctx: Context, p: String) = ContextCompat.checkSelfPermission(ctx, p) == PackageManager.PERMISSION_GRANTED

    /** Full access to the gallery (not "selected photos only"). */
    fun hasFullAccess(ctx: Context): Boolean = when {
        Build.VERSION.SDK_INT >= 33 -> granted(ctx, Manifest.permission.READ_MEDIA_IMAGES)
        else -> granted(ctx, Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    /** Android 14+: the person chose "select photos" — we can see only those. */
    fun hasPartialAccess(ctx: Context): Boolean = Build.VERSION.SDK_INT >= 34 && !hasFullAccess(ctx) &&
        granted(ctx, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)

    fun canRead(ctx: Context) = hasFullAccess(ctx) || hasPartialAccess(ctx)

    private fun constraints(ctx: Context) = Constraints.Builder()
        .setRequiredNetworkType(if (wifiOnly(ctx)) NetworkType.UNMETERED else NetworkType.CONNECTED)
        .setRequiresCharging(chargingOnly(ctx))
        .setRequiresBatteryNotLow(true)
        .build()

    /** Sets up the hourly check and the "a new photo arrived" trigger, or cancels both. */
    fun schedule(ctx: Context, settingsChanged: Boolean = false) {
        val wm = WorkManager.getInstance(ctx)
        if (!enabled(ctx) || !canRead(ctx)) {
            wm.cancelUniqueWork(PERIODIC)
            wm.cancelUniqueWork(ON_NEW)
            return
        }
        val periodic = PeriodicWorkRequestBuilder<BackupWorker>(1, TimeUnit.HOURS)
            .setConstraints(constraints(ctx))
            .build()
        wm.enqueueUniquePeriodicWork(PERIODIC,
            if (settingsChanged) ExistingPeriodicWorkPolicy.UPDATE else ExistingPeriodicWorkPolicy.KEEP, periodic)
        watchForNewMedia(ctx, replace = settingsChanged)
    }

    /** Runs a backup a little after a photo or video is added (content triggers fire once, so
     *  the worker sets this up again each time). */
    fun watchForNewMedia(ctx: Context, replace: Boolean = true) {
        val c = Constraints.Builder()
            .setRequiredNetworkType(if (wifiOnly(ctx)) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresCharging(chargingOnly(ctx))
            .addContentUriTrigger(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true)
            .addContentUriTrigger(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, true)
            .setTriggerContentUpdateDelay(15, TimeUnit.SECONDS)
            .setTriggerContentMaxDelay(2, TimeUnit.MINUTES)
            .build()
        val req = OneTimeWorkRequestBuilder<BackupWorker>()
            .setConstraints(c)
            .setInputData(workDataOf(BackupWorker.KEY_TRIGGERED to true))
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(ON_NEW,
            if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, req)
    }

    /** "Back up now": runs straight away (on any network the person allowed). */
    fun now(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<BackupWorker>()
            .setConstraints(Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly(ctx)) NetworkType.UNMETERED else NetworkType.CONNECTED).build())
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(NOW, ExistingWorkPolicy.KEEP, req)
    }

    fun isRunning(ctx: Context): Boolean = try {
        listOf(PERIODIC, ON_NEW, NOW).any { name ->
            WorkManager.getInstance(ctx).getWorkInfosForUniqueWork(name).get().any { it.state == WorkInfo.State.RUNNING }
        }
    } catch (e: Exception) { false }

    fun status(ctx: Context): JSONObject = JSONObject()
        .put("enabled", enabled(ctx))
        .put("running", isRunning(ctx))
        .put("lastRun", lastRun(ctx))
        .put("uploaded", BackupStore(ctx).count())
        .put("permission", canRead(ctx))
}
