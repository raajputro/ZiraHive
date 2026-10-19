package app.zirahive.android.backup

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * What this phone has already backed up, so each photo is read and hashed only once.
 *   done:    gallery item -> its SHA-256 (backed up, or found already on the server)
 *   partial: gallery item -> an unfinished upload on the server, to carry on next time
 */
class BackupStore(ctx: Context) : SQLiteOpenHelper(ctx.applicationContext, "backup.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE done (item TEXT PRIMARY KEY, sha TEXT NOT NULL, at INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE partial (item TEXT PRIMARY KEY, upload TEXT NOT NULL, sha TEXT)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {}

    fun doneItems(): Set<String> = readableDatabase.rawQuery("SELECT item FROM done", null).use { c ->
        buildSet { while (c.moveToNext()) add(c.getString(0)) }
    }

    fun count(): Int = readableDatabase.rawQuery("SELECT COUNT(*) FROM done", null).use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }

    fun markDone(item: String, sha: String) {
        writableDatabase.insertWithOnConflict("done", null, ContentValues().apply {
            put("item", item); put("sha", sha); put("at", System.currentTimeMillis())
        }, SQLiteDatabase.CONFLICT_REPLACE)
        writableDatabase.delete("partial", "item = ?", arrayOf(item))
    }

    fun partial(item: String): Pair<String, String?>? =
        readableDatabase.rawQuery("SELECT upload, sha FROM partial WHERE item = ?", arrayOf(item)).use { c ->
            if (c.moveToFirst()) c.getString(0) to c.getString(1) else null
        }

    fun markPartial(item: String, upload: String, sha: String) {
        writableDatabase.insertWithOnConflict("partial", null, ContentValues().apply {
            put("item", item); put("upload", upload); put("sha", sha)
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun clearPartial(item: String) { writableDatabase.delete("partial", "item = ?", arrayOf(item)) }
}
