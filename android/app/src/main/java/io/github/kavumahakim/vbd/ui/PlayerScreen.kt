package io.github.kavumahakim.vbd.ui

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ActivityInfo
import android.net.Uri
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Equalizer
import androidx.compose.material.icons.rounded.Forward10
import androidx.compose.material.icons.rounded.Fullscreen
import androidx.compose.material.icons.rounded.FullscreenExit
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Repeat
import androidx.compose.material.icons.rounded.RepeatOne
import androidx.compose.material.icons.rounded.Replay10
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.SkipPrevious
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.automirrored.rounded.PlaylistAdd
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.Radio
import androidx.compose.material3.Switch
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.Tracks
import io.github.kavumahakim.vbd.toMediaItem
import io.github.kavumahakim.vbd.toSong
import kotlinx.coroutines.launch
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.EXTRA_PAGE
import io.github.kavumahakim.vbd.SearchResult
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Streams
import io.github.kavumahakim.vbd.EXTRA_MIME
import io.github.kavumahakim.vbd.Library
import io.github.kavumahakim.vbd.Ytdlp
import kotlinx.coroutines.delay

// ----------------------------------------------------------------- state

/** A snapshot of the player for drawing; refreshed on every player event and twice a second. */
data class PlayerUi(
    val hasMedia: Boolean = false,
    val playing: Boolean = false,
    val buffering: Boolean = false,
    val position: Long = 0,
    val duration: Long = 0,
    val title: String = "",
    val subtitle: String = "",
    val artwork: String = "",
    val mediaUri: String = "",
    val mime: String = "",
    val video: Boolean = false,
    val aspect: Float = 16f / 9f,
    val index: Int = 0,
    val count: Int = 0,
    val speed: Float = 1f,
    val repeat: Int = Player.REPEAT_MODE_OFF,
    val shuffle: Boolean = false,
    val queue: List<MediaItem> = emptyList(),
    /** The page being streamed; empty for a file on the phone. */
    val pageUrl: String = "",
    val error: String = "",
) {
    val streaming: Boolean get() = pageUrl.isNotEmpty()
    val fraction: Float get() = if (duration > 0) (position.toFloat() / duration).coerceIn(0f, 1f) else 0f

    companion object {
        fun of(p: Player?): PlayerUi {
            if (p == null || p.mediaItemCount == 0) return PlayerUi()
            val item = p.currentMediaItem
            val meta = item?.mediaMetadata ?: MediaMetadata.EMPTY
            val size = p.videoSize
            val mime = meta.extras?.getString(EXTRA_MIME).orEmpty()
            return PlayerUi(
                hasMedia = true,
                playing = p.isPlaying,
                buffering = p.playbackState == Player.STATE_BUFFERING,
                position = p.currentPosition.coerceAtLeast(0),
                duration = p.duration.takeIf { it > 0 } ?: 0,
                title = meta.title?.toString().orEmpty(),
                subtitle = meta.artist?.toString().orEmpty(),
                artwork = meta.artworkUri?.toString().orEmpty(),
                mediaUri = item?.mediaId.orEmpty(),
                mime = mime,
                video = size.width > 0 || (meta.mediaType == MediaMetadata.MEDIA_TYPE_VIDEO && !mime.startsWith("audio/")
                    && meta.extras?.getString(EXTRA_PAGE).isNullOrEmpty()),
                aspect = if (size.width > 0 && size.height > 0) size.width * size.pixelWidthHeightRatio / size.height else 16f / 9f,
                index = p.currentMediaItemIndex,
                count = p.mediaItemCount,
                speed = p.playbackParameters.speed,
                repeat = p.repeatMode,
                shuffle = p.shuffleModeEnabled,
                queue = (0 until p.mediaItemCount).map { p.getMediaItemAt(it) },
                pageUrl = meta.extras?.getString(EXTRA_PAGE).orEmpty(),
                error = p.playerError?.let { e ->
                    generateSequence(e as Throwable) { it.cause }.mapNotNull { it.message }.lastOrNull() ?: e.errorCodeName
                }.orEmpty(),
            )
        }
    }
}

