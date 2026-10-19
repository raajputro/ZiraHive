package app.zirahive.android.prayer

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import app.zirahive.android.R
import app.zirahive.android.Server
import app.zirahive.android.ZiraHiveApp
import app.zirahive.android.backup.BackupWorker
import org.json.JSONObject
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Prayer reminders on the phone, set from the place and choices saved on the Namaz page.
 * The settings are kept on the phone too, so reminders keep coming without a connection.
 * One alarm is set at a time: the next reminder. When it rings, the one after it is set.
 */
object PrayerAlarms {
    private const val PREFS = "prayer"
    private const val REQ = 4401

    fun saved(ctx: Context): JSONObject? =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("settings", null)?.let {
            try { JSONObject(it) } catch (e: Exception) { null }
        }

    /** Fetches the settings from ZiraHive (when reachable) and sets the next reminder. */
    suspend fun refresh(ctx: Context) {
        try {
            val base = Server.base(ctx)
            if (base != null && Server.isSignedIn(ctx)) {
                val s = Server.getJson(ctx, base, "/api/namaz/settings")
                ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("settings", s.toString()).apply()
            }
        } catch (e: Exception) { /* use what's saved */ }
        schedule(ctx)
    }

    private fun zone(s: JSONObject): ZoneId = try {
        s.optString("timezone").takeIf { it.isNotBlank() && it != "null" }?.let { ZoneId.of(it) } ?: ZoneId.systemDefault()
    } catch (e: Exception) { ZoneId.systemDefault() }

    /** The next reminder after `now`: (prayer, when to ring, the prayer's own time). */
    fun next(s: JSONObject, now: Long = System.currentTimeMillis()): Triple<String, Long, Long>? {
        if (s.isNull("lat") || s.isNull("lng")) return null
        val r = s.optJSONObject("reminders") ?: JSONObject()
        val before = r.optInt("before", 0) * 60_000L
        val on = PrayerTimes.FARD.filter { r.optBoolean(it, true) }
        if (on.isEmpty()) return null
        val today = LocalDate.ofInstant(Instant.ofEpochMilli(now), zone(s))
        for (d in 0..2) {
            val day = today.plusDays(d.toLong())
            val times = PrayerTimes.forDay(day, s)
            for (p in PrayerTimes.FARD) {
                if (p !in on) continue
                val at = times.getValue(p)
                val ring = at - before
                if (ring > now + 1000) return Triple(p, ring, at)
            }
        }
        return null
    }

    fun schedule(ctx: Context) {
        val am = ctx.getSystemService(AlarmManager::class.java)
        val pi = PendingIntent.getBroadcast(ctx, REQ, Intent(ctx, PrayerReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        am.cancel(pi)
        val s = saved(ctx) ?: return
        val (prayer, ring, at) = next(s) ?: return
        val intent = Intent(ctx, PrayerReceiver::class.java).putExtra("prayer", prayer).putExtra("at", at)
        val alarm = PendingIntent.getBroadcast(ctx, REQ, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()
        if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ring, alarm)
        else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ring, alarm)
    }

    fun label(ctx: Context, prayer: String, at: Long, s: JSONObject?): String {
        val friday = s != null && LocalDate.ofInstant(Instant.ofEpochMilli(at), zone(s)).dayOfWeek == DayOfWeek.FRIDAY
        return ctx.getString(when (prayer) {
            "fajr" -> R.string.prayer_fajr
            "dhuhr" -> if (friday) R.string.prayer_jumuah else R.string.prayer_dhuhr
            "asr" -> R.string.prayer_asr
            "maghrib" -> R.string.prayer_maghrib
            else -> R.string.prayer_isha
        })
    }

    fun notify(ctx: Context, prayer: String, at: Long) {
        val s = saved(ctx)
        val name = label(ctx, prayer, at, s)
        val minutes = ((at - System.currentTimeMillis()) / 60_000).toInt()
        val text = if (minutes >= 1) ctx.getString(R.string.prayer_soon, name, minutes) else ctx.getString(R.string.prayer_now, name)
        val n = NotificationCompat.Builder(ctx, ZiraHiveApp.CH_PRAYER)
            .setSmallIcon(R.drawable.ic_stat_hive)
            .setContentTitle(text)
            .setContentText(s?.optString("place")?.takeIf { it.isNotBlank() })
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(BackupWorker.openApp(ctx, "/quran/namaz"))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(5000 + prayer.hashCode() % 100, n) } catch (e: SecurityException) { }
    }
}

/** Rings for one prayer, then sets the next. Also re-sets the alarm after a restart or a clock change. */
class PrayerReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val prayer = intent.getStringExtra("prayer")
        if (prayer != null) PrayerAlarms.notify(ctx, prayer, intent.getLongExtra("at", System.currentTimeMillis()))
        PrayerAlarms.schedule(ctx)
    }
}
