package io.github.kavumahakim.vbd

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * YouTube Music's own web API (InnerTube), for song search and radio.
 *
 * It answers in about a second with artist, album, length and cover, where
 * yt-dlp's search takes several and returns titles only. It is not a public
 * API and can change; stream links still come from yt-dlp, and radio falls
 * back to yt-dlp's Mix playlists when this fails.
 */
object YtMusic {
    private const val BASE = "https://music.youtube.com/youtubei/v1/"
    // Generic browser client string: nothing here identifies the person using the app.
    private const val USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    private const val CLIENT_VERSION = "1.20241127.01.00"
    /** The search filter the web client sends for its "Songs" chip. */
    private const val SONGS_FILTER = "EgWKAQIIAWoMEA4QChADEAQQCRAF"
    private val DURATION = Regex("^\\d+(?::\\d{2}){1,2}$")

    suspend fun searchSongs(query: String): List<Song> = withContext(Dispatchers.IO) {
        val data = post("search", JSONObject().put("query", query).put("params", SONGS_FILTER))
        find(data, "musicResponsiveListItemRenderer").mapNotNull(::songFromListItem)
    }

    /** Up to 50 songs that go with [videoId], the song itself first. */
    suspend fun radio(videoId: String): List<Song> = withContext(Dispatchers.IO) {
        val data = post("next", JSONObject().put("videoId", videoId).put("playlistId", "RDAMVM$videoId")
            .put("isAudioOnly", true))
        find(data, "playlistPanelVideoRenderer").mapNotNull { p ->
            val id = p.str("videoId").ifEmpty { return@mapNotNull null }
            Song.music(
                id,
                title = text(p.optJSONObject("title")),
                artist = text(p.optJSONObject("shortBylineText")),
                artwork = bigThumbnail(p.optJSONObject("thumbnail")?.optJSONArray("thumbnails")),
                durationSec = parseDuration(text(p.optJSONObject("lengthText"))),
            )
        }
    }

    // ---------------------------------------------------------------- parsing

    private fun songFromListItem(item: JSONObject): Song? {
        val id = item.optJSONObject("playlistItemData")?.str("videoId")?.ifEmpty { null } ?: return null
        val columns = item.optJSONArray("flexColumns")?.objects().orEmpty()
            .map { it.optJSONObject("musicResponsiveListItemFlexColumnRenderer")?.optJSONObject("text") }
        val title = text(columns.getOrNull(0)).ifEmpty { return null }
        // "Artist • Album • 3:05": the artist is everything before the first dot.
        val parts = text(columns.getOrNull(1)).split(" • ").map { it.trim() }
        val duration = parts.lastOrNull { DURATION.matches(it) }
        val thumbs = item.optJSONObject("thumbnail")?.optJSONObject("musicThumbnailRenderer")
            ?.optJSONObject("thumbnail")?.optJSONArray("thumbnails")
        return Song.music(id, title, parts.firstOrNull().orEmpty(), bigThumbnail(thumbs), parseDuration(duration))
    }

    private fun text(o: JSONObject?): String =
        o?.optJSONArray("runs")?.objects()?.joinToString("") { it.str("text") } ?: o?.str("simpleText").orEmpty()

    /** Covers come at 60 px; the URL's size suffix can ask for a sharper one. */
    private fun bigThumbnail(thumbs: JSONArray?): String {
        val url = thumbs?.objects()?.lastOrNull()?.str("url").orEmpty()
        return url.replace(Regex("=w\\d+-h\\d+"), "=w544-h544")
    }

    private fun parseDuration(text: String?): Double? {
        if (text.isNullOrEmpty() || !DURATION.matches(text)) return null
        return text.split(":").fold(0.0) { acc, part -> acc * 60 + part.toDouble() }
    }

    /** Every object stored under [key], anywhere in the response. */
    private fun find(root: Any?, key: String): List<JSONObject> {
        val out = mutableListOf<JSONObject>()
        fun walk(o: Any?) {
            when (o) {
                is JSONObject -> o.keys().forEach { k ->
                    val v = o.opt(k)
                    if (k == key && v is JSONObject) out += v else walk(v)
                }
                is JSONArray -> for (i in 0 until o.length()) walk(o.opt(i))
            }
        }
        walk(root)
        return out
    }

    private fun post(endpoint: String, body: JSONObject): JSONObject {
        body.put("context", JSONObject().put("client", JSONObject()
            .put("clientName", "WEB_REMIX").put("clientVersion", CLIENT_VERSION).put("hl", "en").put("gl", "US")))
        val conn = URL("$BASE$endpoint?prettyPrint=false").openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.connectTimeout = 15_000
            conn.readTimeout = 20_000
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("User-Agent", USER_AGENT)
            conn.setRequestProperty("Origin", "https://music.youtube.com")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            if (conn.responseCode !in 200..299) throw IOException("YouTube Music answered HTTP ${conn.responseCode}")
            return JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
        } finally {
            conn.disconnect()
        }
    }
}