@Composable
fun rememberPlayerUi(player: Player?): PlayerUi {
    var ui by remember(player) { mutableStateOf(PlayerUi.of(player)) }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onEvents(p: Player, events: Player.Events) { ui = PlayerUi.of(p) }
        }
        player?.addListener(listener)
        onDispose { player?.removeListener(listener) }
    }
    LaunchedEffect(player) {
        while (player != null) {
            if (player.isPlaying) ui = PlayerUi.of(player)
            delay(500)
        }
    }
    return ui
}

private fun clock(ms: Long) = Ytdlp.formatDuration(ms / 1000.0).ifEmpty { "0:00" }

// -------------------------------------------------------------- artwork

/** Thumbnail from the web when the download had one, else a frame or cover from the file itself. */
@Composable
fun Artwork(web: String, mediaUri: String, audio: Boolean, modifier: Modifier = Modifier, corner: Dp = 28.dp) {
    val context = LocalContext.current
    val local by produceState<android.graphics.Bitmap?>(null, mediaUri, web) {
        value = if (web.isEmpty() && mediaUri.isNotEmpty()) Library.thumbnail(context, Uri.parse(mediaUri), audio) else null
    }
    Box(
        modifier.clip(RoundedCornerShape(corner)).background(MaterialTheme.colorScheme.secondaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            if (audio) Icons.Rounded.MusicNote else Icons.Rounded.Movie, contentDescription = null,
            tint = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.size(48.dp),
        )
        when {
            web.isNotEmpty() -> AsyncImage(web, null, contentScale = ContentScale.Crop, modifier = Modifier.matchParentSize())
            local != null -> Image(local!!.asImageBitmap(), null, contentScale = ContentScale.Crop,
                modifier = Modifier.matchParentSize())
        }
    }
}

// ----------------------------------------------------------- mini player

@Composable
fun MiniPlayer(player: Player?, ui: PlayerUi, onOpen: () -> Unit) {
    if (player == null || !ui.hasMedia) return
    Card(
        onClick = onOpen,
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Artwork(ui.artwork, ui.mediaUri, !ui.video, Modifier.size(48.dp), corner = 14.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(ui.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    ui.subtitle.ifEmpty { if (ui.count > 1) "${ui.index + 1} of ${ui.count}" else clock(ui.duration) },
                    style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.75f),
                )
            }
            IconButton(onClick = { if (ui.playing) player.pause() else player.play() }) {
                Icon(if (ui.playing) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
                    contentDescription = if (ui.playing) "Pause" else "Play")
            }
            if (ui.count > 1) {
                IconButton(onClick = { player.seekToNextMediaItem() }, enabled = player.hasNextMediaItem()) {
                    Icon(Icons.Rounded.SkipNext, contentDescription = "Next")
                }
            }
            // Stops playback and clears the queue, which hides the mini player.
            IconButton(onClick = { player.stop(); player.clearMediaItems() }) {
                Icon(Icons.Rounded.Close, contentDescription = "Stop and close")
            }
        }
        LinearProgressIndicator(
            progress = { ui.fraction },
            modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 8.dp),
        )
    }
}

// ----------------------------------------------------------- full player

@Composable
fun PlayerScreen(player: Player, ui: PlayerUi, onClose: () -> Unit) {
    var fullscreen by rememberSaveable { mutableStateOf(false) }
    val activity = LocalContext.current as? Activity

    // Fullscreen video turns the phone sideways and hides the status and navigation bars.
    DisposableEffect(fullscreen, activity) {
        val window = activity?.window
        if (activity != null && window != null) {
            val bars = WindowCompat.getInsetsController(window, window.decorView)
            if (fullscreen) {
                activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                bars.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                bars.hide(WindowInsetsCompat.Type.systemBars())
            } else {
                activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                bars.show(WindowInsetsCompat.Type.systemBars())
            }
        }
        onDispose {
            if (fullscreen && activity != null) {
                activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                activity.window?.let { WindowCompat.getInsetsController(it, it.decorView).show(WindowInsetsCompat.Type.systemBars()) }
            }
        }
    }
    LaunchedEffect(ui.video) { if (!ui.video) fullscreen = false }
    BackHandler { if (fullscreen) fullscreen = false else onClose() }

    if (fullscreen && ui.video) {
        FullscreenVideo(player, ui, onExit = { fullscreen = false })
        return
    }

    var showQueue by remember { mutableStateOf(false) }
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxSize()) {
        BoxWithConstraints(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
            val wide = maxWidth > maxHeight
            Column(Modifier.fillMaxSize().padding(horizontal = 20.dp)) {
                PlayerTopBar(ui, onClose = onClose, onQueue = { showQueue = true })
                if (wide) {
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                            Media(player, ui, onFullscreen = { fullscreen = true })
                        }
                        Spacer(Modifier.width(24.dp))
                        Column(Modifier.weight(1f)) { Controls(player, ui) }
                    }
                } else {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Media(player, ui, onFullscreen = { fullscreen = true })
                    }
                    Controls(player, ui)
                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }
    if (showQueue) QueueSheet(player, ui, onDismiss = { showQueue = false })
}

