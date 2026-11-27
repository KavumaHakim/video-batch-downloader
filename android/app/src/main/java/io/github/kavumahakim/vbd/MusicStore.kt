package io.github.kavumahakim.vbd

import android.content.Context
import android.util.AtomicFile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors

/** A song to stream: what the player, Home, likes and playlists all hold. */
data class Song(
    val pageUrl: String,
    val title: String,
    val artist: String = "",
    val artwork: String = "",
    val durationSec: Double? = null,
) {
    /** The YouTube video ID when the link has one: what radio and likes key on. */
    val videoId: String? get() = VIDEO_ID.find(pageUrl)?.groupValues?.get(1)
    val key: String get() = videoId ?: pageUrl

    fun toPlayItem() = PlayItem.stream(pageUrl, title, artist, artwork)

    fun toJson(): JSONObject = JSONObject().apply {
        put("page", pageUrl); put("title", title); put("artist", artist); put("artwork", artwork)
        put("duration", durationSec ?: JSONObject.NULL)
    }

    companion object {
        private val VIDEO_ID = Regex("(?:[?&]v=|youtu\\.be/|/shorts/)([\\w-]{11})")

        fun fromJson(o: JSONObject) = Song(o.str("page"), o.str("title"), o.str("artist"), o.str("artwork"), o.numOrNull("duration"))

        fun music(videoId: String, title: String, artist: String, artwork: String, durationSec: Double?) =
            Song("https://music.youtube.com/watch?v=$videoId", title, artist, artwork, durationSec)
    }
}

data class Playlist(val id: String, val name: String, val songs: List<Song>, val created: Long)

data class Play(val song: Song, val at: Long)

data class SavedQueue(val songs: List<Song>, val index: Int, val positionMs: Long)

/**
 * Likes, playlists, listening history and the last queue, kept in one small
 * JSON file on the phone. Nothing here leaves the device.
 */
object MusicStore {
    const val LIKED_ID = "liked"
    private const val HISTORY_MAX = 500

    private lateinit var file: AtomicFile
    private val writer = Executors.newSingleThreadExecutor()

    private val _liked = MutableStateFlow<List<Song>>(emptyList())
    private val _playlists = MutableStateFlow<List<Playlist>>(emptyList())
    private val _history = MutableStateFlow<List<Play>>(emptyList())
    private val _queue = MutableStateFlow<SavedQueue?>(null)

    val liked: StateFlow<List<Song>> = _liked.asStateFlow()
    val playlists: StateFlow<List<Playlist>> = _playlists.asStateFlow()
    val history: StateFlow<List<Play>> = _history.asStateFlow()
    val savedQueue: StateFlow<SavedQueue?> = _queue.asStateFlow()

    fun init(context: Context) {
        file = AtomicFile(File(context.filesDir, "music.json"))
        val root = runCatching { JSONObject(String(file.readFully())) }.getOrNull() ?: return
        _liked.value = root.optJSONArray("liked")?.objects()?.map(Song::fromJson).orEmpty()
        _playlists.value = root.optJSONArray("playlists")?.objects()?.map { p ->
            Playlist(p.str("id"), p.str("name"), p.optJSONArray("songs")?.objects()?.map(Song::fromJson).orEmpty(),
                p.optLong("created"))
        }.orEmpty()
        _history.value = root.optJSONArray("history")?.objects()?.mapNotNull { h ->
            h.optJSONObject("song")?.let { Play(Song.fromJson(it), h.optLong("at")) }
        }.orEmpty()
        _queue.value = root.optJSONObject("queue")?.let { q ->
            SavedQueue(q.optJSONArray("songs")?.objects()?.map(Song::fromJson).orEmpty(), q.optInt("index"), q.optLong("position"))
        }?.takeIf { it.songs.isNotEmpty() }
    }

    private fun save() {
        val liked = _liked.value
        val playlists = _playlists.value
        val history = _history.value
        val queue = _queue.value
        writer.execute {
            val root = JSONObject().apply {
                put("liked", JSONArray(liked.map { it.toJson() }))
                put("playlists", JSONArray(playlists.map { p ->
                    JSONObject().apply {
                        put("id", p.id); put("name", p.name); put("created", p.created)
                        put("songs", JSONArray(p.songs.map { it.toJson() }))
                    }
                }))
                put("history", JSONArray(history.map { JSONObject().put("song", it.song.toJson()).put("at", it.at) }))
                queue?.let { q ->
                    put("queue", JSONObject().put("songs", JSONArray(q.songs.map { it.toJson() }))
                        .put("index", q.index).put("position", q.positionMs))
                }
            }
            val out = file.startWrite()
            try {
                out.write(root.toString().toByteArray())
                file.finishWrite(out)
            } catch (e: Exception) {
                file.failWrite(out)
            }
        }
    }

