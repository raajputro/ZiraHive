package app.zirahive.android

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.lifecycleScope
import app.zirahive.android.backup.Backup
import app.zirahive.android.notify.NotificationPoller
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import kotlinx.coroutines.launch

/** First run (or "Change address"): where is ZiraHive? */
class SetupActivity : AppCompatActivity() {

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(48), dp(24), dp(24))
        }
        val title = TextView(this).apply {
            text = getString(R.string.setup_title)
            textSize = 24f
            setTextColor(getColor(R.color.ink))
        }
        val intro = TextView(this).apply {
            text = getString(R.string.setup_intro)
            textSize = 15f
            setTextColor(getColor(R.color.muted))
            setPadding(0, dp(8), 0, dp(20))
        }
        fun field(label: Int, hint: Int, value: String?): Pair<TextInputLayout, TextInputEditText> {
            val box = TextInputLayout(this).apply {
                this.hint = getString(label)
                placeholderText = getString(hint)
                setPadding(0, 0, 0, dp(12))
            }
            val edit = TextInputEditText(box.context).apply {
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
                isSingleLine = true
                setText(value ?: "")
            }
            box.addView(edit)
            return box to edit
        }
        val (homeBox, home) = field(R.string.setup_home, R.string.setup_home_hint, Server.home(this))
        val (awayBox, away) = field(R.string.setup_away, R.string.setup_away_hint, Server.away(this))
        away.imeOptions = EditorInfo.IME_ACTION_DONE
        val status = TextView(this).apply {
            textSize = 14f
            setTextColor(getColor(R.color.jute))
            setPadding(0, dp(4), 0, dp(12))
            visibility = View.GONE
        }
        val connect = MaterialButton(this).apply { text = getString(R.string.setup_connect) }

        fun go() {
            val h = Server.normalize(home.text?.toString() ?: "")
            val a = Server.normalize(away.text?.toString() ?: "")
            homeBox.error = null
            if (h == null) { homeBox.error = getString(R.string.setup_need_home); return }
            connect.isEnabled = false
            status.visibility = View.VISIBLE
            status.text = getString(R.string.setup_checking)
            lifecycleScope.launch {
                val ok = Server.answers(h) || (a != null && Server.answers(a))
                connect.isEnabled = true
                if (!ok) {
                    status.text = getString(R.string.setup_unreachable, h)
                    return@launch
                }
                Server.save(this@SetupActivity, h, a)
                Backup.schedule(this@SetupActivity)
                NotificationPoller.schedule(this@SetupActivity)
                startActivity(Intent(this@SetupActivity, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK))
                finish()
            }
        }
        connect.setOnClickListener { go() }
        away.setOnEditorActionListener { _, _, _ -> go(); true }

        listOf(title, intro, homeBox, awayBox, status, connect).forEach { column.addView(it) }
        (connect.layoutParams as LinearLayout.LayoutParams).gravity = Gravity.END
        val scroll = ScrollView(this).apply { addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.updatePadding(top = bars.top, bottom = bars.bottom)
            insets
        }
        setContentView(scroll)
    }
}
