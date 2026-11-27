package io.github.kavumahakim.vbd

import android.content.Context
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors

/**
 * Turns a page link (or a yt-dlp search such as ytsearch1:artist title) into
 * a playable audio URL, on demand.
 *
 * yt-dlp takes several seconds per lookup on a phone, so links are kept
 * until shortly before YouTube expires them (about six hours), two requests
 * for the same song share one lookup, and the next songs in the queue are
 * looked up early while the current one plays.
 */
object Streams {
    const val SCHEME = "vbdstream"
    private const val TAG = "Streams"
    private const val EXPIRY_MARGIN_MS = 30L * 60 * 1000
    private const val FALLBACK_LIFETIME_MS = 2L * 60 * 60 * 1000

    enum class Quality(val label: String, val format: String) {
        // Direct (http) links only: the player reads each song as one file, so an
        // HLS-only source (SoundCloud today) is refused instead of half-playing.
        Normal("Normal · about 130 kbps", "ba[ext=m4a][protocol^=http]/ba[protocol^=http]/b[protocol^=http]"),
        DataSaver("Data saver · about 50 kbps", "wa[ext=m4a][protocol^=http]/ba[abr<=70][protocol^=http]/wa[protocol^=http]/ba[protocol^=http]/b[protocol^=http]"),
    }

    data class Resolved(
        val url: String,
        val headers: Map<String, String>,
        val expiresAt: Long,
        val title: String,
        val artist: String,
        val duration: Double?,
        val thumbnail: String,
        val webpage: String,
    ) {
        fun toJson(): String = JSONObject().apply {
            put("url", url); put("headers", JSONObject(headers)); put("expiresAt", expiresAt)
            put("title", title); put("artist", artist); put("duration", duration ?: JSONObject.NULL)
            put("thumbnail", thumbnail); put("webpage", webpage)
        }.toString()

        companion object {
            fun fromJson(text: String): Resolved {
                val o = JSONObject(text)
                val h = o.optJSONObject("headers")
                val headers = h?.keys()?.asSequence()?.associateWith { h.optString(it) }.orEmpty()
                return Resolved(o.str("url"), headers, o.optLong("expiresAt"), o.str("title"), o.str("artist"),
                    o.numOrNull("duration"), o.str("thumbnail"), o.str("webpage"))
            }
        }
    }

    private lateinit var app: Context
    private lateinit var prefs: SharedPreferences
    private val links = ConcurrentHashMap<String, Resolved>()
    private val inflight = ConcurrentHashMap<String, CompletableFuture<Resolved>>()
    // One quality per song for the life of the app: cached bytes of one
    // quality must never be continued with bytes of another.
    private val pinned = ConcurrentHashMap<String, Quality>()
    // The playing song plus the next two can all be looked up at once.
    private val pool = Executors.newFixedThreadPool(3)
    private val _lastLookupMs = MutableStateFlow(-1L)

    /** How long the most recent yt-dlp lookup took, for Settings. -1 before the first. */
    val lastLookupMs: StateFlow<Long> = _lastLookupMs.asStateFlow()

    /** Called on a worker thread whenever a lookup brings back a song's details. */
    @Volatile var onResolved: ((pageUrl: String, Resolved) -> Unit)? = null

