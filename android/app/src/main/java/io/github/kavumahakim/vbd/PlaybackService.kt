package io.github.kavumahakim.vbd

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.TransferListener
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaController
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import androidx.media3.session.CommandButton
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

/**
 * One thing for the player: a file on the phone, or a song to stream when
 * [pageUrl] is set (then [uri] is a vbdstream: link the player resolves itself).
 */
data class PlayItem(
    val uri: Uri,
    val title: String,
    val subtitle: String = "",
    val artwork: String = "",
    val mime: String = "",
    val pageUrl: String = "",
) {
    val audio: Boolean get() = mime.startsWith("audio/") || pageUrl.isNotEmpty()

    companion object {
        /** A song to stream; an empty title is filled in once yt-dlp has looked it up. */
        fun stream(pageUrl: String, title: String = "", artist: String = "", artwork: String = "") =
            PlayItem(Streams.uriFor(pageUrl), title, artist, artwork, "audio/*", pageUrl)
    }
}

/** The song a queue entry streams, or null for a file on the phone. */
fun MediaItem.toSong(): Song? {
    val m = mediaMetadata
    val page = m.extras?.getString(EXTRA_PAGE)?.ifEmpty { null } ?: Streams.pageUrlOf(mediaId) ?: return null
    return Song(page, m.title?.toString().orEmpty(), m.artist?.toString().orEmpty(), m.artworkUri?.toString().orEmpty(),
        m.durationMs?.takeIf { it > 0 }?.div(1000.0))
}

fun PlayItem.toMediaItem(): MediaItem {
    val metadata = MediaMetadata.Builder()
        .setTitle(title)
        .setArtist(subtitle.ifEmpty { null })
        .setArtworkUri(artwork.takeIf { it.startsWith("http") }?.let(Uri::parse))
        .setMediaType(if (audio) MediaMetadata.MEDIA_TYPE_MUSIC else MediaMetadata.MEDIA_TYPE_VIDEO)
        .setExtras(Bundle().apply {
            putString(EXTRA_MIME, mime)
            putString(EXTRA_PAGE, pageUrl)
        })
        .build()
    return MediaItem.Builder().setMediaId(uri.toString()).setUri(uri).setMediaMetadata(metadata).build()
}

const val EXTRA_MIME = "mime"
const val CMD_LIKE = "vbd.like"
const val EXTRA_PAGE = "page"
const val EXTRA_OPEN_PLAYER = "open_player"

/** The media cache: what has been streamed, kept so replays need no data. */
@UnstableApi
object MediaCache {
    private const val SIZE = 500L * 1024 * 1024
    @Volatile private var cache: SimpleCache? = null

    fun get(context: Context): SimpleCache = cache ?: synchronized(this) {
        cache ?: SimpleCache(
            File(context.applicationContext.cacheDir, "media"),
            LeastRecentlyUsedCacheEvictor(SIZE),
            StandaloneDatabaseProvider(context.applicationContext),
        ).also { cache = it }
    }

    fun sizeBytes(context: Context): Long = get(context).cacheSpace

    fun clear(context: Context) {
        val c = get(context)
        c.keys.toList().forEach { runCatching { c.removeResource(it) } }
    }
}

/**
 * Sends streams through the cache and the yt-dlp resolver, and files on the
 * phone straight to the platform, so local playback is never cached twice.
 */
@UnstableApi
private class RoutingDataSource(private val stream: DataSource, private val local: DataSource) : DataSource {
    private var current: DataSource? = null

    override fun addTransferListener(transferListener: TransferListener) {
        stream.addTransferListener(transferListener)
        local.addTransferListener(transferListener)
    }