@Composable
private fun PlayerTopBar(ui: PlayerUi, onClose: () -> Unit, onQueue: () -> Unit) {
    val context = LocalContext.current
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        FilledTonalIconButton(onClick = onClose) {
            Icon(Icons.Rounded.KeyboardArrowDown, contentDescription = "Close player")
        }
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(if (ui.streaming) "Streaming" else "Now playing", style = MaterialTheme.typography.labelMedium,
                color = if (ui.streaming) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
            if (ui.count > 1) Text("${ui.index + 1} of ${ui.count}", style = MaterialTheme.typography.labelLarge)
        }
        if (ui.streaming) {
            DownloadButton(ui)
            DownloadCurrent(ui)
        } else IconButton(onClick = {
            if (ui.mediaUri.isEmpty()) return@IconButton
            val intent = Intent(Intent.ACTION_VIEW)
                .setDataAndType(Uri.parse(ui.mediaUri), ui.mime.ifEmpty { if (ui.video) "video/*" else "audio/*" })
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            try {
                context.startActivity(Intent.createChooser(intent, "Open with"))
            } catch (_: ActivityNotFoundException) {
                Toast.makeText(context, "No other app can open this file.", Toast.LENGTH_SHORT).show()
            }
        }) { Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = "Open in another app") }
        IconButton(onClick = onQueue) { Icon(Icons.AutoMirrored.Rounded.QueueMusic, contentDescription = "Queue") }
    }
}

@Composable
private fun Media(player: Player, ui: PlayerUi, onFullscreen: () -> Unit) {
    if (ui.video) {
        Box(
            Modifier.fillMaxWidth().aspectRatio(ui.aspect.coerceIn(0.5f, 2.4f), matchHeightConstraintsFirst = ui.aspect < 1f)
                .clip(RoundedCornerShape(28.dp)).background(Color.Black),
        ) {
            VideoSurface(player, Modifier.fillMaxSize())
            FilledTonalIconButton(
                onClick = onFullscreen,
                modifier = Modifier.align(Alignment.BottomEnd).padding(10.dp),
                colors = IconButtonDefaults.filledTonalIconButtonColors(
                    containerColor = Color.Black.copy(alpha = 0.45f), contentColor = Color.White),
            ) { Icon(Icons.Rounded.Fullscreen, contentDescription = "Full screen") }
        }
    } else {
        Artwork(ui.artwork, ui.mediaUri, audio = true,
            modifier = Modifier.fillMaxWidth().widthIn(max = 420.dp).aspectRatio(1f), corner = 36.dp)
    }
}

@OptIn(UnstableApi::class)
@Composable
private fun VideoSurface(player: Player, modifier: Modifier = Modifier) {
    AndroidView(
        factory = { ctx ->
            PlayerView(ctx).apply {
                useController = false
                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                setShutterBackgroundColor(android.graphics.Color.BLACK)
                layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            }
        },
        update = { it.player = player },
        onRelease = { it.player = null },
        modifier = modifier,
    )
}

