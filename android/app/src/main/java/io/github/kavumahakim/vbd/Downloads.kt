package io.github.kavumahakim.vbd

import android.content.Context
import android.os.SystemClock
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

enum class JobStatus(val label: String) {
    Reading("Reading link…"),
    Queued("Queued"),
    Starting("Starting…"),
    Downloading("Downloading"),
    Processing("Processing…"),
    Saving("Saving to Downloads…"),
    Waiting("The site is rate limiting — waiting before trying again"),
    Done("Done"),
    Skipped("Already downloaded"),
    Failed("Failed"),
    Cancelled("Cancelled");

    val finished: Boolean get() = this == Done || this == Skipped || this == Failed || this == Cancelled
}

data class DownloadJob(
    val id: Long,
    val url: String,
    val settings: Settings,
    val title: String = "",
    val playlistTitle: String = "",
    val thumbnail: String = "",
    /** True for links that are read first: Spotify, or a playlist/channel to expand. */
    val needsReading: Boolean = false,
    val status: JobStatus = JobStatus.Queued,
    val progress: Float = 0f,
    val speed: String = "",
    val etaSeconds: Long = -1,
    val error: String = "",
    val note: String = "",
    val files: List<SavedFile> = emptyList(),
) {
    val displayTitle: String get() = title.ifBlank { url.substringAfter("search1:") }
}

/**
 * The download queue. Links are read (Spotify, playlists), queued, and run a
 * few at a time; each job downloads into its own cache folder and its files
 * are then copied into Download/Video Batch Downloader.
 */
object Downloads {
    private lateinit var app: Context
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val ids = AtomicLong(1)
    private val _jobs = MutableStateFlow<List<DownloadJob>>(emptyList())
    val jobs: StateFlow<List<DownloadJob>> = _jobs.asStateFlow()

    private val running = ConcurrentHashMap<Long, Job>()
    private val cancelled: MutableSet<Long> = ConcurrentHashMap.newKeySet()
    private val lastProgress = ConcurrentHashMap<Long, Long>()
    private val lock = Any()

    private val DESTINATION = Regex("^\\[download] Destination: (.+)$")
    private val SPEED = Regex("at\\s+([\\d.]+\\s*[KMGT]?i?B/s)")
    private val PROCESSING = listOf(
        "[Merger]", "[ExtractAudio]", "[EmbedSubtitle]", "[FixupM3u8]", "[FixupM4a]",
        "[VideoConvertor]", "[Metadata]", "[SubtitlesConvertor]",
    )
    private const val NOTE_NO_SUBTITLES = "Subtitles were unavailable — downloaded without them"
    private val RATE_LIMIT_BACKOFF_S = listOf(20L, 60L)

    fun init(context: Context) {
        app = context.applicationContext
    }

    val busy: Boolean get() = _jobs.value.any { !it.status.finished }

    // ------------------------------------------------------------- adding work

    /** Queue every link found in [text]. Returns how many were found. */
    fun addLinks(text: String, settings: Settings): Int {
        val links = Ytdlp.extractLinks(text)
        for (link in links) {
            val reading = Spotify.looksLike(link) || (settings.playlists && Ytdlp.looksLikePlaylist(link))
            val job = DownloadJob(
                ids.getAndIncrement(), link, settings,
                needsReading = reading,
                status = if (reading) JobStatus.Reading else JobStatus.Queued,
            )
            _jobs.update { it + job }
            if (reading) scope.launch { read(job) }
        }
        if (links.isNotEmpty()) kick()
        return links.size
    }

    fun addSearchResults(results: List<SearchResult>, settings: Settings) {
        val jobs = results.map {
            DownloadJob(ids.getAndIncrement(), it.url, settings, title = it.title, thumbnail = it.thumbnail)
        }
        _jobs.update { it + jobs }
        if (jobs.isNotEmpty()) kick()
    }

    private fun kick() {
        DownloadService.start(app)
        pump()
    }

