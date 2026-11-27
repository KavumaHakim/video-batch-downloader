package io.github.kavumahakim.vbd.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ArrowDownward
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.DriveFileRenameOutline
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.RemoveCircleOutline
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.Ytdlp
import kotlinx.coroutines.launch

/** One playlist (or Liked songs): play it, shuffle it, and tidy its songs. */
@Composable
fun PlaylistScreen(id: String, snackbar: SnackbarHostState, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // Read through the flows so edits show at once.
    val liked by MusicStore.liked.collectAsState()
    val lists by MusicStore.playlists.collectAsState()
    val playlist = remember(id, liked, lists) { MusicStore.playlist(id) }
    var menu by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    fun say(text: String) {
        scope.launch { snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(text) }
    }
    BackHandler(onBack = onBack)
    if (playlist == null) {
        LaunchedEffect(Unit) { onBack() }
        return
    }
    val isLiked = id == MusicStore.LIKED_ID
    val songs = playlist.songs

    ScreenScaffold(
        title = playlist.name,
        snackbar = snackbar,
        modifier = modifier,
        large = false,
        navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, "Back") } },
        actions = {
            if (!isLiked) {
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Rounded.MoreVert, "More") }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Rename") }, leadingIcon = { Icon(Icons.Rounded.DriveFileRenameOutline, null) },
                            onClick = { menu = false; renaming = true })
                        DropdownMenuItem(text = { Text("Delete playlist") },
                            leadingIcon = { Icon(Icons.Rounded.Delete, null, tint = MaterialTheme.colorScheme.error) },
                            onClick = { menu = false; deleting = true })
                    }
                }
            }
        },
    ) { inner ->
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = inner.calculateTopPadding() + 8.dp, bottom = 24.dp),
        ) {
            item(key = "header") {
                Column(Modifier.fillMaxWidth().padding(bottom = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    PlaylistCover(songs, Modifier.size(180.dp), liked = isLiked)
                    Spacer(Modifier.height(12.dp))
                    val total = songs.sumOf { it.durationSec ?: 0.0 }
                    Text(
                        listOfNotNull(
                            if (songs.size == 1) "1 song" else "${songs.size} songs",
                            Ytdlp.formatDuration(total).takeIf { total > 0 },
                        ).joinToString(" · "),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Button(onClick = { PlayerConnection.play(context, songs.map { it.toPlayItem() }) }, enabled = songs.isNotEmpty()) {
                            Icon(Icons.Rounded.PlayArrow, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Play")
                        }
                        FilledTonalButton(
                            onClick = { PlayerConnection.play(context, songs.shuffled().map { it.toPlayItem() }) },
                            enabled = songs.isNotEmpty(),
                        ) {
                            Icon(Icons.Rounded.Shuffle, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Shuffle")
                        }
                    }
                }
            }
            if (songs.isEmpty()) {
                item(key = "empty") {
                    EmptyState(Icons.Rounded.LibraryMusic, "No songs yet",
                        if (isLiked) "Tap ♥ in the player, or Like in any song's ⋮ menu."
                        else "Use Add to playlist in any song's ⋮ menu.")
                }
            }
            itemsIndexed(songs, key = { i, s -> "$i:${s.key}" }) { i, song ->
                SongRow(
                    song,
                    onClick = { PlayerConnection.play(context, songs.map { it.toPlayItem() }, i) },
                    say = ::say,
                    extraMenu = { close ->
                        if (i > 0) DropdownMenuItem(text = { Text("Move up") }, leadingIcon = { Icon(Icons.Rounded.ArrowUpward, null) },
                            onClick = { close(); MusicStore.moveInPlaylist(id, i, i - 1) })
                        if (i < songs.lastIndex) DropdownMenuItem(text = { Text("Move down") },
                            leadingIcon = { Icon(Icons.Rounded.ArrowDownward, null) },
                            onClick = { close(); MusicStore.moveInPlaylist(id, i, i + 1) })
                        DropdownMenuItem(
                            text = { Text("Remove from this playlist") },
                            leadingIcon = { Icon(Icons.Rounded.RemoveCircleOutline, null) },
                            onClick = {
                                close()
                                MusicStore.removeFromPlaylist(id, i)
                                scope.launch {
                                    snackbar.currentSnackbarData?.dismiss()
                                    val r = snackbar.showSnackbar("Removed ${song.title}", actionLabel = "Undo")
                                    if (r == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                                        MusicStore.addToPlaylist(id, listOf(song))
                                        MusicStore.playlist(id)?.songs?.let { now ->
                                            MusicStore.moveInPlaylist(id, if (isLiked) 0 else now.lastIndex, i)
                                        }
                                    }
                                }
                            },
                        )
                    },
                )
            }
        }
    }

    if (renaming) {
        NameDialog("Rename playlist", playlist.name, "Rename", onDismiss = { renaming = false }) {
            MusicStore.renamePlaylist(id, it); renaming = false
        }
    }
    if (deleting) {
        AlertDialog(
            onDismissRequest = { deleting = false },
            icon = { Icon(Icons.Rounded.Delete, null) },
            title = { Text("Delete “${playlist.name}”?") },
            text = { Text("The playlist goes; the songs stay wherever else you have them.", maxLines = 3, overflow = TextOverflow.Ellipsis) },
            confirmButton = {
                TextButton(
                    onClick = { deleting = false; MusicStore.deletePlaylist(id); onBack() },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text("Cancel") } },
        )
    }
}
