package io.github.kavumahakim.vbd.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.SearchOff
import androidx.compose.material.icons.rounded.TravelExplore
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.automirrored.rounded.PlaylistPlay
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.ui.platform.LocalContext
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.Tracks
import io.github.kavumahakim.vbd.Song
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.Search
import io.github.kavumahakim.vbd.SearchResult
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Ytdlp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * The search lives outside the screen, so the query, results and ticks are
 * still there after a trip to another tab, and a search still finishes.
 */
private object SearchSession {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    var query by mutableStateOf("")
    var results by mutableStateOf<List<SearchResult>>(emptyList())
    var searched by mutableStateOf(false)
    var loading by mutableStateOf(false)
    var error by mutableStateOf("")
    val selected = mutableStateListOf<String>()
}

@Composable
fun SearchScreen(snackbar: SnackbarHostState, onQueued: () -> Unit, modifier: Modifier = Modifier) {
    val keyboard = LocalSoftwareKeyboardController.current
    val context = LocalContext.current
    val uiScope = rememberCoroutineScope()
    fun say(text: String) {
        uiScope.launch {
            snackbar.currentSnackbarData?.dismiss()
            snackbar.showSnackbar(text)
        }
    }
    val settings by SettingsStore.state.collectAsState()
    val askNotifications = rememberNotificationAsk()
    var query by SearchSession::query
    var results by SearchSession::results
    var searched by SearchSession::searched
    var loading by SearchSession::loading
    var error by SearchSession::error
    val selected = SearchSession.selected
    // Only YouTube offers direct audio links the player can stream today.
    val canStream = settings.searchSite in Ytdlp.STREAMABLE_SITES
    val siteName = Ytdlp.SEARCH_SITES.firstOrNull { it.first == settings.searchSite }?.second ?: "YouTube"

    fun run(site: String = settings.searchSite) {
        if (query.isBlank() || loading) return
        keyboard?.hide()
        loading = true
        error = ""
        selected.clear()
        val q = query
        SearchSession.scope.launch {
            try {
                results = Search.search(q, site)
            } catch (e: Exception) {
                results = emptyList()
                error = e.message ?: e.toString()
            } finally {
                loading = false
                searched = true
            }
        }
    }

    ScreenScaffold(
        title = "Search",
        snackbar = snackbar,
        modifier = modifier,
        floatingActionButton = {
            AnimatedVisibility(visible = selected.isNotEmpty(), enter = scaleIn(), exit = scaleOut()) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (canStream) ExtendedFloatingActionButton(
                        onClick = {
                            PlayerConnection.play(context, Tracks.fromSearch(results.filter { it.url in selected }))
                            selected.clear()
                        },
                        icon = { Icon(Icons.Rounded.PlayArrow, contentDescription = null) },
                        text = { Text("Play") },
                        containerColor = MaterialTheme.colorScheme.secondaryContainer,
                        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                    ExtendedFloatingActionButton(
                        onClick = {
                            Downloads.addSearchResults(results.filter { it.url in selected }, settings)
                            selected.clear()
                            askNotifications()
                            onQueued()
                        },
                        icon = { Icon(Icons.Rounded.Download, contentDescription = null) },
                        text = { Text("Download ${selected.size}") },
                    )
                }
            }
        },
    ) { inner ->
        Column(Modifier.fillMaxSize().padding(top = inner.calculateTopPadding())) {
            TextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                singleLine = true,
                shape = CircleShape,
                placeholder = { Text("Search $siteName") },
                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null) },
                trailingIcon = {
                    if (query.isNotEmpty()) {
                        IconButton(onClick = { query = "" }) { Icon(Icons.Rounded.Close, contentDescription = "Clear") }
                    }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { run() }),
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
            )
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(Ytdlp.SEARCH_SITES, key = { it.first }) { (key, name) ->
                    val on = settings.searchSite == key
                    FilterChip(
                        selected = on,
                        onClick = {
                            SettingsStore.update { it.copy(searchSite = key) }
                            if (searched && !on) run(key)
                        },
                        label = { Text(name) },
                        leadingIcon = if (on) {
                            { Icon(Icons.Rounded.Check, null, Modifier.size(FilterChipDefaults.IconSize)) }
                        } else null,
                    )
                }
            }
            ModeToggle(settings.audioOnly, Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp))
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    error.isNotEmpty() -> EmptyState(Icons.Rounded.SearchOff, "Search failed", error)
                    searched && !loading && results.isEmpty() ->
                        EmptyState(Icons.Rounded.SearchOff, "Nothing found", "Try other words, or another site.")
                    !searched && !loading -> EmptyState(
                        Icons.Rounded.TravelExplore,
                        "Find something to play or download",
                        "Tap ▶ to listen right away, or tick a few and download them all at once.",
                    )
                    else -> LazyColumn(
                        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 104.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (results.isNotEmpty()) {
                            item(key = "count") {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text("${results.size} results", style = MaterialTheme.typography.labelLarge,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.weight(1f).padding(start = 8.dp))
                                    TextButton(onClick = {
                                        if (selected.size == results.size) selected.clear()
                                        else { selected.clear(); selected.addAll(results.map { it.url }) }
                                    }) { Text(if (selected.size == results.size) "Select none" else "Select all") }
                                }
                            }
                        }
                        items(results, key = { it.url }) { r ->
                            ResultCard(
                                r, checked = r.url in selected, audio = settings.audioOnly,
                                onToggle = { if (r.url in selected) selected.remove(r.url) else selected.add(r.url) },
                                canStream = canStream,
                                square = settings.searchSite == "ytmusic",
                                say = ::say,
                                onPlay = { PlayerConnection.play(context, Tracks.fromSearch(listOf(r))) },
                                onPlayNext = {
                                    PlayerConnection.playNext(context, Tracks.fromSearch(listOf(r)))
                                    say("Playing next")
                                },
                                onQueue = {
                                    PlayerConnection.enqueue(context, Tracks.fromSearch(listOf(r)))
                                    say("Added to the queue")
                                },
                                onDownload = {
                                    Downloads.addSearchResults(listOf(r), settings)
                                    askNotifications()
                                    say("Downloading ${if (settings.audioOnly) "audio" else "video"}")
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ResultCard(
    r: SearchResult,
    checked: Boolean,
    audio: Boolean,
    onToggle: () -> Unit,
    canStream: Boolean,
    square: Boolean,
    say: (String) -> Unit,
    onPlay: () -> Unit,
    onPlayNext: () -> Unit,
    onQueue: () -> Unit,
    onDownload: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Card(
        onClick = onToggle,
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (checked) MaterialTheme.colorScheme.secondaryContainer
                             else MaterialTheme.colorScheme.surfaceContainerLow,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Box {
                if (square) {
                    Artwork(r.thumbnail, "", audio = true, modifier = Modifier.size(64.dp), corner = 14.dp)
                } else {
                    Thumbnail(r.thumbnail, audio = audio, width = 120.dp)
                }
                if (checked) {
                    Box(
                        Modifier.align(Alignment.Center).size(36.dp)
                            .background(MaterialTheme.colorScheme.primary, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Rounded.Check, contentDescription = "Selected",
                            tint = MaterialTheme.colorScheme.onPrimary)
                    }
                }
                val duration = Ytdlp.formatDuration(r.duration)
                if (duration.isNotEmpty()) {
                    Text(
                        duration,
                        style = MaterialTheme.typography.labelSmall,
                        color = Color.White,
                        modifier = Modifier.align(Alignment.BottomEnd).padding(4.dp)
                            .background(Color.Black.copy(alpha = 0.7f), RoundedCornerShape(6.dp))
                            .padding(horizontal = 5.dp, vertical = 1.dp),
                    )
                }
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(r.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val meta = listOf(r.uploader, Ytdlp.formatViews(r.views)).filter { it.isNotEmpty() }.joinToString(" · ")
                if (meta.isNotEmpty()) {
                    Text(meta, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                }
            }
            if (canStream) {
                FilledTonalIconButton(onClick = onPlay) {
                    Icon(Icons.Rounded.PlayArrow, contentDescription = "Play ${r.title}")
                }
            }
            if (canStream) {
                SongMenuButton(Song(r.url, r.title, r.uploader, r.thumbnail, r.duration), say)
            } else Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Rounded.MoreVert, contentDescription = "More") }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    if (canStream) {
                        DropdownMenuItem(text = { Text("Play next") },
                            leadingIcon = { Icon(Icons.AutoMirrored.Rounded.PlaylistPlay, null) },
                            onClick = { menu = false; onPlayNext() })
                        DropdownMenuItem(text = { Text("Add to queue") },
                            leadingIcon = { Icon(Icons.AutoMirrored.Rounded.QueueMusic, null) },
                            onClick = { menu = false; onQueue() })
                    }
                    DropdownMenuItem(text = { Text("Download") },
                        leadingIcon = { Icon(Icons.Rounded.Download, null) },
                        onClick = { menu = false; onDownload() })
                }
            }
        }
    }
}
