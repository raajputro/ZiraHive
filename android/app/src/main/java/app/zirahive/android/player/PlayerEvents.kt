package app.zirahive.android.player

import org.json.JSONObject

/** Hands "the player closed, here is where it stopped" from the player back to the web page. */
object PlayerEvents {
    @Volatile var listener: ((JSONObject) -> Unit)? = null
    @Volatile private var pending: JSONObject? = null

    fun closed(result: JSONObject) {
        val l = listener
        if (l != null) l(result) else pending = result
    }

    fun takePending(): JSONObject? = pending.also { pending = null }
}