/** ♥ for the song that is playing; also in the notification. */
@Composable
private fun LikeButton(player: Player) {
    val liked by MusicStore.liked.collectAsState()
    val song = player.currentMediaItem?.toSong() ?: return
    val on = liked.any { it.key == song.key }
    IconButton(onClick = { MusicStore.toggleLike(song) }) {
        Icon(
            if (on) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder,
            contentDescription = if (on) "Remove from Liked songs" else "Like",
            tint = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** ⬇ for the streamed song: save it as audio or as video. */
@Composable
private fun DownloadButton(ui: PlayerUi) {
    val context = LocalContext.current
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.Rounded.Download, contentDescription = "Download this song") }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            listOf(true to "Download audio", false to "Download video").forEach { (audio, label) ->
                DropdownMenuItem(
                    text = { Text(label) },
                    leadingIcon = { Icon(if (audio) Icons.Rounded.MusicNote else Icons.Rounded.Movie, null) },
                    onClick = {
                        open = false
                        val page = Streams.known(ui.pageUrl)?.webpage?.ifEmpty { null } ?: ui.pageUrl
                        Downloads.addSearchResults(
                            listOf(SearchResult(ui.title, page, ui.subtitle, ui.duration / 1000.0, null, ui.artwork)),
                            SettingsStore.current.copy(audioOnly = audio),
                        )
                        Toast.makeText(context, "Downloading ${if (audio) "audio" else "video"}", Toast.LENGTH_SHORT).show()
                    },
                )
            }
        }
    }
}

/** ⋮ for the streamed song: radio and playlists. */
@Composable
private fun DownloadCurrent(ui: PlayerUi) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val player by PlayerConnection.controller.collectAsState()
    var open by remember { mutableStateOf(false) }
    var addTo by remember { mutableStateOf(false) }
    val song = player?.currentMediaItem?.toSong()
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.Rounded.MoreVert, contentDescription = "More") }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            if (song?.videoId != null) {
                DropdownMenuItem(
                    text = { Text("Start radio") },
                    leadingIcon = { Icon(Icons.Rounded.Radio, null) },
                    onClick = {
                        open = false
                        // Keep this song playing; replace what follows it with its radio.
                        val c = player ?: return@DropdownMenuItem
                        scope.launch {
                            val more = runCatching { Tracks.radioFor(song, setOf(song.key)) }.getOrDefault(emptyList())
                            if (more.isEmpty()) {
                                Toast.makeText(context, "No radio found for this song.", Toast.LENGTH_SHORT).show()
                            } else {
                                val next = c.currentMediaItemIndex + 1
                                if (next < c.mediaItemCount) c.removeMediaItems(next, c.mediaItemCount)
                                c.addMediaItems(more.take(25).map { it.toPlayItem().toMediaItem() })
                                Toast.makeText(context, "Radio queued: ${more.size.coerceAtMost(25)} songs", Toast.LENGTH_SHORT).show()
                            }
                        }
                    },
                )
            }
            if (song != null) {
                DropdownMenuItem(
                    text = { Text("Add to playlist") },
                    leadingIcon = { Icon(Icons.AutoMirrored.Rounded.PlaylistAdd, null) },
                    onClick = { open = false; addTo = true },
                )
            }
        }
    }
    if (addTo && song != null) {
        AddToPlaylistSheet(listOf(song), onDismiss = { addTo = false },
            say = { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() })
    }
}

/** Shown when a song would not play: what went wrong, and a way to try again. */
@Composable
private fun PlaybackError(player: Player, message: String) {
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer,
        ),
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
    ) {
        Row(Modifier.padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.Error, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(12.dp))
            Text(message, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f))
            TextButton(onClick = { player.prepare(); player.play() }) { Text("Try again") }
        }
    }
}

@Composable
private fun SeekBar(player: Player, ui: PlayerUi, onDark: Boolean = false) {
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableFloatStateOf(0f) }
    val shown = if (dragging) dragValue else ui.fraction
    Column {
        Slider(
            value = shown,
            onValueChange = { dragging = true; dragValue = it },
            onValueChangeFinished = {
                if (ui.duration > 0) player.seekTo((dragValue * ui.duration).toLong())
                dragging = false
            },
            enabled = ui.duration > 0,
            colors = if (onDark) SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Color.White,
                inactiveTrackColor = Color.White.copy(alpha = 0.3f)) else SliderDefaults.colors(),
        )
        Row(Modifier.fillMaxWidth()) {
            val color = if (onDark) Color.White else MaterialTheme.colorScheme.onSurfaceVariant
            Text(clock(if (dragging) (dragValue * ui.duration).toLong() else ui.position),
                style = MaterialTheme.typography.labelMedium, color = color, modifier = Modifier.weight(1f))
            Text(clock(ui.duration), style = MaterialTheme.typography.labelMedium, color = color)
        }
    }
}

