package io.github.kavumahakim.vbd

import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException

/** What a playlist, channel or album link holds, read without downloading anything. */
object Playlists {
    class Listing(val isPlaylist: Boolean, val title: String, val entries: List<JSONObject>, val root: JSONObject)

    /** Blocking. [limit] caps how many videos are taken; 0 takes them all. */
    fun read(url: String, limit: Int): Listing {
        val root = flatInfo(url, limit)
        val top = root.optJSONArray("entries")?.objects()
        if (root.str("_type") != "playlist" || top == null) return Listing(false, root.str("title"), emptyList(), root)
        val found = mutableListOf<JSONObject>()
        fun collect(items: List<JSONObject>, depth: Int) {
            for (entry in items) {
                if (limit > 0 && found.size >= limit) return
                val nested = entry.optJSONArray("entries")
                when {
                    nested != null -> collect(nested.objects(), depth + 1)
                    // A channel link lists its tabs (Videos, Shorts, Live) as links of their own.
                    entry.str("ie_key") == "YoutubeTab" && depth == 0 -> {
                        val tab = flatInfo(entryUrl(entry), if (limit > 0) limit - found.size else 0)
                        collect(tab.optJSONArray("entries")?.objects().orEmpty(), depth + 1)
                    }
                    entryUrl(entry).isNotEmpty() -> found += entry
                }
            }
        }
        collect(top, 0)
        return Listing(true, root.str("title").ifEmpty { root.str("id") }, found, root)
    }

    private fun flatInfo(url: String, limit: Int): JSONObject {
        val request = YoutubeDLRequest(url).addOption("--flat-playlist").addOption("-J")
        if (limit > 0) request.addOption("--playlist-end", limit)
        val out = YoutubeDL.getInstance().execute(request).out
        return JSONObject(out.trim().lines().last { it.startsWith("{") })
    }
}

/** Turns pasted or shared links into songs to stream. */
object Tracks {
    /**
     * Spotify links become their tracks (matched on YouTube or SoundCloud),
     * playlists and channels their videos, and any other link one song whose
     * title is filled in once it has been looked up.
     */
    suspend fun fromLinks(text: String, settings: Settings): List<PlayItem> = withContext(Dispatchers.IO) {
        Engine.await()
        val out = mutableListOf<PlayItem>()
        var firstError: String? = null
        for (link in Ytdlp.extractLinks(text)) {
            try {
                out += when {
                    Spotify.looksLike(link) -> Spotify.tracks(link, settings.playlistLimit).second.map {
                        // Streams always come from YouTube: SoundCloud only offers HLS now.
                        PlayItem.stream(it.searchUrl("ytsearch"), it.title, it.artist, it.artwork)
                    }
                    Ytdlp.looksLikePlaylist(link) -> {
                        val listing = Playlists.read(link, settings.playlistLimit)
                        if (!listing.isPlaylist) {
                            listOf(PlayItem.stream(link, listing.title, artwork = bestThumbnail(listing.root)))
                        } else {
                            listing.entries.map {
                                PlayItem.stream(entryUrl(it), it.str("title"), listing.title, bestThumbnail(it))
                            }
                        }
                    }
                    else -> listOf(PlayItem.stream(link, Streams.known(link)?.title.orEmpty()))
                }
            } catch (e: YoutubeDLException) {
                firstError = firstError ?: Ytdlp.cleanError(e.message.orEmpty())
            } catch (e: Spotify.SpotifyException) {
                firstError = firstError ?: e.message
            }
        }
        // One bad link in a batch should not stop the rest from playing.
        if (out.isEmpty() && firstError != null) throw IOException(firstError)
        out
    }

    /**
     * Songs that go with [song] for radio: YouTube Music's own radio when it
     * answers, else yt-dlp's reading of YouTube's Mix playlist. [skip] holds
     * song keys to leave out (already queued, or heard a moment ago).
     */
    suspend fun radioFor(song: Song, skip: Set<String> = emptySet()): List<Song> = withContext(Dispatchers.IO) {
        val id = song.videoId ?: return@withContext emptyList()
        val found = runCatching { YtMusic.radio(id) }.getOrNull()?.takeIf { it.size > 1 } ?: run {
            Engine.await()
            Playlists.read("https://www.youtube.com/watch?v=$id&list=RD$id", 30).entries.map {
                Song(entryUrl(it), it.str("title"), it.str("channel").ifEmpty { it.str("uploader") }, bestThumbnail(it),
                    it.numOrNull("duration"))
            }
        }
        found.filter { it.key != song.key && it.key !in skip }.distinctBy { it.key }
    }

    /** A Spotify or YouTube playlist link as (its name, its songs), for importing as a playlist. */
    suspend fun importLink(link: String, settings: Settings): Pair<String, List<Song>> = withContext(Dispatchers.IO) {
        Engine.await()
        try {
            if (Spotify.looksLike(link)) {
                val (name, tracks) = Spotify.tracks(link)
                name to tracks.map { Song(it.searchUrl("ytsearch"), it.title, it.artist, it.artwork) }
            } else {
                val listing = Playlists.read(link, 0)
                if (!listing.isPlaylist) throw IOException("That link is a single video, not a playlist.")
                listing.title to listing.entries.map {
                    Song(entryUrl(it), it.str("title"), it.str("channel").ifEmpty { it.str("uploader") },
                        bestThumbnail(it), it.numOrNull("duration"))
                }
            }
        } catch (e: YoutubeDLException) {
            throw IOException(Ytdlp.cleanError(e.message.orEmpty()))
        } catch (e: Spotify.SpotifyException) {
            throw IOException(e.message)
        }
    }

    fun fromSearch(results: List<SearchResult>): List<PlayItem> =
        results.map { PlayItem.stream(it.url, it.title, it.uploader, it.thumbnail) }
}