    /** Turn a Spotify link or a playlist/channel into one job per video. */
    private suspend fun read(job: DownloadJob) {
        try {
            Engine.await()
            val replacements = if (Spotify.looksLike(job.url)) {
                val source = job.settings.spotifySource
                val (name, tracks) = Spotify.tracks(job.url, job.settings.playlistLimit)
                tracks.map {
                    DownloadJob(
                        ids.getAndIncrement(), it.searchUrl(source), job.settings,
                        title = it.label, thumbnail = it.artwork,
                        playlistTitle = if (tracks.size > 1) name else "",
                    )
                }
            } else {
                expandPlaylist(job)
            }
            if (job.id in cancelled) return
            _jobs.update { list -> list.flatMap { if (it.id == job.id) replacements else listOf(it) } }
        } catch (e: Exception) {
            val message = when (e) {
                is YoutubeDLException -> Ytdlp.cleanError(e.message.orEmpty())
                else -> e.message ?: e.toString()
            }
            update(job.id) { it.copy(status = JobStatus.Failed, error = message) }
        }
        pump()
    }

    private fun expandPlaylist(job: DownloadJob): List<DownloadJob> {
        val listing = Playlists.read(job.url, job.settings.playlistLimit)
        if (!listing.isPlaylist) {
            // Not a playlist after all: a plain video with a list-looking URL.
            return listOf(job.copy(status = JobStatus.Queued, needsReading = false,
                title = listing.title, thumbnail = bestThumbnail(listing.root)))
        }
        val found = listing.entries
        if (found.isEmpty()) {
            return listOf(job.copy(status = JobStatus.Failed, needsReading = true, error = "That playlist is empty."))
        }
        if (found.size == 1) {
            val only = found.single()
            return listOf(job.copy(url = entryUrl(only), status = JobStatus.Queued, needsReading = false,
                title = only.str("title"), thumbnail = bestThumbnail(only)))
        }
        return found.map {
            DownloadJob(
                ids.getAndIncrement(), entryUrl(it), job.settings,
                title = it.str("title"), thumbnail = bestThumbnail(it), playlistTitle = listing.title,
            )
        }
    }

    // --------------------------------------------------------------- the queue

    private fun pump(): Unit = synchronized(lock) {
        val limit = SettingsStore.current.workers.coerceIn(1, 5)
        while (running.size < limit) {
            val next = _jobs.value.firstOrNull { it.status == JobStatus.Queued && !running.containsKey(it.id) } ?: break
            update(next.id) { it.copy(status = JobStatus.Starting, error = "", progress = 0f) }
            val worker = scope.launch(start = CoroutineStart.LAZY) { run(next.id) }
            running[next.id] = worker
            worker.invokeOnCompletion {
                running.remove(next.id)
                lastProgress.remove(next.id)
                pump()
            }
            worker.start()
        }
    }

    private suspend fun run(id: Long) {
        val job = job(id) ?: return
        val workDir = File(app.cacheDir, "work/$id").apply { deleteRecursively(); mkdirs() }
        var withSubs = job.settings.subtitles && !job.settings.audioOnly
        var rateLimitHits = 0
        var note = ""
        try {
            Engine.await()
            while (true) {
                if (id in cancelled) return
                val request = buildRequest(job, workDir, withSubs)
                try {
                    val response = YoutubeDL.getInstance().execute(request, id.toString()) { progress, eta, line ->
                        onProgress(id, progress, eta, line)
                    }
                    finish(job, workDir, response.out, note)
                    return
                } catch (e: YoutubeDL.CanceledException) {
                    setStatus(id, JobStatus.Cancelled)
                    return
                } catch (e: YoutubeDLException) {
                    if (id in cancelled) return
                    val message = Ytdlp.cleanError(e.message.orEmpty())
                    when {
                        // A missing caption track must never sink a download.
                        withSubs && Ytdlp.SUBTITLE_TROUBLE.containsMatchIn(message) -> {
                            withSubs = false
                            note = NOTE_NO_SUBTITLES
                            workDir.listFiles()?.forEach { it.deleteRecursively() }
                        }
                        Ytdlp.RATE_LIMITED.containsMatchIn(message) && rateLimitHits < RATE_LIMIT_BACKOFF_S.size -> {
                            val wait = RATE_LIMIT_BACKOFF_S[rateLimitHits++]
                            setStatus(id, JobStatus.Waiting)
                            delay(wait * 1000)
                            setStatus(id, JobStatus.Starting)
                        }
                        else -> {
                            update(id) { it.copy(status = JobStatus.Failed, error = message) }
                            return
                        }
                    }
                }
            }
        } catch (e: CancellationException) {
            setStatus(id, JobStatus.Cancelled)
            throw e
        } catch (e: Exception) {
            update(id) { it.copy(status = JobStatus.Failed, error = e.message ?: e.toString()) }
        } finally {
            workDir.deleteRecursively()
        }
    }

