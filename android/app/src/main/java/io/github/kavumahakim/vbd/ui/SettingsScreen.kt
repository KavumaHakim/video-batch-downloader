package io.github.kavumahakim.vbd.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.PlaylistPlay
import androidx.compose.material.icons.rounded.AudioFile
import androidx.compose.material.icons.rounded.Autorenew
import androidx.compose.material.icons.rounded.DoneAll
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.FormatListNumbered
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.HighQuality
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Layers
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.Subtitles
import androidx.compose.material.icons.rounded.SystemUpdate
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import android.text.format.Formatter
import androidx.compose.material.icons.rounded.SignalCellularAlt
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Timer
import androidx.compose.material.icons.rounded.Wifi
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableLongStateOf
import androidx.media3.common.util.UnstableApi
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Radio
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import io.github.kavumahakim.vbd.MusicStore
import io.github.kavumahakim.vbd.MediaCache
import io.github.kavumahakim.vbd.Streams
import io.github.kavumahakim.vbd.BuildConfig
import io.github.kavumahakim.vbd.Downloads
import io.github.kavumahakim.vbd.Engine
import io.github.kavumahakim.vbd.MediaSaver
import io.github.kavumahakim.vbd.Settings
import io.github.kavumahakim.vbd.SettingsStore
import io.github.kavumahakim.vbd.Ytdlp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(UnstableApi::class)
@Composable
fun SettingsScreen(snackbar: SnackbarHostState, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val s by SettingsStore.state.collectAsState()
    val version by Engine.version.collectAsState()
    val jobs by Downloads.jobs.collectAsState()
    var updating by remember { mutableStateOf(false) }
    val lookupMs by Streams.lastLookupMs.collectAsState()
    var cacheBytes by remember { mutableLongStateOf(0L) }
    LaunchedEffect(Unit) { cacheBytes = withContext(Dispatchers.IO) { runCatching { MediaCache.sizeBytes(context) }.getOrDefault(0L) } }
    fun set(change: (Settings) -> Settings) = SettingsStore.update(change)
    fun say(text: String) { scope.launch { snackbar.showSnackbar(text) } }
    val fieldModifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 12.dp)

    ScreenScaffold(
        title = "Settings", snackbar = snackbar, modifier = modifier,
        navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, "Back") } },
    ) { inner ->
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(top = inner.calculateTopPadding(), bottom = 24.dp),
        ) {
            SettingsGroup("Video") {
                ChoiceRow(
                    Icons.Rounded.HighQuality, "Quality",
                    options = Ytdlp.QUALITIES.map { it to it },
                    value = s.quality,
                    onChange = { q -> set { it.copy(quality = q) } },
                    hint = "H.264 MP4, plays everywhere",
                )
            }

            SettingsGroup("Audio") {
                ChoiceRow(
                    Icons.Rounded.AudioFile, "Format",
                    options = Ytdlp.AUDIO_FORMATS.map { it to it.uppercase() },
                    value = s.audioFormat,
                    onChange = { f -> set { it.copy(audioFormat = f) } },
                )
                ChoiceRow(
                    Icons.Rounded.GraphicEq, "Bitrate",
                    options = Ytdlp.AUDIO_QUALITIES.map { it to "$it kbps" },
                    value = s.audioQuality,
                    onChange = { q -> set { it.copy(audioQuality = q) } },
                    enabled = s.audioFormat !in Ytdlp.LOSSLESS_AUDIO,
                    hint = if (s.audioFormat in Ytdlp.LOSSLESS_AUDIO) "not used for lossless" else null,
                )
            }

            SettingsGroup("Subtitles") {
                SwitchRow(Icons.Rounded.Subtitles, "Embed subtitles", "Skipped quietly when a video has none",
                    s.subtitles) { v -> set { it.copy(subtitles = v) } }
                if (s.subtitles) {
                    var langs by remember { mutableStateOf(s.subtitleLangs) }
                    OutlinedTextField(
                        value = langs,
                        onValueChange = { langs = it; set { st -> st.copy(subtitleLangs = it) } },
                        label = { Text("Languages, e.g. en, fr — or all") },
                        singleLine = true,
                        shape = RoundedCornerShape(16.dp),
                        modifier = fieldModifier,
                    )
                }
            }

            SettingsGroup("Playlists and channels") {
                SwitchRow(Icons.AutoMirrored.Rounded.PlaylistPlay, "One card per video",
                    "Off downloads a whole playlist as a single card",
                    s.playlists) { v -> set { it.copy(playlists = v) } }
                SwitchRow(Icons.Rounded.Folder, "A folder for each playlist", null,
                    s.playlistFolders) { v -> set { it.copy(playlistFolders = v) } }
                NumberRow(
                    Icons.Rounded.FormatListNumbered, "Videos per playlist",
                    value = s.playlistLimit,
                    zeroLabel = "All of them",
                    hint = "Leave empty to take every video",
                    onChange = { n -> set { it.copy(playlistLimit = n) } },
                )
            }

            SettingsGroup("Spotify") {
                ChoiceRow(
                    Icons.Rounded.LibraryMusic, "Find tracks on",
                    options = Ytdlp.SPOTIFY_SOURCES,
                    value = s.spotifySource,
                    onChange = { src -> set { it.copy(spotifySource = src) } },
                    hint = "Spotify's own audio is protected",
                )
            }

            SettingsGroup("Downloads") {
                SettingRow(Icons.Rounded.Layers, "At the same time", "${s.workers} downloads")
                Slider(
                    value = s.workers.toFloat(),
                    onValueChange = { v -> set { it.copy(workers = v.toInt()) } },
                    valueRange = 1f..5f,
                    steps = 3,
                    modifier = Modifier.padding(horizontal = 24.dp),
                )
                SwitchRow(Icons.Rounded.DoneAll, "Skip what's already downloaded",
                    "Remembers what this app has saved before",
                    s.skipExisting) { v -> set { it.copy(skipExisting = v) } }
                SettingRow(Icons.Rounded.History, "Forget download history",
                    "Lets everything be downloaded again",
                    onClick = { Downloads.clearHistory(); say("Download history cleared.") })
                SettingRow(Icons.Rounded.FolderOpen, "Saved to", MediaSaver.LOCATION)
            }

            SettingsGroup("Streaming") {
                SwitchRow(Icons.Rounded.Radio, "Autoplay", "When the queue runs out, keep going with similar songs",
                    s.autoplay) { v -> set { it.copy(autoplay = v) } }
                SettingRow(Icons.Rounded.History, "Clear listening history",
                    "Resets Recently played, Quick picks and Mixes on Home",
                    onClick = { MusicStore.clearHistory(); say("Listening history cleared.") })
                val qualities = Streams.Quality.entries.map { it.name to it.label }
                ChoiceRow(
                    Icons.Rounded.Wifi, "Quality on Wi-Fi",
                    options = qualities,
                    value = s.streamQualityWifi,
                    onChange = { q -> set { it.copy(streamQualityWifi = q) } },
                )
                ChoiceRow(
                    Icons.Rounded.SignalCellularAlt, "Quality on mobile data",
                    options = qualities,
                    value = s.streamQualityMobile,
                    onChange = { q -> set { it.copy(streamQualityMobile = q) } },
                )
                SettingRow(
                    Icons.Rounded.Timer, "Last song lookup",
                    when {
                        lookupMs < 0 -> "Nothing streamed yet"
                        else -> "Took %.1f seconds".format(lookupMs / 1000.0)
                    },
                )
                SettingRow(
                    Icons.Rounded.Storage, "Clear listening cache",
                    "${Formatter.formatShortFileSize(context, cacheBytes)} of songs kept so replays use no data",
                    onClick = {
                        scope.launch {
                            withContext(Dispatchers.IO) { MediaCache.clear(context) }
                            cacheBytes = 0
                            say("Listening cache cleared.")
                        }
                    },
                )
            }

            SettingsGroup("yt-dlp") {
                SwitchRow(Icons.Rounded.Autorenew, "Keep yt-dlp up to date", "Checks once a day when the app starts",
                    s.autoUpdate) { v -> set { it.copy(autoUpdate = v) } }
                val busy = jobs.any { !it.status.finished }
                val versionLine = when {
                    version.isEmpty() -> "Starting…"
                    busy -> "$version · finish or cancel downloads to update"
                    else -> version
                }
                SettingRow(Icons.Rounded.SystemUpdate, "Version", versionLine) {
                    FilledTonalButton(
                        enabled = !updating && !busy && version.isNotEmpty(),
                        onClick = {
                            updating = true
                            scope.launch {
                                val result = withContext(Dispatchers.IO) { Engine.updateNow(context) }
                                updating = false
                                say(result)
                            }
                        },
                    ) { Text(if (updating) "Updating…" else "Update") }
                }
            }

            SettingsGroup("About") {
                SettingRow(Icons.Rounded.Info, "Video Batch Downloader ${BuildConfig.VERSION_NAME}",
                    "Downloads with yt-dlp and FFmpeg")
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
