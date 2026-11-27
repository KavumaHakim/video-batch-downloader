package io.github.kavumahakim.vbd.ui

import android.content.ClipboardManager
import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.DownloadForOffline
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material.icons.rounded.Headphones
import androidx.compose.material.icons.rounded.HourglassTop
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.Videocam
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.kavumahakim.vbd.DownloadJob
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.Engine
import io.github.kavumahakim.vbd.JobStatus
import io.github.kavumahakim.vbd.MediaSaver
import io.github.kavumahakim.vbd.PlayItem
import io.github.kavumahakim.vbd.PlayerConnection
import io.github.kavumahakim.vbd.Tracks
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Ytdlp
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

@Composable
fun DownloadScreen(
    shared: MutableStateFlow<String?>,
    snackbar: SnackbarHostState,
    modifier: Modifier = Modifier,
    onPlaying: () -> Unit = {},
    onOpenSettings: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val settings by SettingsStore.state.collectAsState()
    val jobs by Downloads.jobs.collectAsState()
    val engineStatus by Engine.status.collectAsState()
    val engineFailed by Engine.failed.collectAsState()
    val askNotifications = rememberNotificationAsk()
    var input by rememberSaveable { mutableStateOf("") }
    var reading by remember { mutableStateOf(false) }
    val linkCount = Ytdlp.extractLinks(input).size

    // What is downloading comes first, then what is waiting (in the order it
    // will run), then what has finished, newest first.
    val (finished, open) = remember(jobs) { jobs.partition { it.status.finished } }
    val ordered = remember(open) {
        open.sortedWith(compareBy<DownloadJob> { if (it.status == JobStatus.Queued) 1 else 0 }.thenBy { it.id })
    }
    val done = remember(finished) { finished.sortedByDescending { it.id } }

    fun message(text: String) {
        scope.launch {
            snackbar.currentSnackbarData?.dismiss()
            snackbar.showSnackbar(text)
        }
    }
    fun undoable(text: String, undo: () -> Unit) {
        scope.launch {
            snackbar.currentSnackbarData?.dismiss()
            val result = snackbar.showSnackbar(text, actionLabel = "Undo", duration = SnackbarDuration.Long)
            if (result == SnackbarResult.ActionPerformed) undo()
        }
    }

    // Links shared from another app land in the box, ready to start.
    LaunchedEffect(Unit) {
        shared.collect { text ->
            if (text == null) return@collect
            val links = Ytdlp.extractLinks(text)
            if (links.isEmpty()) snackbar.showSnackbar("No link found in what was shared.")
            else input = (Ytdlp.extractLinks(input) + links).distinct().joinToString("\n")
            shared.value = null
        }
    }

    // Play without downloading: links, playlists and Spotify are read into songs first.
    fun stream() {
        reading = true
        scope.launch {
            try {
                val items = Tracks.fromLinks(input, settings)
                if (items.isEmpty()) {
                    message("Nothing playable in those links.")
                } else {
                    PlayerConnection.play(context, items)
                    input = ""
                    if (items.size > 1) message("Playing ${items.size} songs")
                }
            } catch (e: Exception) {
                message("Couldn't play that: ${e.message}")
            } finally {
                reading = false
            }
        }
    }

    fun start() {
        val count = Downloads.addLinks(input, settings)
        if (count == 0) {
            message("Paste at least one link starting with http.")
        } else {
            input = ""
            askNotifications()
        }
    }

    ScreenScaffold(
        title = "Downloads",
        snackbar = snackbar,
        modifier = modifier,
        large = false,
        actions = {
            IconButton(onClick = onOpenSettings) { Icon(Icons.Rounded.Settings, contentDescription = "Settings") }
        },
        floatingActionButton = {
            AnimatedVisibility(visible = linkCount > 0, enter = scaleIn(), exit = scaleOut()) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    ExtendedFloatingActionButton(
                        onClick = { if (!reading) stream() },
                        icon = {
                            if (reading) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Rounded.PlayArrow, contentDescription = null)
                        },
                        text = { Text(if (reading) "Reading…" else "Play") },
                        containerColor = MaterialTheme.colorScheme.secondaryContainer,
                        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                    ExtendedFloatingActionButton(
                        onClick = { start() },
                        icon = { Icon(Icons.Rounded.Download, contentDescription = null) },
                        text = { Text(if (linkCount == 1) "Download" else "Download $linkCount") },
                    )
                }
            }
        },
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp, top = inner.calculateTopPadding() + 4.dp, bottom = 104.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (engineStatus.isNotEmpty()) {
                item(key = "engine") {
                    EngineBanner(engineStatus, engineFailed, onRetry = { Engine.retry(context) })
                }
            }
            item(key = "input") {
                LinkCard(
                    input = input,
                    onInput = { input = it },
                    linkCount = linkCount,
                    audioOnly = settings.audioOnly,
                    summary = settings.summary,
                    onSummary = onOpenSettings,
                    onPaste = {
                        val pasted = clipboardText(context)
                        if (pasted.isBlank()) message("The clipboard is empty.")
                        else input = if (input.isBlank()) pasted.trim() else input.trimEnd() + "\n" + pasted.trim()
                    },
                )
            }
            if (jobs.isEmpty()) {
                item(key = "empty") {
                    EmptyState(
                        Icons.Rounded.DownloadForOffline,
                        "Nothing in the queue",
                        "Paste links above to play or download them, or share one to this app from YouTube, Spotify or your browser.",
                    )
                }
            } else {
                item(key = "header") {
                    val failed = jobs.count { it.status == JobStatus.Failed || it.status == JobStatus.Cancelled }
                    Row(Modifier.padding(start = 8.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Queue", style = MaterialTheme.typography.titleMedium)
                            Text(
                                if (open.isNotEmpty()) "${open.size} to go" else "All finished",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (failed > 0) TextButton(onClick = Downloads::retryFailed) { Text("Retry failed") }
                        if (open.isNotEmpty()) {
                            TextButton(onClick = {
                                val ids = Downloads.cancelAll()
                                undoable("Cancelled ${ids.size} download${if (ids.size == 1) "" else "s"}") {
                                    Downloads.uncancel(ids)
                                }
                            }) { Text("Cancel all") }
                        } else {
                            TextButton(onClick = {
                                val gone = Downloads.clearFinished()
                                undoable("Cleared ${gone.size} card${if (gone.size == 1) "" else "s"}") {
                                    Downloads.restore(gone)
                                }
                            }) { Text("Clear") }
                        }
                    }
                }
                items(ordered, key = { it.id }) { job ->
                    JobCard(job, Modifier.animateItem(), onOpen = {}, onRemove = {})
                }
                if (done.isNotEmpty()) {
                    if (ordered.isNotEmpty()) {
                        item(key = "finished") {
                            Text(
                                "Finished", style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.animateItem().padding(start = 8.dp, top = 8.dp),
                            )
                        }
                    }
                    items(done, key = { it.id }) { job ->
                        JobCard(
                            job, Modifier.animateItem(),
                            onOpen = { play(context, job, onPlaying) },
                            onRemove = {
                                val gone = Downloads.remove(job.id)
                                undoable("Removed from the list") { Downloads.restore(gone) }
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun EngineBanner(text: String, failed: Boolean, onRetry: () -> Unit) {
    val c = MaterialTheme.colorScheme
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (failed) c.errorContainer else c.tertiaryContainer,
            contentColor = if (failed) c.onErrorContainer else c.onTertiaryContainer,
        ),
    ) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            if (failed) {
                Icon(Icons.Rounded.Error, contentDescription = null, modifier = Modifier.size(20.dp))
            } else {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = c.onTertiaryContainer)
            }
            Spacer(Modifier.width(12.dp))
            Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            if (failed) {
                Spacer(Modifier.width(8.dp))
                FilledTonalButton(onClick = onRetry) { Text("Retry") }
            }
        }
    }
}

@Composable
private fun LinkCard(
    input: String,
    onInput: (String) -> Unit,
    linkCount: Int,
    audioOnly: Boolean,
    summary: String,
    onSummary: () -> Unit,
    onPaste: () -> Unit,
) {
    Card(
        shape = RoundedCornerShape(28.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh),
    ) {
        Column(Modifier.padding(12.dp)) {
            TextField(
                value = input,
                onValueChange = onInput,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Paste links, one per line — videos, playlists, channels, Instagram posts, Spotify…") },
                minLines = 3,
                maxLines = 8,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
            )
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                AssistChip(
                    onClick = onPaste,
                    label = { Text("Paste") },
                    leadingIcon = { Icon(Icons.Rounded.ContentPaste, null, Modifier.size(AssistChipDefaults.IconSize)) },
                )
                if (input.isNotEmpty()) {
                    AssistChip(
                        onClick = { onInput("") },
                        label = { Text("Clear") },
                        leadingIcon = { Icon(Icons.Rounded.Close, null, Modifier.size(AssistChipDefaults.IconSize)) },
                    )
                }
                Spacer(Modifier.weight(1f))
                when {
                    linkCount > 0 -> Text(
                        if (linkCount == 1) "1 link" else "$linkCount links",
                        style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary,
                    )
                    input.isNotBlank() -> Text(
                        "No link yet",
                        style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            if (input.isNotBlank() && linkCount == 0) {
                Text(
                    "Links start with http:// or https:// — copy one with an app's Share button.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(start = 8.dp, top = 4.dp),
                )
            }
            Spacer(Modifier.height(12.dp))
            ModeToggle(audioOnly, Modifier.padding(horizontal = 4.dp))
            AssistChip(
                onClick = onSummary,
                label = { Text(summary) },
                leadingIcon = { Icon(Icons.Rounded.Tune, null, Modifier.size(AssistChipDefaults.IconSize)) },
                border = null,
                modifier = Modifier.padding(start = 4.dp, top = 4.dp),
            )
        }
    }
}

@Composable
private fun JobCard(job: DownloadJob, modifier: Modifier, onOpen: () -> Unit, onRemove: () -> Unit) {
    val failed = job.status == JobStatus.Failed
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row {
                Thumbnail(job.thumbnail, audio = job.settings.audioOnly)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(job.displayTitle, style = MaterialTheme.typography.titleSmall, maxLines = 2,
                        overflow = TextOverflow.Ellipsis)
                    if (job.playlistTitle.isNotEmpty()) {
                        Text(job.playlistTitle, style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Spacer(Modifier.height(8.dp))
                    StatusPill(job)
                }
            }
            when (job.status) {
                JobStatus.Downloading -> {
                    Spacer(Modifier.height(12.dp))
                    LinearProgressIndicator(progress = { job.progress }, modifier = Modifier.fillMaxWidth())
                    val detail = listOfNotNull(
                        job.speed.ifEmpty { null },
                        if (job.etaSeconds > 0) "${Ytdlp.formatDuration(job.etaSeconds.toDouble())} left" else null,
                    ).joinToString(" · ")
                    if (detail.isNotEmpty()) {
                        Text(detail, style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                    }
                }
                JobStatus.Reading, JobStatus.Starting, JobStatus.Processing, JobStatus.Saving -> {
                    Spacer(Modifier.height(12.dp))
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                else -> {}
            }
            val message = when {
                failed -> job.error.ifEmpty { "Failed" }
                job.status == JobStatus.Done -> buildList {
                    add(if (job.files.size > 1) "${job.files.size} files in ${MediaSaver.LOCATION}" else "In ${MediaSaver.LOCATION}")
                    if (job.note.isNotEmpty()) add(job.note)
                }.joinToString("\n")
                else -> ""
            }
            if (message.isNotEmpty()) {
                Text(message, style = MaterialTheme.typography.bodySmall, maxLines = 4, overflow = TextOverflow.Ellipsis,
                    color = if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 10.dp, start = 4.dp))
            }
            Row(
                Modifier.fillMaxWidth().padding(top = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (job.status.finished) {
                    TextButton(onClick = onRemove) {
                        Icon(Icons.Rounded.Delete, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Remove")
                    }
                } else {
                    TextButton(onClick = { Downloads.cancel(job.id) }) { Text("Cancel") }
                }
                when (job.status) {
                    JobStatus.Done -> FilledTonalButton(onClick = onOpen) {
                        Icon(Icons.Rounded.PlayArrow, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Play")
                    }
                    JobStatus.Failed, JobStatus.Cancelled -> FilledTonalButton(onClick = { Downloads.retry(job.id) }) {
                        Icon(Icons.Rounded.Refresh, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Retry")
                    }
                    else -> {}
                }
            }
        }
    }
}

@Composable
private fun StatusPill(job: DownloadJob) {
    val c = MaterialTheme.colorScheme
    data class Look(val text: String, val icon: ImageVector, val bg: Color, val fg: Color)
    val look = when (job.status) {
        JobStatus.Downloading -> Look("${(job.progress * 100).toInt()}%", Icons.Rounded.Download, c.primaryContainer, c.onPrimaryContainer)
        JobStatus.Reading, JobStatus.Starting, JobStatus.Processing, JobStatus.Saving ->
            Look(job.status.label, Icons.Rounded.HourglassTop, c.primaryContainer, c.onPrimaryContainer)
        JobStatus.Queued -> Look("Queued", Icons.Rounded.Schedule, c.surfaceContainerHighest, c.onSurfaceVariant)
        JobStatus.Waiting -> Look("Rate limited · waiting", Icons.Rounded.HourglassTop, c.tertiaryContainer, c.onTertiaryContainer)
        JobStatus.Done -> Look("Saved", Icons.Rounded.CheckCircle, c.secondaryContainer, c.onSecondaryContainer)
        JobStatus.Skipped -> Look("Already downloaded", Icons.Rounded.CheckCircle, c.secondaryContainer, c.onSecondaryContainer)
        JobStatus.Failed -> Look("Failed", Icons.Rounded.Error, c.errorContainer, c.onErrorContainer)
        JobStatus.Cancelled -> Look("Cancelled", Icons.Rounded.Block, c.surfaceContainerHighest, c.onSurfaceVariant)
    }
    Pill(look.text, look.icon, look.bg, look.fg)
}

private fun clipboardText(context: Context): String {
    val clip = context.getSystemService(ClipboardManager::class.java)?.primaryClip ?: return ""
    return (0 until clip.itemCount).joinToString("\n") { clip.getItemAt(it).coerceToText(context).toString() }
}

/** Plays a finished job's files in the app's own player. */
private fun play(context: Context, job: DownloadJob, onPlaying: () -> Unit) {
    val items = job.files.filter { it.mime.startsWith("video/") || it.mime.startsWith("audio/") }.map {
        PlayItem(it.uri, if (job.files.size > 1) it.name.substringBeforeLast('.') else job.displayTitle,
            job.playlistTitle, job.thumbnail, it.mime)
    }
    if (items.isEmpty()) return
    PlayerConnection.play(context, items)
    onPlaying()
}