    // ------------------------------------------------------------------ likes

    fun isLiked(song: Song) = _liked.value.any { it.key == song.key }

    /** Returns true when the song is now liked. */
    fun toggleLike(song: Song): Boolean {
        val now = !isLiked(song)
        _liked.update { list -> if (now) listOf(song) + list else list.filterNot { it.key == song.key } }
        save()
        return now
    }

    // -------------------------------------------------------------- playlists

    fun playlist(id: String): Playlist? =
        if (id == LIKED_ID) Playlist(LIKED_ID, "Liked songs", _liked.value, 0) else _playlists.value.firstOrNull { it.id == id }

    fun createPlaylist(name: String, songs: List<Song> = emptyList()): Playlist {
        val p = Playlist(UUID.randomUUID().toString(), name.trim().ifEmpty { "New playlist" }, songs, System.currentTimeMillis())
        _playlists.update { it + p }
        save()
        return p
    }

    /** Adds songs a playlist does not already hold; returns how many were new. */
    fun addToPlaylist(id: String, songs: List<Song>): Int {
        if (id == LIKED_ID) {
            val fresh = songs.filterNot(::isLiked)
            _liked.update { fresh + it }
            save()
            return fresh.size
        }
        var added = 0
        editPlaylist(id) { p ->
            val fresh = songs.filter { s -> p.songs.none { it.key == s.key } }
            added = fresh.size
            p.copy(songs = p.songs + fresh)
        }
        return added
    }

    fun removeFromPlaylist(id: String, index: Int) {
        if (id == LIKED_ID) {
            _liked.update { it.filterIndexed { i, _ -> i != index } }
            save()
        } else {
            editPlaylist(id) { p -> p.copy(songs = p.songs.filterIndexed { i, _ -> i != index }) }
        }
    }

    fun moveInPlaylist(id: String, from: Int, to: Int) {
        fun <T> List<T>.moved(): List<T> {
            if (from !in indices || to !in indices) return this
            return toMutableList().apply { add(to, removeAt(from)) }
        }
        if (id == LIKED_ID) {
            _liked.update { it.moved() }
            save()
        } else {
            editPlaylist(id) { p -> p.copy(songs = p.songs.moved()) }
        }
    }

    fun renamePlaylist(id: String, name: String) = editPlaylist(id) { it.copy(name = name.trim().ifEmpty { it.name }) }

    fun deletePlaylist(id: String) {
        _playlists.update { list -> list.filterNot { it.id == id } }
        save()
    }

    private fun editPlaylist(id: String, change: (Playlist) -> Playlist) {
        _playlists.update { list -> list.map { if (it.id == id) change(it) else it } }
        save()
    }

    // ---------------------------------------------------------------- history

    fun recordPlay(song: Song) {
        val last = _history.value.firstOrNull()
        // The same song again within a minute is one listen (a restart or a seek back).
        if (last != null && last.song.key == song.key && System.currentTimeMillis() - last.at < 60_000) return
        _history.update { (listOf(Play(song, System.currentTimeMillis())) + it).take(HISTORY_MAX) }
        save()
    }

    /** Recently played songs, newest first, each once. */
    fun recent(limit: Int): List<Song> = _history.value.map { it.song }.distinctBy { it.key }.take(limit)

    /** The songs played most over the last [days] days. */
    fun topPlayed(limit: Int, days: Int = 30): List<Song> {
        val since = System.currentTimeMillis() - days * 86_400_000L
        return _history.value.filter { it.at >= since }.groupBy { it.song.key }
            .entries.sortedByDescending { it.value.size }.take(limit).map { it.value.first().song }
    }

    /** One song for each of the artists played most: the seeds for "Mixes for you". */
    fun mixSeeds(limit: Int): List<Song> = _history.value.filter { it.song.artist.isNotBlank() }
        .groupBy { it.song.artist.substringBefore(",").substringBefore(" & ").trim().lowercase() }
        .entries.sortedByDescending { it.value.size }.take(limit)
        .map { e -> e.value.groupBy { it.song.key }.maxBy { it.value.size }.value.first().song }

    /** Keys of songs heard in the last [hours] hours, so radio can skip them. */
    fun recentlyHeardKeys(hours: Int = 3): Set<String> {
        val since = System.currentTimeMillis() - hours * 3_600_000L
        return _history.value.takeWhile { it.at >= since }.map { it.song.key }.toSet()
    }

    fun clearHistory() {
        _history.value = emptyList()
        save()
    }

    // ------------------------------------------------------------------ queue

    fun saveQueue(queue: SavedQueue?) {
        if (_queue.value == queue) return
        _queue.value = queue?.takeIf { it.songs.isNotEmpty() }
        save()
    }
}
