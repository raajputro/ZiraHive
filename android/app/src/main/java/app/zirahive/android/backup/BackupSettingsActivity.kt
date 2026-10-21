package app.zirahive.android.backup

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.provider.Settings
import android.text.format.DateUtils
import android.view.View
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.lifecycleScope
import app.zirahive.android.R
import com.google.android.material.button.MaterialButton
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Phone backup: on/off, Wi-Fi and charging rules, which folders, and "Back up now". */
class BackupSettingsActivity : AppCompatActivity() {

    private lateinit var column: LinearLayout
    private lateinit var status: TextView
    private lateinit var notice: TextView
    private lateinit var enable: MaterialSwitch
    private lateinit var folders: LinearLayout

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private val askMedia = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { _ ->
        if (Backup.canRead(this)) {
            Backup.set(this, "enabled", true)
            askNotifications()
            Backup.now(this)
        } else {
            enable.isChecked = false
        }
        refresh()
    }

    private val askNotify = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(20), dp(24), dp(20), dp(32)) }
        column.addView(TextView(this).apply {
            text = getString(R.string.backup_title); textSize = 24f; setTextColor(getColor(R.color.ink))
        })
        status = TextView(this).apply { textSize = 14f; setTextColor(getColor(R.color.muted)); setPadding(0, dp(6), 0, dp(12)) }
        column.addView(status)
        notice = TextView(this).apply {
            textSize = 14f; setTextColor(getColor(R.color.jute)); setPadding(0, 0, 0, dp(12)); visibility = View.GONE
            setOnClickListener { openAppSettings() }
        }
        column.addView(notice)

        enable = switch(R.string.backup_enable, Backup.enabled(this)) { on ->
            if (on && !Backup.canRead(this)) askMedia.launch(Backup.mediaPermissions())
            else { Backup.set(this, "enabled", on); if (on) { askNotifications(); Backup.now(this) } }
            refresh()
        }
        column.addView(TextView(this).apply {
            text = getString(R.string.backup_enable_note); textSize = 13f; setTextColor(getColor(R.color.muted))
            setPadding(0, 0, 0, dp(12))
        })
        switch(R.string.backup_wifi, Backup.wifiOnly(this)) { Backup.set(this, "wifi", it) }
        switch(R.string.backup_charging, Backup.chargingOnly(this)) { Backup.set(this, "charging", it) }
        switch(R.string.backup_videos, Backup.videos(this)) { Backup.set(this, "videos", it) }
        switch(R.string.backup_existing, Backup.existing(this)) { Backup.set(this, "existing", it) }

        column.addView(MaterialButton(this).apply {
            text = getString(R.string.backup_now)
            setOnClickListener { Backup.now(this@BackupSettingsActivity); refresh(running = true) }
        }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) })

        column.addView(TextView(this).apply {
            text = getString(R.string.backup_folders); textSize = 18f; setTextColor(getColor(R.color.ink)); setPadding(0, dp(28), 0, dp(4))
        })
        column.addView(TextView(this).apply {
            text = getString(R.string.backup_folders_note); textSize = 13f; setTextColor(getColor(R.color.muted)); setPadding(0, 0, 0, dp(8))
        })
        folders = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        column.addView(folders)

        val scroll = ScrollView(this).apply { addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.updatePadding(top = bars.top, bottom = bars.bottom)
            insets
        }
        setContentView(scroll)
    }

    override fun onResume() {
        super.onResume()
        refresh()
        loadFolders()
    }

    private fun switch(label: Int, value: Boolean, onChange: (Boolean) -> Unit): MaterialSwitch {
        val s = MaterialSwitch(this).apply {
            text = getString(label); textSize = 16f; isChecked = value
            setTextColor(getColor(R.color.ink))
            setPadding(0, dp(6), 0, dp(6))
            setOnCheckedChangeListener { _, on -> onChange(on) }
        }
        column.addView(s, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        return s
    }

    private fun refresh(running: Boolean = false) {
        val last = Backup.lastRun(this)
        status.text = when {
            running || Backup.isRunning(this) -> getString(R.string.backup_status_running)
            last == 0L -> getString(R.string.backup_status_never)
            else -> getString(R.string.backup_status_last,
                DateUtils.getRelativeTimeSpanString(last, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS),
                BackupStore(this).count())
        }
        when {
            Backup.enabled(this) && Backup.hasPartialAccess(this) -> { notice.text = getString(R.string.backup_partial_permission); notice.visibility = View.VISIBLE }
            Backup.enabled(this) && !Backup.canRead(this) -> { notice.text = getString(R.string.backup_need_permission); notice.visibility = View.VISIBLE }
            else -> notice.visibility = View.GONE
        }
        if (running) lifecycleScope.launch { delay(4000); refresh() }
    }

    /** The phone's photo folders (Camera, WhatsApp Images, Screenshots…) with how many in each. */
    private fun loadFolders() {
        if (!Backup.canRead(this)) { folders.removeAllViews(); return }
        lifecycleScope.launch {
            val counts = withContext(Dispatchers.IO) {
                val m = sortedMapOf<String, Int>(String.CASE_INSENSITIVE_ORDER)
                for (uri in listOf(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, MediaStore.Video.Media.EXTERNAL_CONTENT_URI)) {
                    contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.BUCKET_DISPLAY_NAME), null, null, null)?.use { c ->
                        while (c.moveToNext()) { val b = c.getString(0) ?: continue; m[b] = (m[b] ?: 0) + 1 }
                    }
                }
                m
            }
            val excluded = Backup.excludedFolders(this@BackupSettingsActivity).toMutableSet()
            folders.removeAllViews()
            for ((name, n) in counts) {
                folders.addView(CheckBox(this@BackupSettingsActivity).apply {
                    text = "$name  ($n)"
                    setTextColor(getColor(R.color.ink))
                    isChecked = name !in excluded
                    setOnCheckedChangeListener { _, on ->
                        if (on) excluded -= name else excluded += name
                        Backup.setExcluded(this@BackupSettingsActivity, excluded)
                    }
                })
            }
        }
    }

    private fun askNotifications() {
        if (Build.VERSION.SDK_INT >= 33) askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun openAppSettings() {
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
    }
}
