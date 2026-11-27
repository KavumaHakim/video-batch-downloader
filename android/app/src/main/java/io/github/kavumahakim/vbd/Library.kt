package io.github.kavumahakim.vbd

import android.content.ContentUris
import android.app.RecoverableSecurityException
import android.content.Context
import android.content.IntentSender
import android.media.MediaScannerConnection
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.LruCache
import android.util.Size
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

data class LibraryItem(
    val uri: Uri,
    val name: String,
    val mime: String,
    val folder: String,
    val size: Long,
    val added: Long,
    /** The file itself on Android 9 and older, where there is no MediaStore entry to delete. */
    val file: File? = null,
) {
    val audio: Boolean get() = mime.startsWith("audio/")
    val title: String get() = name.substringBeforeLast('.')
    fun toPlayItem() = PlayItem(uri, title, folder, "", mime)
}

/** What this app has saved into Download/Video Batch Downloader, newest first. */
object Library {
    suspend fun load(context: Context): List<LibraryItem> = withContext(Dispatchers.IO) {
        val items = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) fromMediaStore(context) else fromFolder(context)
        items.filter { it.mime.startsWith("video/") || it.mime.startsWith("audio/") }.sortedByDescending { it.added }
    }

    private fun fromMediaStore(context: Context): List<LibraryItem> {
        val root = "${Environment.DIRECTORY_DOWNLOADS}/${MediaSaver.FOLDER}/"
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val columns = arrayOf(
            MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.RELATIVE_PATH, MediaStore.MediaColumns.SIZE, MediaStore.MediaColumns.DATE_ADDED,
        )
        val out = mutableListOf<LibraryItem>()
        context.contentResolver.query(
            collection, columns, "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?", arrayOf("$root%"), null,
        )?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(1) ?: continue
                val path = c.getString(3).orEmpty()
                out += LibraryItem(
                    uri = ContentUris.withAppendedId(collection, c.getLong(0)),
                    name = name,
                    mime = c.getString(2) ?: MediaSaver.mimeOf(name),
                    folder = path.removePrefix(root).trimEnd('/'),
                    size = c.getLong(4),
                    added = c.getLong(5),
                )
            }
        }
        return out
    }

    @Suppress("DEPRECATION")
    private fun fromFolder(context: Context): List<LibraryItem> {
        val root = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), MediaSaver.FOLDER)
        if (!root.isDirectory) return emptyList()
        return root.walkTopDown().filter { it.isFile }.map { f ->
            LibraryItem(
                uri = FileProvider.getUriForFile(context, "${context.packageName}.files", f),
                name = f.name,
                mime = MediaSaver.mimeOf(f.name),
                folder = f.parentFile?.takeIf { it != root }?.name.orEmpty(),
                size = f.length(),
                added = f.lastModified() / 1000,
                file = f,
            )
        }.toList()
    }

    /**
     * Deletes a saved file. Returns null when it is gone, or the request Android
     * wants the user to confirm, for a file an earlier install of the app saved.
     */
    fun delete(context: Context, item: LibraryItem): IntentSender? {
        thumbs.remove(item.uri.toString())
        if (item.file != null) {
            if (!item.file.delete()) throw IOException("Could not delete ${item.name}")
            MediaScannerConnection.scanFile(context, arrayOf(item.file.path), null, null)
            return null
        }
        return try {
            context.contentResolver.delete(item.uri, null, null)
            null
        } catch (e: SecurityException) {
            when {
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.R ->
                    MediaStore.createDeleteRequest(context.contentResolver, listOf(item.uri)).intentSender
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && e is RecoverableSecurityException ->
                    e.userAction.actionIntent.intentSender
                else -> throw e
            }
        }
    }

    // ------------------------------------------------------------ thumbnails

    private val thumbs = LruCache<String, Bitmap>(80)

    /** A video frame or embedded cover art, or null when the file has neither. */
    suspend fun thumbnail(context: Context, uri: Uri, audio: Boolean): Bitmap? = withContext(Dispatchers.IO) {
        thumbs.get(uri.toString())?.let { return@withContext it }
        val bitmap = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && uri.authority == MediaStore.AUTHORITY) {
                context.contentResolver.loadThumbnail(uri, Size(480, 270), null)
            } else {
                val r = MediaMetadataRetriever()
                try {
                    r.setDataSource(context, uri)
                    if (audio) r.embeddedPicture?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
                    else r.getFrameAtTime(2_000_000)
                } finally {
                    r.release()
                }
            }
        } catch (_: Exception) {
            null
        }
        bitmap?.also { thumbs.put(uri.toString(), it) }
    }
}