    private fun buildRequest(job: DownloadJob, workDir: File, withSubs: Boolean): YoutubeDLRequest {
        val s = job.settings
        val request = YoutubeDLRequest(job.url)
        // A post holding several clips numbers them so they do not overwrite each other.
        request.addOption("-o", File(workDir, "%(title).150B%(playlist_index& - {}|)s.%(ext)s").absolutePath)
        request.addOption("--no-playlist")
        request.addOption("--windows-filenames")
        request.addOption("--no-mtime")
        request.addOption("--retries", 5)
        request.addOption("--fragment-retries", 5)
        // Spacing requests keeps a long batch from being throttled.
        request.addOption("--sleep-requests", "0.75")
        request.addOption("--embed-metadata")
        if (s.audioOnly) {
            request.addOption("-f", "ba/b")
            request.addOption("-x")
            request.addOption("--audio-format", s.audioFormat)
            if (s.audioFormat !in Ytdlp.LOSSLESS_AUDIO) request.addOption("--audio-quality", "${s.audioQuality}K")
        } else {
            // Always H.264 in MP4: streams are only merged, never re-encoded.
            request.addOption("-f", Ytdlp.formatFor(s.quality))
            request.addOption("--merge-output-format", "mp4")
            if (withSubs) {
                request.addOption("--write-subs")
                request.addOption("--write-auto-subs")
                request.addOption("--sub-langs", s.subtitleLangs.split(Regex("[,;\\s]+")).filter { it.isNotEmpty() }
                    .joinToString(",").ifEmpty { "en" })
                request.addOption("--embed-subs")
            }
        }
        if (s.skipExisting) request.addOption("--download-archive", archiveFile(s).absolutePath)
        return request
    }

    /** One history per output kind, so a video already saved can still be fetched as MP3. */
    private fun archiveFile(s: Settings) =
        File(app.filesDir, if (s.audioOnly) "archive-audio-${s.audioFormat}.txt" else "archive-video.txt")

    fun clearHistory() {
        app.filesDir.listFiles { f -> f.name.startsWith("archive-") }?.forEach { it.delete() }
    }

    private fun onProgress(id: Long, progress: Float, eta: Long, line: String) {
        val processing = PROCESSING.any { line.startsWith(it) }
        val destination = DESTINATION.find(line)?.groupValues?.get(1)
        val now = SystemClock.elapsedRealtime()
        if (!processing && destination == null && now - (lastProgress[id] ?: 0L) < 200) return
        lastProgress[id] = now
        update(id) { j ->
            when {
                j.status.finished || id in cancelled -> j
                processing -> j.copy(status = JobStatus.Processing, speed = "", etaSeconds = -1)
                else -> j.copy(
                    status = JobStatus.Downloading,
                    progress = if (progress >= 0) progress / 100f else j.progress,
                    etaSeconds = eta,
                    speed = SPEED.find(line)?.groupValues?.get(1) ?: j.speed,
                    title = j.title.ifBlank { destination?.let(::titleFromPath).orEmpty() },
                )
            }
        }
    }

    private fun titleFromPath(path: String) =
        File(path).nameWithoutExtension.replace(Regex("\\.f\\d+$"), "")

