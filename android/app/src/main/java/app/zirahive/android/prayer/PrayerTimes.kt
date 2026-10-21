package app.zirahive.android.prayer

import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneOffset
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.asin
import kotlin.math.atan
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.tan

/**
 * Prayer times for a day at a place: the same calculation as the web page (web/src/prayer.ts),
 * so the phone reminds at exactly the times shown there. Results are moments in epoch ms.
 */
object PrayerTimes {
    val FARD = listOf("fajr", "dhuhr", "asr", "maghrib", "isha")

    private class Method(val fajr: Double, val isha: Double?, val ishaMinutes: Int?, val maghrib: Double?)

    private val METHODS = mapOf(
        "karachi" to Method(18.0, 18.0, null, null),
        "mwl" to Method(18.0, 17.0, null, null),
        "isna" to Method(15.0, 15.0, null, null),
        "makkah" to Method(18.5, null, 90, null),
        "egypt" to Method(19.5, 17.5, null, null),
        "dubai" to Method(18.2, 18.2, null, null),
        "singapore" to Method(20.0, 18.0, null, null),
        "turkey" to Method(18.0, 17.0, null, null),
        "tehran" to Method(17.7, 14.0, null, 4.5),
        "jafari" to Method(16.0, 14.0, null, 4.0),
    )

    private fun rad(d: Double) = Math.toRadians(d)
    private fun deg(r: Double) = Math.toDegrees(r)
    private fun dsin(d: Double) = sin(rad(d))
    private fun dcos(d: Double) = cos(rad(d))
    private fun dtan(d: Double) = tan(rad(d))
    private fun fix(a: Double, b: Double): Double { val r = a - b * floor(a / b); return if (r < 0) r + b else r }

    private fun julian(year: Int, month: Int, day: Int): Double {
        var y = year; var m = month
        if (m <= 2) { y -= 1; m += 12 }
        val a = floor(y / 100.0); val b = 2 - a + floor(a / 4)
        return floor(365.25 * (y + 4716)) + floor(30.6001 * (m + 1)) + day + b - 1524.5
    }

    private fun sun(jd: Double): Pair<Double, Double> {
        val d = jd - 2451545.0
        val g = fix(357.529 + 0.98560028 * d, 360.0)
        val q = fix(280.459 + 0.98564736 * d, 360.0)
        val l = fix(q + 1.915 * dsin(g) + 0.020 * dsin(2 * g), 360.0)
        val e = 23.439 - 0.00000036 * d
        val ra = fix(deg(atan2(dcos(e) * dsin(l), dcos(l))) / 15, 24.0)
        return deg(asin(dsin(e) * dsin(l))) to (q / 15 - ra)
    }

    /** {fajr, sunrise, dhuhr, asr, maghrib, isha} -> epoch ms, for `date` where the place is. */
    fun forDay(date: LocalDate, s: JSONObject): Map<String, Long> {
        val lat = s.optDouble("lat"); val lng = s.optDouble("lng")
        val m = METHODS[s.optString("method")] ?: METHODS.getValue("karachi")
        val factor = if (s.optString("asr", "hanafi") == "hanafi") 2.0 else 1.0
        val highLat = s.optString("high_lat", "angle")
        val jd0 = julian(date.year, date.monthValue, date.dayOfMonth) - lng / (15 * 24)

        fun midDay(t: Double) = fix(12 - sun(jd0 + t / 24).second, 24.0)
        fun angleTime(angle: Double, t: Double, before: Boolean): Double {
            val decl = sun(jd0 + t / 24).first
            val h = deg(acos((-dsin(angle) - dsin(decl) * dsin(lat)) / (dcos(decl) * dcos(lat)))) / 15
            val noon = midDay(t)
            return if (before) noon - h else noon + h
        }
        fun asrTime(t: Double): Double {
            val decl = sun(jd0 + t / 24).first
            val angle = -deg(atan(1 / (factor + dtan(abs(lat - decl)))))
            return angleTime(angle, t, false)
        }

        var fajr = 5.0; var sunrise = 6.0; var dhuhr = 12.0; var asr = 13.0; var sunset = 18.0; var maghrib = 18.0; var isha = 18.0
        repeat(2) {
            fajr = angleTime(m.fajr, fajr, true)
            sunrise = angleTime(0.833, sunrise, true)
            dhuhr = midDay(dhuhr)
            asr = asrTime(asr)
            sunset = angleTime(0.833, sunset, false)
            maghrib = angleTime(m.maghrib ?: 0.833, maghrib, false)
            if (m.isha != null) isha = angleTime(m.isha, isha, false)
        }
        if (m.ishaMinutes != null) isha = maghrib + m.ishaMinutes / 60.0

        val night = 24 + sunrise - sunset
        if (highLat != "none" && night.isFinite()) {
            fun part(angle: Double) = when (highLat) { "midnight" -> 0.5; "seventh" -> 1.0 / 7; else -> angle / 60 }
            val fajrMax = part(m.fajr) * night
            if (!fajr.isFinite() || sunrise - fajr > fajrMax) fajr = sunrise - fajrMax
            if (m.isha != null) {
                val ishaMax = part(m.isha) * night
                if (!isha.isFinite() || isha - sunset > ishaMax) isha = sunset + ishaMax
            }
            if (m.maghrib != null) {
                val mMax = part(m.maghrib) * night
                if (!maghrib.isFinite() || maghrib - sunset > mMax) maghrib = sunset + mMax
            }
        }

        val base = date.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
        val offsets = s.optJSONObject("offsets") ?: JSONObject()
        fun at(name: String, hours: Double): Long =
            base + (((hours - lng / 15) * 60 + offsets.optInt(name, 0)) * 60_000).roundToLong()
        return mapOf("fajr" to at("fajr", fajr), "sunrise" to at("sunrise", sunrise), "dhuhr" to at("dhuhr", dhuhr),
                     "asr" to at("asr", asr), "maghrib" to at("maghrib", maghrib), "isha" to at("isha", isha))
    }
}
