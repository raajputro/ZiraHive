package app.zirahive.android.share

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.text.InputType
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.workDataOf
import app.zirahive.android.R
import app.zirahive.android.Server
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/**
 * "Share → ZiraHive" from any app (Gallery, WhatsApp, a PDF from Downloads): asks which folder,
 * copies the files while this screen is open (the sharing app's permission ends when it closes),
 * then [ShareUploadWorker] sends them in the background.
 */
class ShareActivity : AppCompatActivity() {

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Server.isSetUp(this)) {
            Toast.makeText(this, R.string.share_not_set_up, Toast.LENGTH_LONG).show()
            finish()
            return
        }
        val uris = sharedUris(intent)
        val text = if (uris.isEmpty()) intent.getStringExtra(Intent.EXTRA_TEXT) else null
        if (uris.isEmpty() && text.isNullOrBlank()) { finish(); return }
        val count = if (uris.isEmpty()) 1 else uris.size

        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(24), dp(20), dp(24), dp(16)) }
        box.addView(TextView(this).apply { text = getString(R.string.share_title); textSize = 20f })
        box.addView(TextView(this).apply {
            text = getString(R.string.share_count, count); setPadding(0, dp(4), 0, dp(16))
        })
        val folderBox = TextInputLayout(this).apply { hint = getString(R.string.share_folder) }
        val folder = TextInputEditText(folderBox.context).apply {
            setText(getSharedPreferences("share", MODE_PRIVATE).getString("folder", "/From phone"))
            inputType = InputType.TYPE_CLASS_TEXT
            isSingleLine = true
        }
        folderBox.addView(folder)
        box.addView(folderBox)
        val busy = ProgressBar(this).apply { visibility = View.GONE }
        val busyText = TextView(this).apply { text = getString(R.string.share_preparing); visibility = View.GONE }
        box.addView(busy); box.addView(busyText)
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(16), 0, 0) }
        val cancel = MaterialButton(this, null, com.google.android.material.R.attr.borderlessButtonStyle).apply {
            text = getString(R.string.share_cancel); setOnClickListener { finish() }
        }
        val send = MaterialButton(this).apply { text = getString(R.string.share_send) }
        row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))
        row.addView(cancel); row.addView(send)
        box.addView(row)
        setContentView(box)

        send.setOnClickListener {
            val dest = "/" + (folder.text?.toString() ?: "").trim().trim('/').ifBlank { "From phone" }
            getSharedPreferences("share", MODE_PRIVATE).edit().putString("folder", dest).apply()
            send.isEnabled = false; cancel.isEnabled = false
            busy.visibility = View.VISIBLE; busyText.visibility = View.VISIBLE
            lifecycleScope.launch {
                val dir = File(cacheDir, "share/" + UUID.randomUUID()).apply { mkdirs() }
                val files = withContext(Dispatchers.IO) {
                    if (uris.isEmpty()) {
                        val stamp = SimpleDateFormat("yyyy-MM-dd HH.mm", Locale.US).format(Date())
                        listOf(File(dir, "Shared text $stamp.txt").apply { writeText(text!!) })
                    } else uris.mapNotNull { copy(it, dir) }
                }
                if (files.isEmpty()) {
                    Toast.makeText(this@ShareActivity, R.string.share_failed, Toast.LENGTH_LONG).show()
                    finish()
                    return@launch
                }
                val req = OneTimeWorkRequestBuilder<ShareUploadWorker>()
                    .setInputData(workDataOf(ShareUploadWorker.KEY_DIR to dir.absolutePath, ShareUploadWorker.KEY_FOLDER to dest))
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                    .build()
                WorkManager.getInstance(this@ShareActivity).enqueue(req)
                finish()
            }
        }
    }

    private fun sharedUris(i: Intent): List<Uri> = when (i.action) {
        Intent.ACTION_SEND -> listOfNotNull(
            if (Build.VERSION.SDK_INT >= 33) i.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else @Suppress("DEPRECATION") i.getParcelableExtra(Intent.EXTRA_STREAM))
        Intent.ACTION_SEND_MULTIPLE -> (if (Build.VERSION.SDK_INT >= 33) i.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else @Suppress("DEPRECATION") i.getParcelableArrayListExtra(Intent.EXTRA_STREAM)) ?: emptyList()
        else -> emptyList()
    }

    private fun copy(uri: Uri, dir: File): File? = try {
        var name = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        } ?: uri.lastPathSegment?.substringAfterLast('/') ?: "file"
        name = name.replace(Regex("[\\\\/:*?\"<>|]"), "_")
        var target = File(dir, name)
        var n = 2
        while (target.exists()) { target = File(dir, name.substringBeforeLast('.') + " ($n)" + name.substringAfterLast('.', "").let { if (it.isEmpty()) "" else ".$it" }); n++ }
        contentResolver.openInputStream(uri)!!.use { input -> target.outputStream().use { input.copyTo(it) } }
        target
    } catch (e: Exception) {
        null
    }
}
