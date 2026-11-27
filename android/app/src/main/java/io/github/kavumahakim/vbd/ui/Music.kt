package io.github.kavumahakim.vbd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.PlaylistAdd
import androidx.compose.material.icons.automirrored.rounded.PlaylistPlay
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.Radio
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.SearchResult
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Song
import io.github.kavumahakim.vbd.Ytdlp

/** A song as a list row: cover, title, artist and length, with its menu. */
@Composable
fun SongRow(
    song: Song,
    onClick: () -> Unit,
    say: (String) -> Unit,
    modifier: Modifier = Modifier,
    highlighted: Boolean = false,
    extraMenu: @Composable ColumnScope.(close: () -> Unit) -> Unit = {},
) {
    ListItem(
        modifier = modifier.clip(RoundedCornerShape(16.dp)).clickable(onClick = onClick),
        colors = ListItemDefaults.colors(
            containerColor = if (highlighted) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent),
        leadingContent = { Artwork(song.artwork, "", audio = true, modifier = Modifier.size(52.dp), corner = 12.dp) },
        headlineContent = { Text(song.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        supportingContent = {
            val meta = listOf(song.artist, Ytdlp.formatDuration(song.durationSec)).filter { it.isNotEmpty() }
            Text(meta.joinToString(" · "), maxLines = 1, overflow = TextOverflow.Ellipsis)
        },
        trailingContent = { SongMenuButton(song, say, extraMenu) },
    )
}

/** A song as a square card, for the rows on Home. */
@Composable
fun SongCard(song: Song, subtitle: String = song.artist, onClick: () -> Unit) {
    Column(Modifier.width(148.dp).clip(RoundedCornerShape(20.dp)).clickable(onClick = onClick).padding(6.dp)) {
        Artwork(song.artwork, "", audio = true, modifier = Modifier.fillMaxWidth().aspectRatio(1f), corner = 20.dp)
        Spacer(Modifier.height(8.dp))
        Text(song.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(subtitle, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** ⋮ with what can be done to any song, plus [extraMenu] items from the screen showing it. */
@Composable
fun SongMenuButton(
    song: Song,
    say: (String) -> Unit,
    extraMenu: @Composable ColumnScope.(close: () -> Unit) -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val liked by MusicStore.liked.collectAsState()
    var open by remember { mutableStateOf(false) }
    var addTo by remember { mutableStateOf(false) }
    val isLiked = liked.any { it.key == song.key }
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.Rounded.MoreVert, contentDescription = "More for ${song.title}") }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            val close = { open = false }
            DropdownMenuItem(text = { Text("Play next") }, leadingIcon = { Icon(Icons.AutoMirrored.Rounded.PlaylistPlay, null) },
                onClick = { close(); PlayerConnection.playNext(context, listOf(song.toPlayItem())); say("Playing next") })
            DropdownMenuItem(text = { Text("Add to queue") }, leadingIcon = { Icon(Icons.AutoMirrored.Rounded.QueueMusic, null) },
                onClick = { close(); PlayerConnection.enqueue(context, listOf(song.toPlayItem())); say("Added to the queue") })
            if (song.videoId != null) {
                DropdownMenuItem(text = { Text("Start radio") }, leadingIcon = { Icon(Icons.Rounded.Radio, null) },
                    onClick = { close(); PlayerConnection.startRadio(context, song); say("Starting radio…") })
            }
            DropdownMenuItem(
                text = { Text(if (isLiked) "Remove from Liked songs" else "Like") },
                leadingIcon = { Icon(if (isLiked) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder, null) },
                onClick = { close(); say(if (MusicStore.toggleLike(song)) "Added to Liked songs" else "Removed from Liked songs") },
            )
            DropdownMenuItem(text = { Text("Add to playlist") }, leadingIcon = { Icon(Icons.AutoMirrored.Rounded.PlaylistAdd, null) },
                onClick = { close(); addTo = true })
            DropdownMenuItem(text = { Text("Download") }, leadingIcon = { Icon(Icons.Rounded.Download, null) },
                onClick = {
                    close()
                    Downloads.addSearchResults(
                        listOf(SearchResult(song.title, song.pageUrl, song.artist, song.durationSec, null, song.artwork)),
                        SettingsStore.current,
                    )
                    say("Downloading ${if (SettingsStore.current.audioOnly) "audio" else "video"}")
                })
            extraMenu(close)
        }
    }
    if (addTo) AddToPlaylistSheet(listOf(song), onDismiss = { addTo = false }, say = say)
}

/** Pick a playlist (or make one) for [songs]. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddToPlaylistSheet(songs: List<Song>, onDismiss: () -> Unit, say: (String) -> Unit) {
    val playlists by MusicStore.playlists.collectAsState()
    var naming by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text("Add to playlist", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 24.dp, bottom = 8.dp))
        LazyColumn(contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 24.dp)) {
            item {
                ListItem(
                    modifier = Modifier.clip(RoundedCornerShape(16.dp)).clickable { naming = true },
                    colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                    leadingContent = { Icon(Icons.Rounded.Add, null) },
                    headlineContent = { Text("New playlist") },
                )
            }
            item {
                PlaylistPickRow("Liked songs", MusicStore.liked.value.size, Icons.Rounded.Favorite) {
                    val n = MusicStore.addToPlaylist(MusicStore.LIKED_ID, songs)
                    say(if (n == 0) "Already in Liked songs" else "Added to Liked songs"); onDismiss()
                }
            }
            items(playlists, key = { it.id }) { p ->
                PlaylistPickRow(p.name, p.songs.size, Icons.AutoMirrored.Rounded.QueueMusic) {
                    val n = MusicStore.addToPlaylist(p.id, songs)
                    say(if (n == 0) "Already in ${p.name}" else "Added to ${p.name}"); onDismiss()
                }
            }
        }
    }
    if (naming) {
        NameDialog("New playlist", "", "Create", onDismiss = { naming = false }) { name ->
            val p = MusicStore.createPlaylist(name, songs)
            say("Added to ${p.name}")
            naming = false
            onDismiss()
        }
    }
}

@Composable
private fun PlaylistPickRow(name: String, count: Int, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    ListItem(
        modifier = Modifier.clip(RoundedCornerShape(16.dp)).clickable(onClick = onClick),
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        leadingContent = { Icon(icon, null) },
        headlineContent = { Text(name) },
        supportingContent = { Text(if (count == 1) "1 song" else "$count songs") },
    )
}

/** A small dialog asking for a name, for new and renamed playlists. */
@Composable
fun NameDialog(title: String, initial: String, confirm: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(value = name, onValueChange = { name = it.take(80) }, singleLine = true,
                placeholder = { Text("Name") }, shape = RoundedCornerShape(16.dp))
        },
        confirmButton = { TextButton(onClick = { onConfirm(name) }, enabled = name.isNotBlank()) { Text(confirm) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** A playlist's cover: its first song's art. */
@Composable
fun PlaylistCover(songs: List<Song>, modifier: Modifier, liked: Boolean = false) {
    if (liked) {
        Box(modifier.clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.Favorite, null, tint = MaterialTheme.colorScheme.onPrimaryContainer)
        }
    } else {
        Artwork(songs.firstOrNull()?.artwork.orEmpty(), "", audio = true, modifier = modifier, corner = 16.dp)
    }
}

/** A row of a title and an optional action, above a section of Home or Library. */
@Composable
fun SectionHeader(title: String, action: String? = null, onAction: () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(start = 8.dp, top = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
        if (action != null) TextButton(onClick = onAction) { Text(action) }
    }
}