    fun init(context: Context) {
        app = context.applicationContext
        prefs = app.getSharedPreferences("stream_links", Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val stale = mutableListOf<String>()
        for ((key, value) in prefs.all) {
            val r = runCatching { Resolved.fromJson(value as String) }.getOrNull()
            if (r == null || r.expiresAt <= now) stale += key else links[key] = r
        }
        if (stale.isNotEmpty()) prefs.edit().apply { stale.forEach(::remove) }.apply()
    }

    // ------------------------------------------------------------- stream URIs

    fun uriFor(pageUrl: String): Uri =
        Uri.Builder().scheme(SCHEME).authority("track").appendQueryParameter("u", pageUrl).build()

    fun pageUrlOf(uri: Uri?): String? =
        if (uri?.scheme == SCHEME) uri.getQueryParameter("u") else null

    fun pageUrlOf(mediaId: String): String? = pageUrlOf(Uri.parse(mediaId))

    // ----------------------------------------------------------------- quality

    private fun metered(): Boolean =
        app.getSystemService(ConnectivityManager::class.java)?.isActiveNetworkMetered ?: false

    fun qualityFor(pageUrl: String): Quality = pinned.getOrPut(pageUrl) {
        val s = SettingsStore.current
        val name = if (metered()) s.streamQualityMobile else s.streamQualityWifi
        Quality.entries.firstOrNull { it.name == name } ?: Quality.Normal
    }

    /** The media cache's key: the song and its pinned quality, not the expiring URL. */
    fun cacheKey(uri: Uri): String {
        val page = pageUrlOf(uri) ?: return uri.toString()
        return "${qualityFor(page).name}|$page"
    }

    // ---------------------------------------------------------------- lookups

    /** Blocking: call from a worker thread (Media3 calls it on its loader thread). */
    fun resolve(pageUrl: String): Resolved {
        val key = "${qualityFor(pageUrl).name}|$pageUrl"
        links[key]?.takeIf { it.expiresAt > System.currentTimeMillis() }?.let { return it }
        val future = start(pageUrl, key)
        return try {
            future.get()
        } catch (e: ExecutionException) {
            throw (e.cause as? IOException) ?: IOException(e.cause?.message ?: "Could not find a stream", e.cause)
        } catch (e: InterruptedException) {
            throw IOException("Stream lookup was interrupted", e)
        } finally {
            // Only this attempt's entry: a newer one for the same song stays.
            inflight.remove(key, future)
        }
    }

    /**
     * Look a song up in the background so it starts at once when its turn
     * comes. It only queues the lookup and never waits on the pool itself:
     * a prefetch blocking a pool thread on another pool task could deadlock it.
     */
    fun prefetch(pageUrl: String) {
        val key = "${qualityFor(pageUrl).name}|$pageUrl"
        if (links[key]?.let { it.expiresAt > System.currentTimeMillis() } == true) return
        val future = start(pageUrl, key)
        future.whenComplete { _, _ -> inflight.remove(key, future) }
    }

    /** The one lookup in flight for [key], started if there is none. */
    private fun start(pageUrl: String, key: String): CompletableFuture<Resolved> =
        inflight.computeIfAbsent(key) { CompletableFuture.supplyAsync({ lookup(pageUrl, key) }, pool) }

    /** Forget a link that stopped working (HTTP 403 once YouTube expires it early). */
    fun invalidate(pageUrl: String) {
        val key = "${qualityFor(pageUrl).name}|$pageUrl"
        links.remove(key)
        prefs.edit().remove(key).apply()
    }

    /** What a lookup found, if it is still fresh: titles and artwork for the UI. */
    fun known(pageUrl: String): Resolved? =
        Quality.entries.firstNotNullOfOrNull { q -> links["${q.name}|$pageUrl"] }

    private fun lookup(pageUrl: String, key: String): Resolved {
        runBlocking { Engine.await() }
        val quality = qualityFor(pageUrl)
        val request = YoutubeDLRequest(pageUrl)
            .addOption("-f", quality.format)
            .addOption("-j")
            .addOption("--no-playlist")
            .addOption("--no-warnings")
        val started = SystemClock.elapsedRealtime()
        val out = try {
            YoutubeDL.getInstance().execute(request).out
        } catch (e: YoutubeDLException) {
            throw IOException(Ytdlp.cleanError(e.message.orEmpty()))
        } catch (e: YoutubeDL.CanceledException) {
            throw IOException("Stream lookup was cancelled")
        }
        val took = SystemClock.elapsedRealtime() - started
        _lastLookupMs.value = took
        Log.i(TAG, "Looked up $pageUrl in $took ms")

        val line = out.lines().lastOrNull { it.startsWith("{") } ?: throw IOException("yt-dlp found no stream")
        val info = JSONObject(line)
        // A merged format carries its parts in requested_formats; take the audio one.
        val format = info.optJSONArray("requested_formats")?.objects()
            ?.firstOrNull { it.str("vcodec") == "none" } ?: info
        val url = format.str("url").ifEmpty { info.str("url") }
        if (url.isEmpty()) throw IOException("yt-dlp found no playable stream")
        val headersJson = format.optJSONObject("http_headers") ?: info.optJSONObject("http_headers")
        val headers = headersJson?.keys()?.asSequence()?.associateWith { headersJson.optString(it) }.orEmpty()
        val expire = Regex("[?&]expire=(\\d+)").find(url)?.groupValues?.get(1)?.toLongOrNull()?.times(1000)
        val expiresAt = (expire ?: (System.currentTimeMillis() + FALLBACK_LIFETIME_MS)) - EXPIRY_MARGIN_MS

        val resolved = Resolved(
            url = url,
            headers = headers,
            expiresAt = expiresAt,
            title = info.str("track").ifEmpty { info.str("title") },
            artist = info.str("artist").ifEmpty { info.str("uploader") }.ifEmpty { info.str("channel") }
                .removeSuffix(" - Topic"),
            duration = info.numOrNull("duration"),
            thumbnail = bestThumbnail(info),
            webpage = info.str("webpage_url"),
        )
        links[key] = resolved
        prefs.edit().putString(key, resolved.toJson()).apply()
        onResolved?.invoke(pageUrl, resolved)
        return resolved
    }
}
