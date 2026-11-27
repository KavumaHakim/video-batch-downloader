package io.github.kavumahakim.vbd

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.LibraryMusic
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.graphics.vector.ImageVector
import io.github.kavumahakim.vbd.ui.DownloadScreen
import io.github.kavumahakim.vbd.ui.HomeScreen
import io.github.kavumahakim.vbd.ui.PlaylistScreen
import io.github.kavumahakim.vbd.ui.LibraryScreen
import io.github.kavumahakim.vbd.ui.MiniPlayer
import io.github.kavumahakim.vbd.ui.PlayerScreen
import io.github.kavumahakim.vbd.ui.SearchScreen
import io.github.kavumahakim.vbd.ui.SettingsScreen
import io.github.kavumahakim.vbd.ui.VbdTheme
import io.github.kavumahakim.vbd.ui.rememberPlayerUi
import kotlinx.coroutines.flow.MutableStateFlow

class MainActivity : ComponentActivity() {
    /** Text shared into the app ("Share → Video Batch Downloader"), waiting to be picked up. */
    private val shared = MutableStateFlow<String?>(null)
    /** Set when the media notification is tapped: show the player. */
    private val openPlayer = MutableStateFlow(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) handle(intent)
        setContent {
            VbdTheme {
                AppRoot(shared, openPlayer)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        PlayerConnection.connect(this)
    }

    override fun onStop() {
        super.onStop()
        // Playback carries on in PlaybackService; only the UI's handle goes.
        if (!isChangingConfigurations) PlayerConnection.disconnect()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)?.let { shared.value = it }
        }
        if (intent?.getBooleanExtra(EXTRA_OPEN_PLAYER, false) == true) openPlayer.value = true
    }
}

private enum class Tab(val label: String, val selectedIcon: ImageVector, val icon: ImageVector) {
    Home("Home", Icons.Rounded.Home, Icons.Outlined.Home),
    Search("Search", Icons.Rounded.Search, Icons.Outlined.Search),
    Library("Library", Icons.Rounded.LibraryMusic, Icons.Outlined.LibraryMusic),
    Downloads("Downloads", Icons.Rounded.Download, Icons.Outlined.Download),
}

/** A page shown over a tab: Settings, or one playlist. */
private const val PAGE_SETTINGS = "settings"
private const val PAGE_PLAYLIST = "playlist:"

@Composable
private fun AppRoot(shared: MutableStateFlow<String?>, openPlayer: MutableStateFlow<Boolean>) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var page by rememberSaveable { mutableStateOf<String?>(null) }
    var playerOpen by rememberSaveable { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    val player by PlayerConnection.controller.collectAsState()
    val ui = rememberPlayerUi(player)

    // Android 9 and older need storage access before anything can be saved.
    // (Notifications are asked for on the first download, where the reason is clear.)
    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {}
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            permissions.launch(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE))
        }
    }
    // Back closes a page first, then goes to Home, and only leaves the app from there.
    BackHandler(enabled = page == PAGE_SETTINGS && !playerOpen) { page = null }
    BackHandler(enabled = page == null && tab != Tab.Home.ordinal && !playerOpen) { tab = Tab.Home.ordinal }
    LaunchedEffect(Unit) {
        shared.collect { if (it != null) { tab = Tab.Downloads.ordinal; page = null; playerOpen = false } }
    }
    LaunchedEffect(Unit) {
        openPlayer.collect { if (it) { playerOpen = true; openPlayer.value = false } }
    }
    LaunchedEffect(ui.hasMedia) { if (!ui.hasMedia && player != null) playerOpen = false }

    Box(Modifier.fillMaxSize()) {
        Scaffold(
            bottomBar = {
                Column {
                    MiniPlayer(player, ui, onOpen = { playerOpen = true })
                    NavigationBar {
                        Tab.entries.forEach { t ->
                            NavigationBarItem(
                                selected = tab == t.ordinal && page == null,
                                onClick = { tab = t.ordinal; page = null },
                                icon = { Icon(if (tab == t.ordinal) t.selectedIcon else t.icon, contentDescription = null) },
                                label = { Text(t.label) },
                            )
                        }
                    }
                }
            },
        ) { padding ->
            // Each screen draws its own title bar under the status bar, so the
            // top inset is left to it; the sides matter on a phone held sideways.
            val direction = LocalLayoutDirection.current
            val modifier = Modifier.padding(
                start = padding.calculateStartPadding(direction),
                end = padding.calculateEndPadding(direction),
                bottom = padding.calculateBottomPadding(),
            )
            val openSettings = { page = PAGE_SETTINGS }
            val openPlaylist = { id: String -> page = PAGE_PLAYLIST + id }
            val openPlayerNow = { playerOpen = true }
            val current = page
            when {
                current == PAGE_SETTINGS -> SettingsScreen(snackbar, onBack = { page = null }, modifier = modifier)
                current != null && current.startsWith(PAGE_PLAYLIST) ->
                    PlaylistScreen(current.removePrefix(PAGE_PLAYLIST), snackbar, onBack = { page = null }, modifier = modifier)
                else -> when (Tab.entries[tab]) {
                    Tab.Home -> HomeScreen(
                        snackbar, hasMedia = ui.hasMedia,
                        onOpenSettings = openSettings,
                        onOpenSearch = { tab = Tab.Search.ordinal },
                        onOpenPlaylist = openPlaylist,
                        onPlaying = openPlayerNow,
                        modifier = modifier,
                    )
                    Tab.Search -> SearchScreen(snackbar, onQueued = { tab = Tab.Downloads.ordinal }, modifier = modifier)
                    Tab.Library -> LibraryScreen(
                        snackbar, onPlaying = openPlayerNow, onOpenPlaylist = openPlaylist,
                        onOpenSettings = openSettings, modifier = modifier,
                    )
                    Tab.Downloads -> DownloadScreen(
                        shared, snackbar, modifier,
                        onPlaying = openPlayerNow,
                        onOpenSettings = openSettings,
                    )
                }
            }
        }
        AnimatedVisibility(
            visible = playerOpen && player != null && ui.hasMedia,
            enter = slideInVertically { it },
            exit = slideOutVertically { it },
        ) {
            player?.let { PlayerScreen(it, ui, onClose = { playerOpen = false }) }
        }
    }
}