@Composable
private fun Controls(player: Player, ui: PlayerUi) {
    Column(Modifier.fillMaxWidth()) {
        Spacer(Modifier.height(20.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    ui.title, style = MaterialTheme.typography.headlineSmall, maxLines = 1,
                    modifier = Modifier.fillMaxWidth().basicMarquee(),
                )
                if (ui.subtitle.isNotEmpty()) {
                    Text(ui.subtitle, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (ui.streaming) LikeButton(player)
        }
        if (ui.error.isNotEmpty()) PlaybackError(player, ui.error)
        Spacer(Modifier.height(12.dp))
        SeekBar(player, ui)
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = { player.seekToPreviousMediaItem() }, enabled = ui.count > 1 || ui.position > 3000,
                modifier = Modifier.size(52.dp)) {
                Icon(Icons.Rounded.SkipPrevious, contentDescription = "Previous", modifier = Modifier.size(32.dp))
            }
            FilledTonalIconButton(onClick = { player.seekTo((ui.position - 10_000).coerceAtLeast(0)) },
                modifier = Modifier.size(52.dp)) {
                Icon(Icons.Rounded.Replay10, contentDescription = "Back 10 seconds")
            }
            Box(contentAlignment = Alignment.Center) {
                PlayPauseButton(player, ui.playing || (ui.buffering && player.playWhenReady))
                if (ui.buffering) CircularProgressIndicator(Modifier.size(92.dp), strokeWidth = 3.dp)
            }
            FilledTonalIconButton(onClick = { player.seekTo(ui.position + 10_000) }, modifier = Modifier.size(52.dp)) {
                Icon(Icons.Rounded.Forward10, contentDescription = "Forward 10 seconds")
            }
            IconButton(onClick = { player.seekToNextMediaItem() }, enabled = player.hasNextMediaItem(),
                modifier = Modifier.size(52.dp)) {
                Icon(Icons.Rounded.SkipNext, contentDescription = "Next", modifier = Modifier.size(32.dp))
            }
        }
        Spacer(Modifier.height(16.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        ) {
            FilterChip(
                selected = ui.shuffle,
                onClick = { player.shuffleModeEnabled = !ui.shuffle },
                label = { Text("Shuffle") },
                leadingIcon = { Icon(Icons.Rounded.Shuffle, null, Modifier.size(FilterChipDefaults.IconSize)) },
            )
            FilterChip(
                selected = ui.repeat != Player.REPEAT_MODE_OFF,
                onClick = {
                    player.repeatMode = when (ui.repeat) {
                        Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
                        Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
                        else -> Player.REPEAT_MODE_OFF
                    }
                },
                label = { Text(when (ui.repeat) { Player.REPEAT_MODE_ONE -> "Repeat one"; Player.REPEAT_MODE_ALL -> "Repeat all"; else -> "Repeat" }) },
                leadingIcon = {
                    Icon(if (ui.repeat == Player.REPEAT_MODE_ONE) Icons.Rounded.RepeatOne else Icons.Rounded.Repeat,
                        null, Modifier.size(FilterChipDefaults.IconSize))
                },
            )
            SpeedChip(player, ui.speed)
        }
    }
}

/** The big play button: a squircle while playing, a circle while paused. */
@Composable
private fun PlayPauseButton(player: Player, playing: Boolean, size: Dp = 80.dp) {
    val corner by animateDpAsState(if (playing) 26.dp else size / 2, label = "playShape")
    FilledIconButton(
        onClick = { if (playing) player.pause() else player.play() },
        shape = RoundedCornerShape(corner),
        modifier = Modifier.size(size),
    ) {
        Icon(if (playing) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
            contentDescription = if (playing) "Pause" else "Play", modifier = Modifier.size(size * 0.45f))
    }
}

@Composable
private fun SpeedChip(player: Player, speed: Float) {
    var open by remember { mutableStateOf(false) }
    Box {
        AssistChip(
            onClick = { open = true },
            label = { Text(speedLabel(speed)) },
            leadingIcon = { Icon(Icons.Rounded.Speed, null, Modifier.size(AssistChipDefaults.IconSize)) },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 1.75f, 2f).forEach { s ->
                DropdownMenuItem(text = { Text(speedLabel(s)) }, onClick = { player.setPlaybackSpeed(s); open = false })
            }
        }
    }
}

