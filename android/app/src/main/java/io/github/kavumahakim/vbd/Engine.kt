package io.github.kavumahakim.vbd

import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.concurrent.thread

/**
 * Unpacks the bundled Python, yt-dlp and FFmpeg on first launch, and keeps
 * yt-dlp current: sites change often, and an old yt-dlp is the usual reason
 * downloads start failing.
 */
object Engine {
    @Volatile private var ready = CompletableDeferred<Unit>()
    private val _status = MutableStateFlow("Starting yt-dlp…")
    private val _version = MutableStateFlow("")
    private val _failed = MutableStateFlow(false)

    /** A line for the UI while the engine is busy or broken; "" when all is well. */
    val status: StateFlow<String> = _status.asStateFlow()
    val version: StateFlow<String> = _version.asStateFlow()
    /** True when starting failed; the UI then offers [retry] instead of a spinner. */
    val failed: StateFlow<Boolean> = _failed.asStateFlow()

    private const val UPDATE_EVERY_MS = 24L * 60 * 60 * 1000

    fun start(context: Context) {
        val app = context.applicationContext
        val deferred = ready
        _failed.value = false
        _status.value = "Starting yt-dlp…"
        thread(name = "engine-init") {
            try {
                YoutubeDL.getInstance().init(app)
                FFmpeg.getInstance().init(app)
                if (SettingsStore.current.autoUpdate) autoUpdate(app)
                _version.value = YoutubeDL.getInstance().version(app).orEmpty()
                _status.value = ""
                deferred.complete(Unit)
            } catch (e: Throwable) {
                _status.value = "Could not start yt-dlp: ${e.message}"
                _failed.value = true
                deferred.completeExceptionally(e)
            }
        }
    }

    suspend fun await() = ready.await()

    /** Try starting again after a failure (often a full disk on first launch). */
    fun retry(context: Context) {
        if (!_failed.value) return
        ready = CompletableDeferred()
        start(context)
    }

    /** Checks at most once a day; no network just means trying again next launch. */
    private fun autoUpdate(app: Context) {
        val prefs = app.getSharedPreferences("engine", Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now - prefs.getLong("lastUpdateCheck", 0) < UPDATE_EVERY_MS) return
        _status.value = "Checking for a newer yt-dlp…"
        try {
            YoutubeDL.getInstance().updateYoutubeDL(app, YoutubeDL.UpdateChannel._STABLE)
            prefs.edit().putLong("lastUpdateCheck", now).apply()
        } catch (_: Exception) {
        }
    }

    /** Settings → Update now. Blocking; returns a message for the user. */
    fun updateNow(context: Context): String {
        val app = context.applicationContext
        return try {
            val result = YoutubeDL.getInstance().updateYoutubeDL(app, YoutubeDL.UpdateChannel._STABLE)
            _version.value = YoutubeDL.getInstance().version(app).orEmpty()
            app.getSharedPreferences("engine", Context.MODE_PRIVATE).edit()
                .putLong("lastUpdateCheck", System.currentTimeMillis()).apply()
            if (result == YoutubeDL.UpdateStatus.ALREADY_UP_TO_DATE) "yt-dlp is already up to date."
            else "Updated yt-dlp to ${_version.value}."
        } catch (e: Exception) {
            "Update failed: ${e.message}"
        }
    }
}