    override fun open(dataSpec: DataSpec): Long {
        val target = if (dataSpec.uri.scheme == Streams.SCHEME) stream else local
        current = target
        return target.open(dataSpec)
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        current?.read(buffer, offset, length) ?: C.RESULT_END_OF_INPUT

    override fun getUri(): Uri? = current?.uri

    override fun getResponseHeaders(): Map<String, List<String>> = current?.responseHeaders ?: emptyMap()

    override fun close() {
        try {
            current?.close()
        } finally {
            current = null
        }
    }
}

/**
 * Owns the ExoPlayer, so playback carries on with the app closed, with
 * controls in the notification and on the lock screen.
 */
@UnstableApi
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null
    private val main = Handler(Looper.getMainLooper())
    /** Songs already given a fresh link after a 403, so one bad song cannot loop. */
    private val relinked = mutableSetOf<String>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    /** The song whose radio was last fetched, so autoplay asks once per song. */
    private var radioSeed: String? = null
    /** The song last written to history, so pausing and resuming is not a second listen. */
    private var recordedKey: String? = null

    override fun onCreate() {
        super.onCreate()
        val http = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(20_000)
        val resolving = ResolvingDataSource.Factory(http) { spec ->
            val page = Streams.pageUrlOf(spec.uri) ?: return@Factory spec
            val r = Streams.resolve(page)
            spec.buildUpon().setUri(r.url).setHttpRequestHeaders(r.headers).build()
        }
        val streams = CacheDataSource.Factory()
            .setCache(MediaCache.get(this))
            .setCacheKeyFactory { spec -> Streams.cacheKey(spec.uri) }
            .setUpstreamDataSourceFactory(resolving)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        val local = DefaultDataSource.Factory(this)
        val routing = DataSource.Factory { RoutingDataSource(streams.createDataSource(), local.createDataSource()) }

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(routing))
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),
                /* handleAudioFocus = */ true,
            )
            .setHandleAudioBecomingNoisy(true) // pause when headphones come out
            .build()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                prefetchAhead(player)
                // A new song counts once it actually plays: restoring a queue
                // or queueing music paused is not listening to it.
                recordedKey = null
                if (player.isPlaying) recordIfNew(player)
                refreshLikeButton(player)
                saveQueue(player)
                autoplay(player)
            }
            override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) {
                prefetchAhead(player)
                autoplay(player)
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying) recordIfNew(player) else saveQueue(player)
            }
            override fun onPlayerError(error: PlaybackException) = recover(player, error)
        })
        Streams.onResolved = { page, r -> main.post { fillIn(player, page, r) } }

        val openPlayer = PendingIntent.getActivity(
            this, 1,
            Intent(this, MainActivity::class.java).putExtra(EXTRA_OPEN_PLAYER, true)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        session = MediaSession.Builder(this, player)
            .setSessionActivity(openPlayer)
            .setCallback(object : MediaSession.Callback {
                override fun onConnect(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo,
                ): MediaSession.ConnectionResult = MediaSession.ConnectionResult.AcceptedResultBuilder(session)
                    .setAvailableSessionCommands(
                        MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS.buildUpon()
                            .add(SessionCommand(CMD_LIKE, Bundle.EMPTY)).build()
                    )
                    .build()

                override fun onCustomCommand(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo,
                    customCommand: SessionCommand,
                    args: Bundle,
                ): ListenableFuture<SessionResult> {
                    if (customCommand.customAction == CMD_LIKE) {
                        session.player.currentMediaItem?.toSong()?.let(MusicStore::toggleLike)
                    }
                    return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
                }

                // Controllers send items without their playable URI; it travels as the media ID.
                override fun onAddMediaItems(
                    mediaSession: MediaSession,
                    controller: MediaSession.ControllerInfo,
                    mediaItems: MutableList<MediaItem>,
                ): ListenableFuture<MutableList<MediaItem>> = Futures.immediateFuture(
                    mediaItems.map { it.buildUpon().setUri(it.mediaId).build() }.toMutableList()
                )
            })
            .build()
        // The heart in the notification follows likes made anywhere in the app.
        scope.launch { MusicStore.liked.collect { refreshLikeButton(player) } }
    }

    private fun recordIfNew(player: Player) {
        val song = player.currentMediaItem?.toSong() ?: return
        if (song.key == recordedKey) return
        recordedKey = song.key
        MusicStore.recordPlay(song)
    }

    private fun refreshLikeButton(player: Player) {
        val song = player.currentMediaItem?.toSong()
        val buttons = if (song == null) emptyList() else listOf(
            CommandButton.Builder(if (MusicStore.isLiked(song)) CommandButton.ICON_HEART_FILLED else CommandButton.ICON_HEART_UNFILLED)
                .setDisplayName(if (MusicStore.isLiked(song)) "Unlike" else "Like")
                .setSessionCommand(SessionCommand(CMD_LIKE, Bundle.EMPTY))
                .setSlots(CommandButton.SLOT_FORWARD_SECONDARY)
                .build()
        )
        session?.setMediaButtonPreferences(buttons)
    }

    /** The streamed part of the queue, so it comes back after a restart. */
    private fun saveQueue(player: Player) {
        val songs = (0 until player.mediaItemCount).mapNotNull { player.getMediaItemAt(it).toSong() }
        if (songs.isEmpty()) return
        val current = player.currentMediaItem?.toSong()
        val index = songs.indexOfFirst { it.key == current?.key }.coerceAtLeast(0)
        MusicStore.saveQueue(SavedQueue(songs, index, if (current != null) player.currentPosition else 0))
    }

    /** On the last song with autoplay on, queue its radio so the music keeps going. */
    private fun autoplay(player: Player) {
        if (!SettingsStore.current.autoplay || player.mediaItemCount == 0) return
        if (player.currentMediaItemIndex != player.mediaItemCount - 1) return
        val song = player.currentMediaItem?.toSong() ?: return
        if (song.videoId == null || radioSeed == song.key) return
        radioSeed = song.key
        scope.launch {
            val queued = (0 until player.mediaItemCount).mapNotNull { player.getMediaItemAt(it).toSong()?.key }.toSet()
            val more = runCatching { Tracks.radioFor(song, queued + MusicStore.recentlyHeardKeys()) }.getOrDefault(emptyList())
            if (more.isNotEmpty() && player.currentMediaItem?.toSong()?.key == song.key) {
                player.addMediaItems(more.take(25).map { it.toPlayItem().toMediaItem() })
            }
        }
    }

    /** Look up the next two streamed songs while this one plays. */
    private fun prefetchAhead(player: Player) {
        if (player.mediaItemCount == 0) return
        relinked.retainAll(setOfNotNull(player.currentMediaItem?.let { Streams.pageUrlOf(it.mediaId) }))
        val start = player.currentMediaItemIndex
        for (i in start..minOf(start + 2, player.mediaItemCount - 1)) {
            Streams.pageUrlOf(player.getMediaItemAt(i).mediaId)?.let(Streams::prefetch)
        }
    }

    /**
     * A stream link YouTube stopped accepting (403/410) is looked up again and
     * playback carries on from the same second; a song that cannot be found
     * at all is skipped, as a music app would.
     */
    private fun recover(player: ExoPlayer, error: PlaybackException) {
        val item = player.currentMediaItem ?: return
        val page = Streams.pageUrlOf(item.mediaId) ?: return
        val http = generateSequence(error as Throwable) { it.cause }
            .filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()
        if (http != null && http.responseCode in setOf(403, 410) && relinked.add(page)) {
            Streams.invalidate(page)
            player.prepare()
            player.play()
            return
        }
        val title = item.mediaMetadata.title?.toString().orEmpty().ifEmpty { "That song" }
        if (player.hasNextMediaItem()) {
            Toast.makeText(this, "Couldn't play “$title” — skipped", Toast.LENGTH_SHORT).show()
            player.seekToNextMediaItem()
            player.prepare()
            player.play()
        }
    }

    /** Titles, artists and artwork found by a lookup go onto the songs that lacked them. */
    private fun fillIn(player: ExoPlayer, page: String, r: Streams.Resolved) {
        for (i in 0 until player.mediaItemCount) {
            val item = player.getMediaItemAt(i)
            if (Streams.pageUrlOf(item.mediaId) != page) continue
            val m = item.mediaMetadata
            val title = m.title?.toString().orEmpty()
            val needsTitle = title.isEmpty() || title.startsWith("http")
            val needsArtist = m.artist.isNullOrEmpty() && r.artist.isNotEmpty()
            val needsArt = m.artworkUri == null && r.thumbnail.startsWith("http")
            if (!needsTitle && !needsArtist && !needsArt) continue
            val meta = m.buildUpon()
                .setTitle(if (needsTitle) r.title.ifEmpty { title } else title)
                .setArtist(if (needsArtist) r.artist else m.artist)
                .setArtworkUri(if (needsArt) Uri.parse(r.thumbnail) else m.artworkUri)
                .setDurationMs(r.duration?.let { (it * 1000).toLong() } ?: m.durationMs)
                .build()
            player.replaceMediaItem(i, item.buildUpon().setMediaMetadata(meta).build())
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    // Swiping the app away stops playback unless something is actually playing.
    override fun onTaskRemoved(rootIntent: Intent?) {
        val player = session?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        Streams.onResolved = null
        session?.player?.let(::saveQueue)
        scope.cancel()
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }
}

/** The UI's handle on the player: a MediaController bound to [PlaybackService]. */
object PlayerConnection {
    private val _controller = MutableStateFlow<MediaController?>(null)
    val controller: StateFlow<MediaController?> = _controller.asStateFlow()
    private var future: ListenableFuture<MediaController>? = null
    private var pending: ((MediaController) -> Unit)? = null

    fun connect(context: Context) {
        if (future != null) return
        val app = context.applicationContext
        val token = SessionToken(app, ComponentName(app, PlaybackService::class.java))
        val f = MediaController.Builder(app, token).buildAsync()
        future = f
        f.addListener({
            val c = runCatching { f.get() }.getOrNull()
            _controller.value = c
            if (c != null) {
                val action = pending
                pending = null
                if (action != null) action(c) else restore(c)
            }
        }, ContextCompat.getMainExecutor(app))
    }

    private var restored = false

    /** Once per launch, an empty player gets back the queue it had, paused where it stopped. */
    private fun restore(c: MediaController) {
        if (restored) return
        restored = true
        val q = MusicStore.savedQueue.value ?: return
        if (c.mediaItemCount > 0) return
        c.setMediaItems(q.songs.map { it.toPlayItem().toMediaItem() }, q.index.coerceIn(q.songs.indices), q.positionMs)
        c.prepare()
    }

    // Outlives any one screen, so a radio started from a menu still arrives.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    /** Play [song] now, then line up its radio behind it. */
    fun startRadio(context: Context, song: Song) {
        play(context, listOf(song.toPlayItem()))
        scope.launch {
            val more = runCatching { Tracks.radioFor(song, setOf(song.key)) }.getOrDefault(emptyList())
            if (more.isNotEmpty()) enqueue(context, more.take(25).map { it.toPlayItem() })
        }
    }

    fun disconnect() {
        future?.let { MediaController.releaseFuture(it) }
        future = null
        _controller.value = null
    }

    private fun withController(context: Context, action: (MediaController) -> Unit) {
        val c = _controller.value
        if (c != null) action(c) else {
            pending = action
            connect(context)
        }
    }

    /** Replace the queue with [items] and start at [start]. */
    fun play(context: Context, items: List<PlayItem>, start: Int = 0) {
        if (items.isEmpty()) return
        restored = true
        withController(context) { c ->
            c.setMediaItems(items.map { it.toMediaItem() }, start.coerceIn(items.indices), 0L)
            c.prepare()
            c.play()
        }
    }

    /** Put [items] right after the current song; plays them if nothing is playing. */
    fun playNext(context: Context, items: List<PlayItem>) {
        if (items.isEmpty()) return
        withController(context) { c ->
            if (c.mediaItemCount == 0) {
                c.setMediaItems(items.map { it.toMediaItem() }); c.prepare(); c.play()
            } else {
                c.addMediaItems(c.currentMediaItemIndex + 1, items.map { it.toMediaItem() })
            }
        }
    }

    /** Add [items] to the end of the queue; plays them if nothing is playing. */
    fun enqueue(context: Context, items: List<PlayItem>) {
        if (items.isEmpty()) return
        withController(context) { c ->
            val wasEmpty = c.mediaItemCount == 0
            c.addMediaItems(items.map { it.toMediaItem() })
            if (wasEmpty) { c.prepare(); c.play() }
        }
    }
}
