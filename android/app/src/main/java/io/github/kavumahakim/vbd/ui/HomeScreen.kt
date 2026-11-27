package io.github.kavumahakim.vbd.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.Headphones
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Radio
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.Song
import kotlinx.coroutines.launch
import java.util.Calendar

@Composable
fun HomeScreen(
    snackbar: SnackbarHostState,
    hasMedia: Boolean,
    onOpenSettings: () -> Unit,
    onOpenSearch: () -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onPlaying: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val history by MusicStore.history.collectAsState()
    val liked by MusicStore.liked.collectAsState()
    val playlists by MusicStore.playlists.collectAsState()
    val saved by MusicStore.savedQueue.collectAsState()
    val recent = remember(history) { MusicStore.recent(12) }
    val picks = remember(history) { MusicStore.topPlayed(8) }
    val seeds = remember(history) { MusicStore.mixSeeds(6) }
    fun say(text: String) {
        scope.launch { snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(text) }
    }
    fun play(songs: List<Song>, start: Int = 0) {
        PlayerConnection.play(context, songs.map { it.toPlayItem() }, start)
    }

    ScreenScaffold(
        title = greeting(),
        snackbar = snackbar,
        modifier = modifier,
        actions = { IconButton(onClick = onOpenSettings) { Icon(Icons.Rounded.Settings, contentDescription = "Settings") } },
    ) { inner ->
        LazyColumn(
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = inner.calculateTopPadding(), bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            if (history.isEmpty() && liked.isEmpty() && playlists.isEmpty()) {
                item {
                    EmptyState(
                        Icons.Rounded.Headphones,
                        "Start listening",
                        "Search for a song and tap ▶. What you play shows up here, with mixes made from it.",
                    )
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Button(onClick = onOpenSearch) {
                            Icon(Icons.Rounded.Search, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Find music")
                        }
                    }
                }
            }

            // Where you left off, when the player is empty (the queue usually comes back on its own).
            val q = saved
            if (q != null && !hasMedia) {
                item(key = "resume") {
                    val song = q.songs.getOrNull(q.index) ?: q.songs.first()
                    Card(
                        onClick = { play(q.songs, q.index); onPlaying() },
                        shape = RoundedCornerShape(24.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    ) {
                        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Artwork(song.artwork, "", audio = true, modifier = Modifier.size(56.dp), corner = 14.dp)
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text("Pick up where you left off", style = MaterialTheme.typography.labelMedium)
                                Text(song.title, style = MaterialTheme.typography.titleMedium, maxLines = 1,
                                    overflow = TextOverflow.Ellipsis)
                            }
                            FilledIconButton(onClick = { play(q.songs, q.index); onPlaying() }) {
                                Icon(Icons.Rounded.PlayArrow, contentDescription = "Resume")
                            }
                        }
                    }
                }
            }

            if (recent.isNotEmpty()) {
                item(key = "recent-h") { SectionHeader("Recently played") }
                item(key = "recent") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        itemsIndexed(recent, key = { _, s -> s.key }) { i, song ->
                            SongCard(song) { play(recent, i) }
                        }
                    }
                }
            }

            if (seeds.isNotEmpty()) {
                item(key = "mixes-h") { SectionHeader("Mixes for you") }
                item(key = "mixes") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        items(seeds, key = { it.key }) { seed ->
                            MixCard(seed) {
                                PlayerConnection.startRadio(context, seed)
                                say("Starting a mix from ${seed.title}…")
                            }
                        }
                    }
                }
            }

            if (picks.size >= 3) {
                item(key = "picks-h") {
                    SectionHeader("Quick picks", "Play all") { play(picks); onPlaying() }
                }
                itemsIndexed(picks, key = { _, s -> "pick:" + s.key }) { i, song ->
                    SongRow(song, onClick = { play(picks, i) }, say = ::say)
                }
            }

            item(key = "lists-h") { SectionHeader("Your playlists") }
            item(key = "lists") {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    item(key = "liked") {
                        PlaylistCard("Liked songs", "${liked.size} songs", liked, liked = true) {
                            onOpenPlaylist(MusicStore.LIKED_ID)
                        }
                    }
                    items(playlists, key = { it.id }) { p ->
                        PlaylistCard(p.name, "${p.songs.size} songs", p.songs) { onOpenPlaylist(p.id) }
                    }
                }
            }
        }
    }
}

@Composable
private fun MixCard(seed: Song, onClick: () -> Unit) {
    Column(Modifier.width(148.dp).clip(RoundedCornerShape(20.dp)).clickable(onClick = onClick).padding(6.dp)) {
        Box {
            Artwork(seed.artwork, "", audio = true, modifier = Modifier.fillMaxWidth().aspectRatio(1f), corner = 20.dp)
            Pill("Mix", Icons.Rounded.Radio, MaterialTheme.colorScheme.tertiaryContainer,
                MaterialTheme.colorScheme.onTertiaryContainer, Modifier.align(Alignment.BottomStart).padding(8.dp))
        }
        Spacer(Modifier.height(8.dp))
        Text(seed.artist.ifEmpty { seed.title } + " mix", style = MaterialTheme.typography.titleSmall, maxLines = 1,
            overflow = TextOverflow.Ellipsis)
        Text("Based on ${seed.title}", style = MaterialTheme.typography.bodySmall, maxLines = 1,
            overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun PlaylistCard(name: String, subtitle: String, songs: List<Song>, liked: Boolean = false, onClick: () -> Unit) {
    Column(Modifier.width(148.dp).clip(RoundedCornerShape(20.dp)).clickable(onClick = onClick).padding(6.dp)) {
        PlaylistCover(songs, Modifier.fillMaxWidth().aspectRatio(1f), liked = liked)
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(if (liked) Icons.Rounded.Favorite else Icons.AutoMirrored.Rounded.QueueMusic, null,
                Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(4.dp))
            Text(name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun greeting(): String = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
    in 5..11 -> "Good morning"
    in 12..17 -> "Good afternoon"
    else -> "Good evening"
}
