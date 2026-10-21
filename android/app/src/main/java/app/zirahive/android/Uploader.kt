package app.zirahive.android

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.security.MessageDigest

/**
 * ZiraHive's resumable upload (the same protocol the web app and the PC sync use):
 *   POST /api/uploads {filename, size, sha256, ...}  -> {id, offset} or {status: "exists"}
 *   PATCH /api/uploads/{id} with bytes and Upload-Offset, until it says "complete".
 * A dropped connection carries on from where the server says it got to.
 */
class Uploader(private val ctx: Context, private val base: String) {

    data class Result(val existed: Boolean, val assetId: String?)

    suspend fun alreadyBackedUp(hashes: List<String>): Set<String> {
        if (hashes.isEmpty()) return emptySet()
        val out = mutableSetOf<String>()
        for (chunk in hashes.chunked(1000)) {
            val r = JSONObject(Server.postJson(ctx, base, "/api/uploads/check",
                JSONObject().put("sha256", JSONArray(chunk))))
            val e = r.optJSONArray("existing") ?: continue
            for (i in 0 until e.length()) out += e.getString(i).lowercase()
        }
        return out
    }

    /**
     * Sends one file. [open] opens it from the start each time it's called; [resumeId] is an
     * unfinished upload from an earlier try, [onStarted] remembers a new one so a later try can
     * carry on, [onProgress] gets bytes sent.
     */
    suspend fun send(
        name: String, size: Long, sha256: String?, folder: String, open: () -> InputStream,
        takenAt: String? = null, deviceAssetId: String? = null, dedupe: Boolean = true,
        resumeId: String? = null, onStarted: (String) -> Unit = {}, onProgress: (Long) -> Unit = {},
    ): Result = withContext(Dispatchers.IO) {
        var id: String? = null
        var offset = 0L
        if (resumeId != null) {
            try {
                val st = Server.getJson(ctx, base, "/api/uploads/$resumeId")
                if (st.optString("status") == "complete") return@withContext Result(false, st.optJSONObject("asset")?.optString("id"))
                id = resumeId
                offset = st.optLong("offset", 0)
            } catch (e: SignedOut) {
                throw e
            } catch (e: Exception) {
                id = null  // gone (cleaned up on the server): start again
            }
        }
        if (id == null) {
            val body = JSONObject().put("filename", name).put("size", size).put("folder", folder).put("dedupe", dedupe)
            sha256?.let { body.put("sha256", it) }
            takenAt?.let { body.put("taken_at", it) }
            deviceAssetId?.let { body.put("device_asset_id", it) }
            val r = JSONObject(Server.postJson(ctx, base, "/api/uploads", body))
            if (r.optString("status") == "exists") return@withContext Result(true, r.optJSONObject("asset")?.optString("id"))
            id = r.getString("id")
            offset = r.optLong("offset", 0)
            onStarted(id)
        }
        val octets = "application/offset+octet-stream".toMediaType()
        open().use { input ->
            skipFully(input, offset)
            val buf = ByteArray(CHUNK)
            while (offset < size) {
                val n = readUpTo(input, buf, minOf(CHUNK.toLong(), size - offset).toInt())
                if (n <= 0) break
                val req = Server.request(ctx, base, "/api/uploads/$id")
                    .patch(buf.copyOf(n).toRequestBody(octets))
                    .header("Upload-Offset", offset.toString())
                    .build()
                val r = Server.call(req).use { JSONObject(it.body!!.string()) }
                offset = r.optLong("offset", offset + n)
                onProgress(offset)
                if (r.optString("status") == "complete" || r.optString("status") == "exists") {
                    return@withContext Result(r.optString("status") == "exists", r.optJSONObject("asset")?.optString("id"))
                }
            }
        }
        val st = Server.getJson(ctx, base, "/api/uploads/$id")
        if (st.optString("status") != "complete") throw java.io.IOException("upload didn't finish")
        Result(false, st.optJSONObject("asset")?.optString("id"))
    }

    companion object {
        const val CHUNK = 4 * 1024 * 1024

        fun sha256(input: InputStream): String {
            val md = MessageDigest.getInstance("SHA-256")
            val buf = ByteArray(1 shl 20)
            input.use {
                while (true) {
                    val n = it.read(buf)
                    if (n < 0) break
                    md.update(buf, 0, n)
                }
            }
            return md.digest().joinToString("") { "%02x".format(it) }
        }

        private fun skipFully(input: InputStream, n: Long) {
            var left = n
            val buf = ByteArray(64 * 1024)
            while (left > 0) {
                val skipped = input.skip(left)
                if (skipped > 0) { left -= skipped; continue }
                val r = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                if (r < 0) throw java.io.EOFException()
                left -= r
            }
        }

        private fun readUpTo(input: InputStream, buf: ByteArray, max: Int): Int {
            var total = 0
            while (total < max) {
                val r = input.read(buf, total, max - total)
                if (r < 0) break
                total += r
            }
            return total
        }
    }
}
