package io.github.kavumahakim.vbd.ui

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.text.format.Formatter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material.icons.rounded.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Song
import io.github.kavumahakim.vbd.Tracks
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.JobStatus
import io.github.kavumahakim.vbd.Library
import io.github.kavumahakim.vbd.LibraryItem
import io.github.kavumahakim.vbd.MediaSaver
import io.github.kavumahakim.vbd.PlayerConnection
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun LibraryScreen(
    snackbar: SnackbarHostState,
    onPlaying: () -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onOpenSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var section by rememberSaveable { mutableIntStateOf(0) } // 0 playlists, 1 downloaded files
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val jobs by Downloads.jobs.collectAsState()
    var items by remember { mutableStateOf<List<LibraryItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var filter by rememberSaveable { mutableIntStateOf(0) } // 0 all, 1 video, 2 audio
    var toDelete by remember { mutableStateOf<LibraryItem?>(null) }
    val finishedCount = jobs.count { it.status == JobStatus.Done }

    fun reload() {
        scope.launch {
            loading = true
            items = runCatching { Library.load(context) }.getOrDefault(emptyList())
            loading = false
        }
    }
    fun say(text: String) {
        scope.launch {
            snackbar.currentSnackbarData?.dismiss()
            snackbar.showSnackbar(text)
        }
    }
    LaunchedEffect(finishedCount) { reload() }
    LifecycleResumeEffect(Unit) {
        reload()
        onPauseOrDispose { }
    }
    // Android asks the user itself before deleting a file an earlier install saved.
    val confirmDelete = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) {
        if (it.resultCode == Activity.RESULT_OK) { say("Deleted."); reload() }
    }

    val shown = when (filter) {
        1 -> items.filterNot { it.audio }
        2 -> items.filter { it.audio }
        else -> items
    }
    fun play(start: Int) {
        PlayerConnection.play(context, shown.map { it.toPlayItem() }, start)
        onPlaying()
    }

    ScreenScaffold(
        title = "Library",
        snackbar = snackbar,
        modifier = modifier,
        actions = {
            if (section == 1) IconButton(onClick = { reload() }) { Icon(Icons.Rounded.Refresh, contentDescription = "Refresh") }
            IconButton(onClick = onOpenSettings) { Icon(Icons.Rounded.Settings, contentDescription = "Settings") }
        },
        floatingActionButton = {
            if (section == 1 && shown.isNotEmpty()) {
                ExtendedFloatingActionButton(
                    onClick = { play(0) },
                    icon = { Icon(Icons.Rounded.PlayArrow, contentDescription = null) },
                    text = { Text("Play all") },
                )
            }
        },
    ) { inner ->
        Column(Modifier.fillMaxSize().padding(top = inner.calculateTopPadding())) {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                listOf("Playlists", "Downloaded").forEachIndexed { i, label ->
                    SegmentedButton(
                        selected = section == i,
                        onClick = { section = i },
                        shape = SegmentedButtonDefaults.itemShape(index = i, count = 2),
                    ) { Text(label) }
                }
            }
            if (section == 0) {
                PlaylistsSection(snackbar, onOpenPlaylist)
                return@Column
            }
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                val counts = listOf(items.size, items.count { !it.audio }, items.count { it.audio })
                items(listOf("All", "Videos", "Music").withIndex().toList()) { (i, label) ->
                    FilterChip(
                        selected = filter == i,
                        onClick = { filter = i },
                        label = { Text("$label · ${counts[i]}") },
                        leadingIcon = if (filter == i) {
                            { Icon(Icons.Rounded.Check, null, Modifier.size(FilterChipDefaults.IconSize)) }
                        } else null,
                    )
                }
            }
            if (loading && items.isEmpty()) LinearProgressIndicator(Modifier.fillMaxWidth().padding(16.dp))
            Box(Modifier.weight(1f)) {
                if (!loading && shown.isEmpty()) {
                    EmptyState(
                        Icons.Rounded.VideoLibrary,
                        if (items.isEmpty()) "No downloads yet" else "Nothing here",
                        "Everything this app saves to ${MediaSaver.LOCATION} shows up here, ready to play.",
                    )
                } else {
                    LazyColumn(
                        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 104.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        itemsIndexed(shown, key = { _, it -> it.uri.toString() }) { i, item ->
                            LibraryRow(
                                item,
                                onPlay = { play(i) },
                                onOpenWith = { if (!openWith(context, item)) say("No other app can open this file.") },
                                onShare = { share(context, item) },
                                onDelete = { toDelete = item },
                                modifier = Modifier.animateItem(),
                            )
                        }
                    }
                }
            }
        }
    }

    toDelete?.let { item ->
        AlertDialog(
            onDismissRequest = { toDelete = null },
            icon = { Icon(Icons.Rounded.Delete, contentDescription = null) },
            title = { Text("Delete this file?") },
            text = { Text("“${item.title}” will be removed from your phone. This can't be undone.") },
            confirmButton = {
                TextButton(
                    onClick = {
                        toDelete = null
                        scope.launch {
                            try {
                                val request = withContext(Dispatchers.IO) { Library.delete(context, item) }
                                if (request != null) {
                                    confirmDelete.launch(IntentSenderRequest.Builder(request).build())
                                } else {
                                    items = items.filterNot { it.uri == item.uri }
                                    say("Deleted.")
                                }
                            } catch (e: Exception) {
                                say("Could not delete: ${e.message}")
                            }
                        }
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { toDelete = null }) { Text("Cancel") } },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LibraryRow(
    item: LibraryItem,
    onPlay: () -> Unit,
    onOpenWith: () -> Unit,
    onShare: () -> Unit,
    onDelete: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(20.dp)
    Card(
        shape = shape,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
        modifier = modifier.fillMaxWidth().clip(shape).combinedClickable(onClick = onPlay, onLongClick = { menu = true }),
    ) {
        Row(Modifier.padding(start = 10.dp, top = 10.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            val thumb = if (item.audio) Modifier.size(64.dp) else Modifier.size(width = 112.dp, height = 63.dp)
            Artwork("", item.uri.toString(), item.audio, thumb, corner = 14.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(item.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val meta = listOf(
                    item.folder,
                    item.name.substringAfterLast('.', "").uppercase(),
                    Formatter.formatShortFileSize(context, item.size),
                ).filter { it.isNotEmpty() }.joinToString(" · ")
                Text(meta, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
            }
            Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Rounded.MoreVert, contentDescription = "More") }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(
                        text = { Text("Play") }, leadingIcon = { Icon(Icons.Rounded.PlayArrow, null) },
                        onClick = { menu = false; onPlay() },
                    )
                    DropdownMenuItem(
                        text = { Text("Open with…") }, leadingIcon = { Icon(Icons.AutoMirrored.Rounded.OpenInNew, null) },
                        onClick = { menu = false; onOpenWith() },
                    )
                    DropdownMenuItem(
                        text = { Text("Share") }, leadingIcon = { Icon(Icons.Rounded.Share, null) },
                        onClick = { menu = false; onShare() },
                    )
                    DropdownMenuItem(
                        text = { Text("Delete") },
                        leadingIcon = { Icon(Icons.Rounded.Delete, null, tint = MaterialTheme.colorScheme.error) },
                        onClick = { menu = false; onDelete() },
                    )
                }
            }
        }
    }
}

private fun openWith(context: Context, item: LibraryItem): Boolean {
    val intent = Intent(Intent.ACTION_VIEW).setDataAndType(item.uri, item.mime)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    return try {
        context.startActivity(Intent.createChooser(intent, "Open with"))
        true
    } catch (_: ActivityNotFoundException) {
        false
    }
}

private fun share(context: Context, item: LibraryItem) {
    val intent = Intent(Intent.ACTION_SEND).setType(item.mime)
        .putExtra(Intent.EXTRA_STREAM, item.uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(intent, "Share ${item.title}"))
}

@Composable
private fun PlaylistsSection(snackbar: SnackbarHostState, onOpenPlaylist: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    val liked by MusicStore.liked.collectAsState()
    val playlists by MusicStore.playlists.collectAsState()
    var naming by remember { mutableStateOf(false) }
    var importing by remember { mutableStateOf(false) }
    var importBusy by remember { mutableStateOf(false) }
    fun say(text: String) {
        scope.launch { snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(text) }
    }
    LazyColumn(
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "actions") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = { naming = true }, label = { Text("New playlist") },
                    leadingIcon = { Icon(Icons.Rounded.Add, null, Modifier.size(AssistChipDefaults.IconSize)) })
                AssistChip(onClick = { importing = true }, label = { Text(if (importBusy) "Importing…" else "Import from link") },
                    enabled = !importBusy,
                    leadingIcon = { Icon(Icons.Rounded.Link, null, Modifier.size(AssistChipDefaults.IconSize)) })
            }
        }
        item(key = "liked") {
            PlaylistRow("Liked songs", liked.size, liked, liked = true) { onOpenPlaylist(MusicStore.LIKED_ID) }
        }
        items(playlists, key = { it.id }) { p ->
            PlaylistRow(p.name, p.songs.size, p.songs) { onOpenPlaylist(p.id) }
        }
        if (playlists.isEmpty()) {
            item(key = "hint") {
                Text(
                    "Make a playlist here, or bring one in from Spotify or YouTube with Import from link.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(8.dp),
                )
            }
        }
    }
    if (naming) {
        NameDialog("New playlist", "", "Create", onDismiss = { naming = false }) { name ->
            val p = MusicStore.createPlaylist(name); naming = false; onOpenPlaylist(p.id)
        }
    }
    if (importing) {
        NameDialog("Spotify or YouTube playlist link", "", "Import", onDismiss = { importing = false }) { link ->
            importing = false
            importBusy = true
            scope.launch {
                try {
                    val (name, songs) = Tracks.importLink(link.trim(), SettingsStore.current)
                    if (songs.isEmpty()) say("That playlist is empty.")
                    else {
                        val p = MusicStore.createPlaylist(name, songs)
                        say("Imported ${songs.size} songs into ${p.name}")
                    }
                } catch (e: Exception) {
                    say("Couldn't import: ${e.message}")
                } finally {
                    importBusy = false
                }
            }
        }
    }
}

@Composable
private fun PlaylistRow(name: String, count: Int, songs: List<Song>, liked: Boolean = false, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            PlaylistCover(songs, Modifier.size(64.dp), liked = liked)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(if (count == 1) "1 song" else "$count songs", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
