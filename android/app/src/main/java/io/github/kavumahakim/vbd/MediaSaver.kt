package io.github.kavumahakim.vbd

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import androidx.annotation.RequiresApi
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException

data class SavedFile(val uri: Uri, val mime: String, val name: String)

/**
 * yt-dlp writes into the app's private cache; finished files are copied into
 * the phone's shared Download folder, where galleries, music players and file
 * managers can see them.
 */
object MediaSaver {
    const val FOLDER = "Video Batch Downloader"
    val LOCATION = "Download/$FOLDER"

    fun mimeOf(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: when (ext) {
            "opus" -> "audio/ogg"
            "m4a" -> "audio/mp4"
            "flac" -> "audio/flac"
            "mkv" -> "video/x-matroska"
            "webm" -> "video/webm"
            "srt" -> "application/x-subrip"
            else -> "application/octet-stream"
        }
    }

    fun save(context: Context, file: File, subfolder: String?): SavedFile {
        val mime = mimeOf(file.name)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveToMediaStore(context, file, subfolder, mime)
        } else {
            saveLegacy(context, file, subfolder, mime)
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun saveToMediaStore(context: Context, file: File, subfolder: String?, mime: String): SavedFile {
        val resolver = context.contentResolver
        val relativePath = listOfNotNull(Environment.DIRECTORY_DOWNLOADS, FOLDER, subfolder).joinToString("/")
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("Android would not create ${file.name} in Downloads")
        try {
            val out = resolver.openOutputStream(uri) ?: throw IOException("Could not write ${file.name}")
            out.use { sink -> file.inputStream().use { it.copyTo(sink) } }
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
        return SavedFile(uri, mime, file.name)
    }

    @Suppress("DEPRECATION")
    private fun saveLegacy(context: Context, file: File, subfolder: String?, mime: String): SavedFile {
        var dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), FOLDER)
        if (subfolder != null) dir = File(dir, subfolder)
        if (!dir.isDirectory && !dir.mkdirs()) throw IOException("Could not create $dir")
        var target = File(dir, file.name)
        var n = 1
        while (target.exists()) {
            target = File(dir, "${file.nameWithoutExtension} ($n).${file.extension}")
            n++
        }
        file.copyTo(target)
        MediaScannerConnection.scanFile(context, arrayOf(target.path), arrayOf(mime), null)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", target)
        return SavedFile(uri, mime, target.name)
    }
}