private fun speedLabel(s: Float) = (if (s % 1f == 0f) "%.0f".format(s) else "%s".format(s)) + "×"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun QueueSheet(player: Player, ui: PlayerUi, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        val settings by SettingsStore.state.collectAsState()
        Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 16.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Up next", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Text("Autoplay", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(end = 8.dp))
            Switch(checked = settings.autoplay, onCheckedChange = { v -> SettingsStore.update { it.copy(autoplay = v) } })
        }
        LazyColumn(contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 24.dp)) {
            itemsIndexed(ui.queue, key = { i, item -> "$i:${item.mediaId}" }) { i, item ->
                val current = i == ui.index
                val meta = item.mediaMetadata
                val audio = meta.extras?.getString(EXTRA_MIME).orEmpty().startsWith("audio/")
                ListItem(
                    modifier = Modifier.clip(RoundedCornerShape(20.dp)).clickable {
                        player.seekTo(i, 0)
                        player.play()
                    },
                    colors = ListItemDefaults.colors(
                        containerColor = if (current) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent),
                    leadingContent = {
                        Box {
                            Artwork(meta.artworkUri?.toString().orEmpty(), item.mediaId, audio,
                                Modifier.size(56.dp), corner = 14.dp)
                            if (current) {
                                Box(Modifier.matchParentSize().clip(RoundedCornerShape(14.dp))
                                    .background(Color.Black.copy(alpha = 0.45f)), contentAlignment = Alignment.Center) {
                                    Icon(Icons.Rounded.Equalizer, contentDescription = "Playing", tint = Color.White)
                                }
                            }
                        }
                    },
                    headlineContent = { Text(meta.title?.toString().orEmpty(), maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    supportingContent = meta.artist?.let { { Text(it.toString(), maxLines = 1) } },
                )
            }
        }
    }
}

// ------------------------------------------------------- fullscreen video

@Composable
private fun FullscreenVideo(player: Player, ui: PlayerUi, onExit: () -> Unit) {
    var controls by remember { mutableStateOf(true) }
    LaunchedEffect(controls, ui.playing) {
        if (controls && ui.playing) { delay(3500); controls = false }
    }
    Box(
        Modifier.fillMaxSize().background(Color.Black)
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { controls = !controls },
    ) {
        VideoSurface(player, Modifier.fillMaxSize())
        AnimatedVisibility(controls, enter = fadeIn(), exit = fadeOut(), modifier = Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.4f))) {
                Row(Modifier.fillMaxWidth().padding(16.dp).align(Alignment.TopStart),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(ui.title, color = Color.White, style = MaterialTheme.typography.titleMedium,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    IconButton(onClick = onExit) {
                        Icon(Icons.Rounded.FullscreenExit, contentDescription = "Leave full screen", tint = Color.White)
                    }
                }
                Row(Modifier.align(Alignment.Center), horizontalArrangement = Arrangement.spacedBy(28.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { player.seekTo((ui.position - 10_000).coerceAtLeast(0)) }) {
                        Icon(Icons.Rounded.Replay10, contentDescription = "Back 10 seconds", tint = Color.White,
                            modifier = Modifier.size(36.dp))
                    }
                    PlayPauseButton(player, ui.playing, size = 72.dp)
                    IconButton(onClick = { player.seekTo(ui.position + 10_000) }) {
                        Icon(Icons.Rounded.Forward10, contentDescription = "Forward 10 seconds", tint = Color.White,
                            modifier = Modifier.size(36.dp))
                    }
                }
                Box(Modifier.align(Alignment.BottomCenter).padding(horizontal = 24.dp, vertical = 12.dp)) {
                    SeekBar(player, ui, onDark = true)
                }
            }
        }
    }
}
