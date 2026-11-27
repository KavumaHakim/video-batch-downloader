package io.github.kavumahakim.vbd

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Everything the Settings screen controls. A copy is taken for each job when it is queued. */
data class Settings(
    val audioOnly: Boolean = false,
    val quality: String = "Best available",
    val audioFormat: String = "mp3",
    val audioQuality: String = "192",
    val subtitles: Boolean = false,
    val subtitleLangs: String = "en",
    val playlists: Boolean = true,
    val playlistLimit: Int = 0,
    val playlistFolders: Boolean = true,
    val skipExisting: Boolean = true,
    val workers: Int = 2,
    val spotifySource: String = "ytsearch",
    val searchSite: String = "ytmusic",
    val autoUpdate: Boolean = true,
    /** Streams.Quality names: what to stream on Wi-Fi and on mobile data. */
    val streamQualityWifi: String = "Normal",
    val streamQualityMobile: String = "DataSaver",
    /** When the queue runs out, keep going with songs like the last one. */
    val autoplay: Boolean = true,
) {
    /** One line describing what Start download will produce, e.g. "MP4 · H.264 · 1080p". */
    val summary: String
        get() = if (audioOnly) {
            val bitrate = if (audioFormat in Ytdlp.LOSSLESS_AUDIO) "lossless" else "$audioQuality kbps"
            "${audioFormat.uppercase()} · $bitrate"
        } else {
            "MP4 · H.264 · $quality"
        }
}

object SettingsStore {
    private lateinit var prefs: SharedPreferences
    private val _state = MutableStateFlow(Settings())
    val state: StateFlow<Settings> = _state.asStateFlow()
    val current: Settings get() = _state.value

    fun init(context: Context) {
        prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
        val d = Settings()
        _state.value = Settings(
            audioOnly = prefs.getBoolean("audioOnly", d.audioOnly),
            // Older builds offered 1440p/2160p; H.264 tops out at 1080p.
            quality = (prefs.getString("quality", d.quality) ?: d.quality)
                .takeIf { it in Ytdlp.QUALITIES } ?: d.quality,
            audioFormat = prefs.getString("audioFormat", d.audioFormat) ?: d.audioFormat,
            audioQuality = prefs.getString("audioQuality", d.audioQuality) ?: d.audioQuality,
            subtitles = prefs.getBoolean("subtitles", d.subtitles),
            subtitleLangs = prefs.getString("subtitleLangs", d.subtitleLangs) ?: d.subtitleLangs,
            playlists = prefs.getBoolean("playlists", d.playlists),
            playlistLimit = prefs.getInt("playlistLimit", d.playlistLimit),
            playlistFolders = prefs.getBoolean("playlistFolders", d.playlistFolders),
            skipExisting = prefs.getBoolean("skipExisting", d.skipExisting),
            workers = prefs.getInt("workers", d.workers),
            spotifySource = prefs.getString("spotifySource", d.spotifySource) ?: d.spotifySource,
            searchSite = prefs.getString("searchSite", d.searchSite) ?: d.searchSite,
            autoUpdate = prefs.getBoolean("autoUpdate", d.autoUpdate),
            streamQualityWifi = prefs.getString("streamQualityWifi", d.streamQualityWifi) ?: d.streamQualityWifi,
            streamQualityMobile = prefs.getString("streamQualityMobile", d.streamQualityMobile) ?: d.streamQualityMobile,
            autoplay = prefs.getBoolean("autoplay", d.autoplay),
        )
    }

    fun update(change: (Settings) -> Settings) {
        val s = change(_state.value)
        _state.value = s
        prefs.edit()
            .putBoolean("audioOnly", s.audioOnly)
            .putString("quality", s.quality)
            .putString("audioFormat", s.audioFormat)
            .putString("audioQuality", s.audioQuality)
            .putBoolean("subtitles", s.subtitles)
            .putString("subtitleLangs", s.subtitleLangs)
            .putBoolean("playlists", s.playlists)
            .putInt("playlistLimit", s.playlistLimit)
            .putBoolean("playlistFolders", s.playlistFolders)
            .putBoolean("skipExisting", s.skipExisting)
            .putInt("workers", s.workers)
            .putString("spotifySource", s.spotifySource)
            .putString("searchSite", s.searchSite)
            .putBoolean("autoUpdate", s.autoUpdate)
            .putString("streamQualityWifi", s.streamQualityWifi)
            .putString("streamQualityMobile", s.streamQualityMobile)
            .putBoolean("autoplay", s.autoplay)
            .apply()
    }
}
