package io.github.kavumahakim.vbd

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.abs

/**
 * Reading track lists off Spotify links, without an account or API key.
 *
 * Spotify's audio is DRM-protected and yt-dlp cannot download it. What the
 * public embed page does give us is the track titles and artists; those become
 * search queries so the matching track is fetched from YouTube or SoundCloud.
 * Port of the desktop app's spotify.py.
 */
object Spotify {
    private val LINK = Regex(
        "^https?://(?:open|play)\\.spotify\\.com/(?:intl-[a-z]{2,5}(?:-[a-z]+)?/)?" +
            "(track|album|playlist|artist|show|episode)/([A-Za-z0-9]+)",
        RegexOption.IGNORE_CASE,
    )
    private val NEXT_DATA = Regex("<script id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", RegexOption.DOT_MATCHES_ALL)
    // Generic client string: nothing here identifies the person running the app.
    private const val USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"

    class SpotifyException(message: String) : Exception(message)

    data class Track(val title: String, val artist: String, val artwork: String) {
        val label: String get() = if (artist.isNotEmpty()) "$artist — $title" else title
        fun searchUrl(prefix: String): String =
            "${prefix}1:" + "$artist $title".replace(Regex("\\s+"), " ").trim()
    }

    fun looksLike(url: String) = LINK.containsMatchIn(url.trim())

    /** (collection name, tracks) for a Spotify link. Blocking: call off the main thread. */
    fun tracks(url: String, limit: Int = 0): Pair<String, List<Track>> {
        val match = LINK.find(url.trim()) ?: return "" to emptyList()
        val kind = match.groupValues[1].lowercase()
        val id = match.groupValues[2]
        val html = try {
            fetch("https://open.spotify.com/embed/$kind/$id")
        } catch (e: IOException) {
            throw SpotifyException("Could not reach Spotify: ${e.message}")
        }
        val json = NEXT_DATA.find(html)?.groupValues?.get(1)
            ?: throw SpotifyException("Spotify did not return the data this page usually carries.")
        val entity = try {
            entity(JSONObject(json))
        } catch (e: Exception) {
            throw SpotifyException("Could not read the Spotify page: ${e.message}")
        } ?: throw SpotifyException("That Spotify link holds nothing this app can read.")

        val name = entity.str("name").ifEmpty { entity.str("title") }.ifEmpty { kind.replaceFirstChar { it.uppercase() } }
        // The embed gives one cover per release; album and playlist tracks share it.
        val cover = artwork(entity)
        val entries = entity.optJSONArray("trackList")?.objects().orEmpty()
        if (entries.isEmpty()) {
            val title = entity.str("name").ifEmpty { entity.str("title") }
            if (title.isEmpty()) throw SpotifyException("That Spotify link holds nothing this app can read.")
            return name to listOf(Track(title, artists(entity), cover))
        }
        val tracks = mutableListOf<Track>()
        for (entry in entries) {
            val title = entry.str("title").ifEmpty { entry.str("name") }.trim()
            if (title.isEmpty()) continue
            tracks += Track(title, artists(entry).trim(), cover)
            if (limit > 0 && tracks.size >= limit) break
        }
        if (tracks.isEmpty()) throw SpotifyException("Spotify listed no tracks for that link.")
        return name to tracks
    }

    private fun fetch(url: String): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 25_000
        conn.readTimeout = 25_000
        conn.setRequestProperty("User-Agent", USER_AGENT)
        conn.setRequestProperty("Accept-Language", "en")
        try {
            if (conn.responseCode !in 200..299) throw IOException("HTTP ${conn.responseCode}")
            return conn.inputStream.bufferedReader().use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    private fun entity(payload: JSONObject): JSONObject? {
        val pageProps = payload.optJSONObject("props")?.optJSONObject("pageProps") ?: return null
        val data = pageProps.optJSONObject("state")?.optJSONObject("data")
            ?: pageProps.optJSONObject("data") ?: return null
        return data.optJSONObject("entity") ?: data
    }

    private fun artwork(entity: JSONObject): String {
        val art = entity.optJSONObject("visualIdentity") ?: entity.optJSONObject("coverArt") ?: return ""
        val images = (art.optJSONArray("image") ?: art.optJSONArray("sources"))?.objects()
            ?.filter { it.str("url").isNotEmpty() }.orEmpty()
        if (images.isEmpty()) return ""
        fun width(o: JSONObject) = o.optInt("width", 0).takeIf { it > 0 } ?: o.optInt("maxWidth", 0)
        val sized = images.filter { width(it) > 0 }.sortedBy { abs(width(it) - 160) }
        return (sized.firstOrNull() ?: images.last()).str("url")
    }

    private fun artists(entry: JSONObject): String {
        val names = entry.optJSONArray("artists")?.objects()?.map { it.str("name") }?.filter { it.isNotEmpty() }.orEmpty()
        // Album and playlist track lists carry the artist as a plain subtitle.
        return if (names.isNotEmpty()) names.joinToString(", ") else entry.str("subtitle")
    }
}