    private fun finish(job: DownloadJob, workDir: File, output: String, note: String) {
        if (job.id in cancelled) return
        val files = workDir.walkTopDown().filter {
            it.isFile && !it.name.endsWith(".part") && !it.name.endsWith(".ytdl") && ".temp." !in it.name
        }.sortedBy { it.name }.toList()
        if (files.isEmpty()) {
            if ("already been recorded in the archive" in output) {
                update(job.id) { it.copy(status = JobStatus.Skipped, progress = 1f) }
            } else {
                update(job.id) { it.copy(status = JobStatus.Failed, error = "yt-dlp finished without producing a file.") }
            }
            return
        }
        setStatus(job.id, JobStatus.Saving)
        val folder = job.playlistTitle.takeIf { job.settings.playlistFolders && it.isNotBlank() }
            ?.let(Ytdlp::safeFolderName)
        val saved = files.map { MediaSaver.save(app, it, folder) }
        update(job.id) {
            it.copy(
                status = JobStatus.Done, progress = 1f, files = saved, note = note, speed = "", etaSeconds = -1,
                title = it.title.ifBlank { files.first().nameWithoutExtension },
            )
        }
    }

    // ------------------------------------------------------------ card actions

    fun cancel(id: Long) {
        val job = job(id) ?: return
        if (job.status.finished) return
        cancelled += id
        setStatus(id, JobStatus.Cancelled)
        YoutubeDL.getInstance().destroyProcessById(id.toString())
        running[id]?.cancel()
    }

    /** Cancels everything unfinished and returns their ids, so the caller can offer Undo. */
    fun cancelAll(): List<Long> {
        val ids = _jobs.value.filter { !it.status.finished }.map { it.id }
        ids.forEach(::cancel)
        return ids
    }

    /** Undo for [cancelAll]: queue those jobs again. */
    fun uncancel(ids: List<Long>) = ids.forEach(::retry)

    fun retry(id: Long) {
        val job = job(id) ?: return
        if (!job.status.finished || job.status == JobStatus.Done) return
        // A cancelled job's process may still be winding down; let it finish
        // first so its last status update cannot land on the fresh attempt.
        val worker = running[id]
        if (worker != null) worker.invokeOnCompletion { scope.launch { retryNow(id) } }
        else retryNow(id)
    }

    private fun retryNow(id: Long) {
        val job = job(id) ?: return
        cancelled -= id
        val fresh = job.copy(
            status = if (job.needsReading) JobStatus.Reading else JobStatus.Queued,
            error = "", note = "", progress = 0f, speed = "", etaSeconds = -1,
        )
        update(id) { fresh }
        if (fresh.needsReading) scope.launch { read(fresh) }
        kick()
    }

    fun retryFailed() = _jobs.value.filter { it.status == JobStatus.Failed || it.status == JobStatus.Cancelled }
        .forEach { retry(it.id) }

    /** Takes a finished card off the list and returns it for Undo. */
    fun remove(id: Long): List<DownloadJob> {
        val gone = _jobs.value.filter { it.id == id && it.status.finished }
        _jobs.update { list -> list.filterNot { j -> gone.any { it.id == j.id } } }
        return gone
    }

    /** Takes every finished card off the list and returns them for Undo. */
    fun clearFinished(): List<DownloadJob> {
        val gone = _jobs.value.filter { it.status.finished }
        _jobs.update { list -> list.filterNot { it.status.finished } }
        return gone
    }

    /** Undo for [remove] and [clearFinished]. */
    fun restore(jobs: List<DownloadJob>) = _jobs.update { list ->
        (list + jobs.filter { j -> list.none { it.id == j.id } }).sortedBy { it.id }
    }

    // ---------------------------------------------------------------- helpers

    private fun job(id: Long) = _jobs.value.firstOrNull { it.id == id }

    private fun update(id: Long, change: (DownloadJob) -> DownloadJob): Unit =
        _jobs.update { list -> list.map { if (it.id == id) change(it) else it } }

    /** Cancelled is final: a late status from a dying process must not overwrite it. */
    private fun setStatus(id: Long, status: JobStatus): Unit = update(id) {
        if (it.status == JobStatus.Cancelled && status != JobStatus.Cancelled) it else it.copy(status = status)
    }
}
