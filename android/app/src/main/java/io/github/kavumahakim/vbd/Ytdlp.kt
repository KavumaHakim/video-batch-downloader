package io.github.kavumahakim.vbd

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs

/**
 * yt-dlp knowledge shared with the desktop app's downloader.py: format
 * selection, error matching and the small parsing helpers.
 */
object Ytdlp {
    // Video is always H.264 + AAC in MP4: it plays on every phone and PC in
    // hardware, so nothing ever needs converting. YouTube offers H.264 up to
    // 1080p, which is why the list stops there.
    val QUALITIES = listOf("Best available", "1080p", "720p", "480p", "360p")
    private const val H264 = "[vcodec~='^(avc|h264)']"

    val AUDIO_FORMATS = listOf("mp3", "m4a", "opus", "flac", "wav")
    val LOSSLESS_AUDIO = setOf("flac", "wav")
    val AUDIO_QUALITIES = listOf("128", "192", "256", "320")

    /** yt-dlp search prefixes, used by the Search tab and for Spotify matches. */
    val SEARCH_SITES = listOf(
        "ytmusic" to "YouTube Music",
        "ytsearch" to "YouTube",
        "scsearch" to "SoundCloud",
        "bilisearch" to "Bilibili",
        "nicosearch" to "Niconico",
    )
    val SPOTIFY_SOURCES = listOf("ytsearch" to "YouTube", "scsearch" to "SoundCloud")
    /** Search sites whose results the player can stream. */
    val STREAMABLE_SITES = setOf("ytmusic", "ytsearch")

    val RATE_LIMITED = Regex(
        "HTTP Error 429|Too Many Requests|HTTP Error 403|Forbidden" +
            "|Sign in to confirm|not a bot|temporarily blocked|try again later",
        RegexOption.IGNORE_CASE,
    )
    val SUBTITLE_TROUBLE = Regex("subtitle|caption|\\.srt|\\.vtt", RegexOption.IGNORE_CASE)
    private val ANSI = Regex("\u001B\\[[0-9;]*m")

    // URLs worth probing for a playlist. A false positive only costs one
    // extraction that comes back as a single video.
    private val PLAYLIST_HINTS = Regex(
        "[?&](?:list|playlist|album|set)=|/playlists?(?:/|$|\\?)|/sets/|/albums?/" +
            "|/channels?/|/users?/|/c/|/@|/videos(?:/|$|\\?)|/streams(?:/|$|\\?)" +
            "|/shows?/|/series/|/collections?/|/podcasts?/",
        RegexOption.IGNORE_CASE,
    )
    private val LINK = Regex("https?://[^\\s<>\"']+", RegexOption.IGNORE_CASE)

    /**
     * The yt-dlp -f value for a quality cap: H.264 video with AAC audio first,
     * then H.264 with any audio. Only a site that has no H.264 at all falls
     * through to its best stream, so the download still happens.
     */
    fun formatFor(quality: String): String {
        val cap = if (quality == "Best available") "" else "[height<=${quality.removeSuffix("p")}]"
        return "bv*$cap$H264+ba[ext=m4a]/bv*$cap$H264+ba/b$cap$H264/bv*$cap+ba/b$cap/b"
    }

    fun looksLikePlaylist(url: String) = PLAYLIST_HINTS.containsMatchIn(url)

    /** Every http(s) link in pasted or shared text, in order, without duplicates. */
    fun extractLinks(text: String): List<String> =
        LINK.findAll(text).map { it.value.trimEnd('.', ',', ')', ']', ';', '!') }.distinct().toList()

    /** The last ERROR: line of yt-dlp's output, without colour codes or the prefix. */
    fun cleanError(raw: String): String {
        val lines = ANSI.replace(raw, "").lines().map { it.trim() }.filter { it.isNotEmpty() }
        val line = lines.lastOrNull { it.startsWith("ERROR:") } ?: lines.lastOrNull() ?: "Unknown error"
        return line.removePrefix("ERROR:").trim()
    }

    /** A playlist title trimmed to something every file system accepts as a folder. */
    fun safeFolderName(name: String): String {
        val cleaned = name.replace(Regex("[<>:\"/\\\\|?*]"), " ")
            .replace(Regex("[\\x00-\\x1f]"), "")
            .replace(Regex("\\s+"), " ")
            .trim(' ', '.')
        return cleaned.take(120).ifEmpty { "Playlist" }
    }

    fun formatDuration(seconds: Double?): String {
        if (seconds == null) return ""
        val total = seconds.toLong()
        val h = total / 3600
        val m = (total % 3600) / 60
        val s = total % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
    }

    fun formatViews(count: Long?): String = when {
        count == null -> ""
        count >= 1_000_000_000 -> "%.1fB views".format(count / 1e9)
        count >= 1_000_000 -> "%.1fM views".format(count / 1e6)
        count >= 1_000 -> "%.1fK views".format(count / 1e3)
        else -> "$count views"
    }
}

// ------------------------------------------------------------------ JSON helpers

/** A string field, or "" when it is missing or null (org.json would say "null"). */
fun JSONObject.str(key: String): String =
    if (has(key) && !isNull(key)) optString(key, "") else ""

fun JSONObject.numOrNull(key: String): Double? =
    if (has(key) && !isNull(key)) optDouble(key).takeIf { !it.isNaN() } else null

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }

/** The entry's own page, preferring a full web URL over an extractor-internal one. */
fun entryUrl(entry: JSONObject): String =
    listOf("webpage_url", "original_url", "url").map { entry.str(it) }.firstOrNull { it.startsWith("http") } ?: ""

/** Artwork near card size rather than the full-resolution original. */
fun bestThumbnail(entry: JSONObject): String {
    entry.str("thumbnail").let { if (it.isNotEmpty()) return it }
    val thumbs = entry.optJSONArray("thumbnails")?.objects()?.filter { it.str("url").isNotEmpty() }.orEmpty()
    if (thumbs.isEmpty()) return ""
    val sized = thumbs.filter { it.optInt("width", 0) > 0 }.sortedBy { abs(it.optInt("width") - 320) }
    return (sized.firstOrNull() ?: thumbs.last()).str("url")
}
