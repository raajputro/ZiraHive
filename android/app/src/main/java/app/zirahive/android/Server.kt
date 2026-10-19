package app.zirahive.android

import android.content.Context
import android.os.Build
import android.webkit.CookieManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Raised when the server says we aren't signed in (or the session expired). */
class SignedOut : IOException("signed out")

/**
 * Where ZiraHive is and how to talk to it. The phone knows up to two addresses: the one at home
 * (http://192.168.0.10:8080) and, optionally, one for away from home (Tailscale). The sign-in is
 * the web page's own session cookie, which the app's built-in browser shares with this code, so
 * signing in once on the page is enough for backups, sharing and notifications too.
 */
object Server {
    private const val PREFS = "server"
    private var resolved: String? = null
    private var resolvedAt = 0L

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val quick: OkHttpClient = http.newBuilder()
        .connectTimeout(2, TimeUnit.SECONDS).readTimeout(3, TimeUnit.SECONDS).build()

    fun userAgent(): String =
        "ZiraHiveApp/${BuildConfig.VERSION_NAME} (Android ${Build.VERSION.RELEASE}; ${Build.MODEL})"

    /** "Samsung SM-A546E" style name, shown in backup notifications ("from Samsung SM-A546E"). */
    fun deviceName(): String {
        val maker = Build.MANUFACTURER.replaceFirstChar { it.uppercase() }
        return if (Build.MODEL.startsWith(Build.MANUFACTURER, ignoreCase = true)) Build.MODEL else "$maker ${Build.MODEL}"
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun home(ctx: Context): String? = prefs(ctx).getString("home", null)
    fun away(ctx: Context): String? = prefs(ctx).getString("away", null)
    fun isSetUp(ctx: Context) = home(ctx) != null

    fun save(ctx: Context, home: String, away: String?) {
        prefs(ctx).edit().putString("home", home).putString("away", away).apply()
        resolved = null
    }

    /** "192.168.0.10:8080" -> "http://192.168.0.10:8080"; a tidy origin without a trailing slash. */
    fun normalize(input: String): String? {
        var s = input.trim().trimEnd('/')
        if (s.isEmpty()) return null
        if (!s.startsWith("http://", true) && !s.startsWith("https://", true)) {
            s = if (s.contains(".ts.net") || s.contains("zirahive.") && !s.contains(":")) "https://$s" else "http://$s"
        }
        return try {
            val u = java.net.URI(s)
            if (u.host.isNullOrEmpty()) null else "${u.scheme}://${u.host}${if (u.port > 0) ":${u.port}" else ""}"
        } catch (e: Exception) {
            null
        }
    }

    /** True when ZiraHive answers at this address. */
    suspend fun answers(base: String, client: OkHttpClient = quick): Boolean = withContext(Dispatchers.IO) {
        try {
            client.newCall(Request.Builder().url("$base/api/health").header("User-Agent", userAgent()).build())
                .execute().use { r -> r.isSuccessful && (r.body?.string() ?: "").contains("\"ok\"") }
        } catch (e: Exception) {
            false
        }
    }

    /** The address to use right now: home when it answers, otherwise the away address. */
    suspend fun base(ctx: Context, fresh: Boolean = false): String? {
        val home = home(ctx) ?: return null
        val away = away(ctx)
        val cached = resolved
        if (!fresh && cached != null && System.currentTimeMillis() - resolvedAt < 5 * 60_000) return cached
        val pick = when {
            away == null -> home
            answers(home) -> home
            answers(away) -> away
            else -> home
        }
        resolved = pick
        resolvedAt = System.currentTimeMillis()
        return pick
    }

    /** The session cookie for this address (the same sign-in works at home and away). */
    fun cookie(ctx: Context, base: String): String? {
        val cm = CookieManager.getInstance()
        return cm.getCookie(base)?.takeIf { it.contains("zirahive_token") || it.contains("gharbox_token") }
            ?: listOfNotNull(home(ctx), away(ctx)).firstNotNullOfOrNull { other ->
                cm.getCookie(other)?.takeIf { it.contains("zirahive_token") || it.contains("gharbox_token") }
            }
    }

    /**
     * A sign-in just for this phone's background work, lasting a year (the page's own sign-in
     * lasts 30 days, and backups shouldn't stop because nobody opened the app for a month).
     * "Sign out everywhere" or a new password still ends it.
     */
    fun deviceToken(ctx: Context): String? = prefs(ctx).getString("device_token", null)

    fun forgetDeviceToken(ctx: Context) {
        prefs(ctx).edit().remove("device_token").remove("device_user").remove("device_token_at").apply()
    }

    /** Gets (or, once a month, renews) the device sign-in while the page is signed in. It is
     *  always for whoever is signed in on the page: another family member signing in on this
     *  phone gets their own, so backups go to the right account. */
    suspend fun ensureDeviceToken(ctx: Context, base: String) {
        val p = prefs(ctx)
        val cookie = cookie(ctx, base) ?: return
        val pageUser = try {
            call(Request.Builder().url("$base/api/auth/me").header("User-Agent", userAgent()).header("Cookie", cookie).build())
                .use { JSONObject(it.body!!.string()).getString("id") }
        } catch (e: Exception) { return }
        val fresh = System.currentTimeMillis() - p.getLong("device_token_at", 0) < 30L * 24 * 3600_000
        if (deviceToken(ctx) != null && fresh && p.getString("device_user", null) == pageUser) return
        try {
            val req = Request.Builder().url("$base/api/auth/device-token").header("User-Agent", userAgent())
                .header("Cookie", cookie).post(jsonBody(JSONObject())).build()
            val token = call(req).use { JSONObject(it.body!!.string()).getString("token") }
            p.edit().putString("device_token", token).putString("device_user", pageUser)
                .putLong("device_token_at", System.currentTimeMillis()).apply()
        } catch (e: Exception) { /* next time */ }
    }

    fun isSignedIn(ctx: Context): Boolean =
        deviceToken(ctx) != null || listOfNotNull(home(ctx), away(ctx)).any { cookie(ctx, it) != null }

    fun request(ctx: Context, base: String, path: String): Request.Builder {
        val b = Request.Builder().url(base + path).header("User-Agent", userAgent())
        val token = deviceToken(ctx)
        if (token != null) b.header("Authorization", "Bearer $token")
        else cookie(ctx, base)?.let { b.header("Cookie", it) }
        return b
    }

    private val JSON = "application/json".toMediaType()

    fun jsonBody(o: JSONObject) = o.toString().toRequestBody(JSON)

    /** Runs a call; 401 becomes [SignedOut], other failures an IOException with the server's message. */
    suspend fun call(req: Request): Response = withContext(Dispatchers.IO) {
        val r = http.newCall(req).execute()
        if (r.code == 401) { r.close(); throw SignedOut() }
        if (!r.isSuccessful) {
            val msg = try { JSONObject(r.body?.string() ?: "").optString("detail", r.message) } catch (e: Exception) { r.message }
            r.close()
            throw IOException("${r.code} $msg")
        }
        r
    }

    suspend fun getJson(ctx: Context, base: String, path: String): JSONObject =
        call(request(ctx, base, path).get().build()).use { JSONObject(it.body!!.string()) }

    suspend fun postJson(ctx: Context, base: String, path: String, body: JSONObject): String =
        call(request(ctx, base, path).post(jsonBody(body)).build()).use { it.body?.string() ?: "" }

    suspend fun putJson(ctx: Context, base: String, path: String, body: JSONObject) {
        call(request(ctx, base, path).put(jsonBody(body)).build()).close()
    }
}
