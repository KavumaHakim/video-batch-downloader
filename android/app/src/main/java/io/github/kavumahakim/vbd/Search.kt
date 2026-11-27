package io.github.kavumahakim.vbd

import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class SearchResult(
    val title: String,
    val url: String,
    val uploader: String,
    val duration: Double?,
    val views: Long?,
    val thumbnail: String,
)

/** Video search through yt-dlp's built-in search extractors (ytsearch, scsearch...). */
object Search {
    const val MAX_RESULTS = 30

    suspend fun search(query: String, prefix: String, limit: Int = MAX_RESULTS): List<SearchResult> =
        withContext(Dispatchers.IO) {
            val q = query.trim()
            if (q.isEmpty()) return@withContext emptyList()
            var site = prefix
            if (prefix == "ytmusic") {
                // YouTube Music's own search: songs with artist, length and cover. It is
                // not a public API, so when it fails, plain YouTube search answers instead.
                val songs = runCatching { YtMusic.searchSongs(q) }.getOrNull()
                if (songs != null) {
                    return@withContext songs.take(limit).map {
                        SearchResult(it.title, it.pageUrl, it.artist, it.durationSec, null, it.artwork)
                    }
                }
                site = "ytsearch"
            }
            Engine.await()
            val request = YoutubeDLRequest("$site${limit.coerceIn(1, MAX_RESULTS)}:$q")
                .addOption("--flat-playlist")
                .addOption("--ignore-errors")
                .addOption("-J")
            val out = try {
                YoutubeDL.getInstance().execute(request).out
            } catch (e: YoutubeDLException) {
                throw Exception(Ytdlp.cleanError(e.message.orEmpty()))
            }
            val root = JSONObject(out.trim().lines().last { it.startsWith("{") })
            root.optJSONArray("entries")?.objects().orEmpty().mapNotNull { entry ->
                val url = entryUrl(entry).ifEmpty { return@mapNotNull null }
                SearchResult(
                    title = entry.str("title").ifEmpty { url },
                    url = url,
                    uploader = entry.str("uploader").ifEmpty { entry.str("channel") },
                    duration = entry.numOrNull("duration"),
                    views = entry.numOrNull("view_count")?.toLong(),
                    thumbnail = bestThumbnail(entry),
                )
            }
        }
}
