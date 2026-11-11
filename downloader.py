"""Background download service for the Video Batch Downloader GUI."""

from __future__ import annotations

import itertools
import logging
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Iterable, Optional

YT_DLP_IMPORT_ERROR = ""
try:
    import yt_dlp
except Exception as _exc:  # The GUI shows the reason instead of a bare "missing".
    yt_dlp = None  # type: ignore[assignment]
    YT_DLP_IMPORT_ERROR = f"{_exc.__class__.__name__}: {_exc}"


@dataclass
class DownloadJob:
    job_id: int
    url: str
    title: str = ""
    status: str = "Queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    output_path: str = ""
    error: str = ""
    note: str = ""              # Non-fatal remark, e.g. subtitles were unavailable
    playlist_title: str = ""    # Set when the job came out of an expanded playlist
    playlist_url: str = ""
    playlist_index: int = 0
    media_count: int = 0        # >1 for a post holding several photos or clips


# Codec -> container extension yt-dlp writes after FFmpegExtractAudio.
AUDIO_FORMATS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "wav": "wav", "flac": "flac"}
LOSSLESS_AUDIO = {"wav", "flac"}

# DownloadConfig.subtitle_mode values ("" leaves subtitles alone).
EMBED_SUBTITLE_MODES = {"embed", "both"}
KEEP_SUBTITLE_MODES = {"file", "both"}
DEFAULT_SUBTITLE_LANGS = "en"

# A missing caption track must never sink a download, so a failure that mentions
# subtitles is retried with subtitles turned off instead of being reported.
SUBTITLE_TROUBLE = re.compile(r"subtitle|caption|\.srt|\.vtt", re.IGNORECASE)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
NOTE_NO_SUBTITLES = "Subtitles were unavailable - downloaded without them"

# URLs worth probing for a playlist. A false positive only costs one extraction
# that comes back as a single video, so these lean towards catching too much.
PLAYLIST_URL_HINTS = re.compile(
    r"[?&](?:list|playlist|album|set)=|/playlists?(?:/|$|\?)|/sets/|/albums?/"
    r"|/channels?/|/users?/|/c/|/@|/videos(?:/|$|\?)|/streams(?:/|$|\?)"
    r"|/shows?/|/series/|/collections?/|/podcasts?/",
    re.IGNORECASE,
)


def subtitle_languages(raw: str) -> list[str]:
    """Split a user-typed language list ("en, es" or "all") into yt-dlp codes."""
    langs = [part for part in re.split(r"[,;\s]+", raw.strip()) if part]
    return langs or [DEFAULT_SUBTITLE_LANGS]


def clean_error(message: Any) -> str:
    """Strip yt-dlp's ANSI colouring and its ERROR: prefix from a message."""
    text = ANSI_ESCAPE.sub("", str(message)).strip()
    return re.sub(r"^ERROR:\s*", "", text).strip()


@dataclass
class DownloadConfig:
    output_dir: Path
    quality: str = "Best available"
    mode: str = "Parallel"
    workers: int = 3
    skip_existing: bool = True
    ffmpeg_path: str = ""
    audio_format: str = ""       # "" = video; otherwise an AUDIO_FORMATS key
    audio_quality: str = "192"   # kbps, ignored for lossless codecs
    subtitle_mode: str = ""      # "" = none; "file", "embed" or "both"
    subtitle_langs: str = DEFAULT_SUBTITLE_LANGS
    subtitle_auto: bool = True   # also accept machine-generated captions
    playlists: bool = True       # expand playlist/channel links into their videos
    playlist_limit: int = 0      # videos taken per playlist; 0 = every one
    playlist_folders: bool = True  # save each playlist into its own subfolder

    @property
    def audio_only(self) -> bool:
        return bool(self.audio_format)

    @property
    def wants_subtitles(self) -> bool:
        # Subtitles only make sense for the video pipeline; an audio file has
        # nowhere to put them and the sidecar files would be orphans.
        return bool(self.subtitle_mode) and not self.audio_only

    @property
    def embeds_subtitles(self) -> bool:
        return self.wants_subtitles and self.subtitle_mode in EMBED_SUBTITLE_MODES

    @property
    def target_ext(self) -> str:
        return AUDIO_FORMATS.get(self.audio_format, "mp4") if self.audio_only else "mp4"


# --------------------------------------------------------------------- playlists
@dataclass
class PlaylistEntry:
    url: str
    title: str = ""
    playlist_title: str = ""
    playlist_url: str = ""
    playlist_index: int = 0


def looks_like_playlist(url: str) -> bool:
    """Cheap pre-check so plain video links are not probed over the network."""
    return bool(PLAYLIST_URL_HINTS.search(url))


def is_search_query(url: str) -> bool:
    """True for a yt-dlp search target such as ytsearch1:daft punk one more time.

    Spotify links are queued this way: the track name is known, the video that
    holds it is whatever the search turns up.
    """
    return bool(re.match(r"^[a-z]{2,12}search\d*:", url.strip(), re.IGNORECASE))


def safe_folder_name(name: str) -> str:
    """A playlist title trimmed down to something Windows accepts as a folder."""
    cleaned = re.sub(r"[<>:\"/\\|?*]", " ", name)
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:120] or "Playlist"


def _entry_url(entry: dict[str, Any]) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    return ""


def _flatten(entries: Iterable[Any], depth: int = 0) -> list[dict[str, Any]]:
    """Walk nested playlist results (a channel yields one playlist per tab)."""
    flat: list[dict[str, Any]] = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        nested = entry.get("entries")
        if nested and depth < 3:
            flat.extend(_flatten(nested, depth + 1))
        else:
            flat.append(entry)
    return flat


def expand_playlist(
    url: str,
    logger: logging.Logger,
    limit: int = 0,
    cancel: Optional[threading.Event] = None,
) -> list[PlaylistEntry]:
    """Return the videos behind a playlist/channel URL, or [] if it is not one.

    Only titles and URLs are fetched (a flat extraction), so a 300-video
    playlist resolves in a couple of requests instead of 300.
    """
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed. Run: pip install -r requirements.txt")
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "color": "no_color",
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": False,
        "ignoreerrors": True,     # one dead entry must not cost us the rest
        "logger": logger,
    }
    if limit > 0:
        options["playlistend"] = limit
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get("_type") != "playlist":
        return []

    playlist_title = str(info.get("title") or info.get("id") or "Playlist")
    playlist_url = str(info.get("webpage_url") or url)
    entries: list[PlaylistEntry] = []
    seen: set[str] = set()
    for position, entry in enumerate(_flatten(info.get("entries")), 1):
        if cancel is not None and cancel.is_set():
            break
        entry_url = _entry_url(entry)
        if not entry_url or entry_url in seen:
            continue
        seen.add(entry_url)
        entries.append(PlaylistEntry(
            url=entry_url,
            title=str(entry.get("title") or ""),
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            playlist_index=int(entry.get("playlist_index") or position),
        ))
        if limit > 0 and len(entries) >= limit:
            break
    return entries


class DownloadManager:
    """Runs yt-dlp jobs off the GUI thread and emits plain dictionaries."""

    def __init__(self, event_queue: Queue[dict[str, Any]], logger: logging.Logger) -> None:
        self.event_queue = event_queue
        self.logger = logger
        self.cancel_event = threading.Event()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: list[Future[None]] = []
        self._lock = threading.Lock()
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, jobs: list[DownloadJob], config: DownloadConfig) -> None:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp is not installed. Run: pip install -r requirements.txt")
        if self.active:
            raise RuntimeError("A download batch is already running.")
        if config.audio_only and not find_ffmpeg(config.ffmpeg_path):
            raise RuntimeError(
                f"Converting to {config.audio_format.upper()} needs FFmpeg, which was not found. "
                "Install FFmpeg and put it on PATH, or set the FFmpeg path in Settings."
            )
        if config.embeds_subtitles and not find_ffmpeg(config.ffmpeg_path):
            raise RuntimeError(
                "Embedding subtitles needs FFmpeg, which was not found. Install FFmpeg and put it "
                "on PATH, set the FFmpeg path in Settings, or save subtitles as separate files."
            )

        config.output_dir.mkdir(parents=True, exist_ok=True)
        self.cancel_event.clear()
        with self._lock:
            self._active = True
        max_workers = 1 if config.mode == "Sequential" else max(1, min(config.workers, 5))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="yt-dlp")
        self._futures = [self._executor.submit(self._download_one, job, config) for job in jobs]
        threading.Thread(target=self._wait_for_batch, daemon=True).start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self._emit({"type": "batch_status", "status": "Cancelling"})

    def _wait_for_batch(self) -> None:
        for future in self._futures:
            try:
                future.result()
            except Exception:  # Defensive: each job should report its own failure.
                self.logger.exception("Unexpected worker failure")
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        self._executor = None
        with self._lock:
            self._active = False
        self._emit({"type": "batch_complete"})

    def _download_one(self, job: DownloadJob, config: DownloadConfig) -> None:
        if self.cancel_event.is_set():
            self._status(job, "Cancelled")
            return

        self._status(job, "Downloading")
        self.logger.info("Starting: %s | %s", job.url, job.title or "untitled")
        # Captions are a nice-to-have: try with them, and when they are what
        # broke, fall back to a plain download instead of failing the video.
        attempts = [True, False] if config.wants_subtitles else [False]
        for index, with_subtitles in enumerate(attempts):
            retry_left = index + 1 < len(attempts)
            state: dict[str, Any] = {"media_done": False}
            try:
                outcome = self._attempt(job, config, with_subtitles, state)
            except Exception as exc:
                if self.cancel_event.is_set():
                    self._status(job, "Cancelled")
                    return
                message = clean_error(exc) or exc.__class__.__name__
                # Either the message blames subtitles, or the video itself had
                # already arrived and only the caption step afterwards broke.
                if retry_left and (state["media_done"] or SUBTITLE_TROUBLE.search(message)):
                    job.note = NOTE_NO_SUBTITLES
                    self.logger.warning(
                        "Subtitles failed for %s, retrying without them: %s", job.url, message)
                    continue
                job.error = message
                self._status(job, "Failed", error=message)
                self.logger.error("Failed: %s | %s", job.url, message)
                return
            if self.cancel_event.is_set():
                self._status(job, "Cancelled")
                return
            if outcome == "skipped" and index == 0:
                self._status(job, "Skipped")
                self.logger.info("Skipped existing file: %s", job.url)
                return
            # A skip on the retry means the first pass had already written the
            # file before the caption step tripped, so it really did complete.
            self._status(job, "Completed")
            self.logger.info("Completed: %s | %s%s", job.url, job.output_path,
                             f" ({job.note})" if job.note else "")
            return

    def _attempt(
        self,
        job: DownloadJob,
        config: DownloadConfig,
        with_subtitles: bool,
        state: dict[str, Any],
    ) -> str:
        """Run one download pass; returns completed, skipped or cancelled."""
        target_dir = self._job_dir(job, config)
        target_dir.mkdir(parents=True, exist_ok=True)
        options = self._options(job, config, target_dir, with_subtitles, state)
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(job.url, download=False)
            head = self._first_entries(info)
            # A search target resolves to one hit, which is the video itself.
            item = head[0] if len(head) == 1 else info
            if item and item.get("title"):
                job.title = str(item["title"])
                self._emit({"type": "metadata", "job_id": job.job_id, "title": job.title})
            if len(head) > 1:
                self._prepare_multi(job, ydl, config, info, head, target_dir)
            elif config.skip_existing and self._existing_output(ydl, item, config, target_dir):
                job.output_path = str(self._prepared_path(ydl, item, target_dir, config.target_ext))
                return "skipped"
            if self.cancel_event.is_set():
                return "cancelled"
            if with_subtitles:
                # ydl.params is the very dict we passed in, so editing it here
                # still reaches the download that follows.
                self._narrow_subtitle_langs(ydl.params, item)
            ydl.download([job.url])
        return "completed"

    @staticmethod
    def _first_entries(info: Optional[dict[str, Any]], count: int = 2) -> list[dict[str, Any]]:
        """Peek at the head of a playlist result without extracting all of it.

        yt-dlp hands back a lazy list for a long playlist, so taking its length
        would extract every entry. Two are enough to tell a single item from
        several, and several photos of one post from separate videos.
        """
        if not info or info.get("_type") != "playlist":
            return []
        entries = info.get("entries") or ()
        return [entry for entry in itertools.islice(iter(entries), count) if isinstance(entry, dict)]

    @staticmethod
    def _one_post(entries: list[dict[str, Any]]) -> bool:
        """True when the items belong to one post rather than being separate videos.

        An Instagram carousel reports every photo and clip under the post's own
        URL and title; a playlist's entries each have a page of their own.
        """
        urls = {_entry_url(entry) for entry in entries}
        urls.discard("")
        return len(urls) <= 1

    def _prepare_multi(
        self,
        job: DownloadJob,
        ydl: Any,
        config: DownloadConfig,
        info: dict[str, Any],
        head: list[dict[str, Any]],
        target_dir: Path,
    ) -> None:
        """Set a link that holds several media up to write one file per item."""
        if not self._one_post(head):
            # A playlist that was never expanded into its own rows; leave the
            # naming alone and let each video keep its title.
            return
        entries = info.get("entries")
        job.media_count = len(entries) if isinstance(entries, (list, tuple)) else len(head)
        self._emit({"type": "media_count", "job_id": job.job_id, "count": job.media_count})
        self.logger.info("%s holds %d media items", job.url, job.media_count)
        # Every item carries the post's own title, so the plain template would
        # have them all write over one another.
        ydl.params["outtmpl"]["default"] = str(
            target_dir / "%(title).100B - %(playlist_index)s [%(id)s].%(ext)s")
        if config.skip_existing:
            # yt-dlp then leaves items that are already on disk alone.
            ydl.params["overwrites"] = None

    @staticmethod
    def _job_dir(job: DownloadJob, config: DownloadConfig) -> Path:
        if config.playlist_folders and job.playlist_title:
            return config.output_dir / safe_folder_name(job.playlist_title)
        return config.output_dir

    @staticmethod
    def _narrow_subtitle_langs(options: dict[str, Any], info: Optional[dict[str, Any]]) -> None:
        """Ask only for the caption languages this video actually offers.

        yt-dlp merely warns about a language it cannot find, but narrowing the
        request keeps the convert and embed steps from running on nothing and
        removes the most common reason a caption download errors out.
        """
        if not info:
            return
        wanted = [str(lang) for lang in (options.get("subtitleslangs") or [])]
        if any(lang.lower() in {"all", "-all"} for lang in wanted):
            return
        available: set[str] = set(info.get("subtitles") or {})
        if options.get("writeautomaticsub"):
            available |= set(info.get("automatic_captions") or {})
        # "en" should also match the "en-US" / "en-orig" style codes.
        keep = [lang for lang in wanted
                if any(code == lang or code.startswith(f"{lang}-") for code in available)]
        if keep:
            options["subtitleslangs"] = keep
        else:
            options["writesubtitles"] = False
            options["writeautomaticsub"] = False

    def _options(
        self,
        job: DownloadJob,
        config: DownloadConfig,
        target_dir: Path,
        with_subtitles: bool,
        state: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "outtmpl": str(target_dir / "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "restrictfilenames": False,
            "noplaylist": True,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
            "progress_hooks": [self._progress_hook(job, state)],
            "postprocessor_hooks": [self._postprocessor_hook(job)],
            "quiet": True,
            "no_warnings": True,
            "color": "no_color",
            "logger": self.logger,
        }
        if not config.playlists:
            # One link, one file. This also keeps the probe below from walking
            # a whole playlist just to find out how long it is.
            options["playlistend"] = 1
        # Point yt-dlp at whatever we resolved rather than letting it search PATH
        # on its own: an auto-downloaded FFmpeg lives beside the app, not on PATH.
        # The directory is passed so ffprobe is picked up alongside ffmpeg.
        resolved = find_ffmpeg(config.ffmpeg_path)
        if resolved:
            options["ffmpeg_location"] = str(Path(resolved).parent)
        elif config.ffmpeg_path:
            options["ffmpeg_location"] = config.ffmpeg_path

        postprocessors: list[dict[str, Any]] = []
        if config.audio_only:
            options["format"] = "ba/b"
            extract: dict[str, Any] = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": config.audio_format,
            }
            if config.audio_format not in LOSSLESS_AUDIO:
                extract["preferredquality"] = config.audio_quality
            postprocessors.append(extract)
        else:
            options["format"] = self._format_for(config.quality)
            options["merge_output_format"] = "mp4"
        if with_subtitles and config.wants_subtitles:
            postprocessors.extend(self._subtitle_options(options, config, bool(resolved)))
        if postprocessors:
            options["postprocessors"] = postprocessors
        return options

    @staticmethod
    def _subtitle_options(
        options: dict[str, Any], config: DownloadConfig, has_ffmpeg: bool
    ) -> list[dict[str, Any]]:
        """Turn on subtitle downloads and return the postprocessors they need."""
        options["writesubtitles"] = True
        options["writeautomaticsub"] = config.subtitle_auto
        options["subtitleslangs"] = subtitle_languages(config.subtitle_langs)
        options["subtitlesformat"] = "srt/vtt/best"

        postprocessors: list[dict[str, Any]] = []
        keep_files = config.subtitle_mode in KEEP_SUBTITLE_MODES
        if keep_files and has_ffmpeg:
            # Sources often only offer VTT; .srt is what players expect.
            postprocessors.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
        if config.subtitle_mode in EMBED_SUBTITLE_MODES:
            postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": keep_files})
        return postprocessors

    def _postprocessor_hook(self, job: DownloadJob) -> Callable[[dict[str, Any]], None]:
        def hook(data: dict[str, Any]) -> None:
            # Postprocessing renames the file (merge, audio extraction), so the path
            # recorded by the progress hook is stale by the time the job finishes.
            if data.get("status") != "finished":
                return
            path = (data.get("info_dict") or {}).get("filepath")
            if path:
                job.output_path = str(path)
        return hook

    @staticmethod
    def _format_for(quality: str) -> str:
        if quality == "Best available":
            return "bv*+ba/b"
        height = int(quality.rstrip("p"))
        return f"bv*[height<={height}]+ba/b[height<={height}]/b"

    def _progress_hook(
        self, job: DownloadJob, state: Optional[dict[str, Any]] = None
    ) -> Callable[[dict[str, Any]], None]:
        def hook(data: dict[str, Any]) -> None:
            # Raising from a progress hook is yt-dlp's supported way to stop
            # an in-flight download without killing its worker thread.
            if self.cancel_event.is_set():
                raise RuntimeError("Download cancelled by user")
            status = data.get("status")
            if status == "downloading":
                downloaded = int(data.get("downloaded_bytes") or 0)
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                job.downloaded_bytes = downloaded
                job.total_bytes = int(total) if total else None
                job.speed = float(data["speed"]) if data.get("speed") else None
                job.eta = int(data["eta"]) if data.get("eta") is not None else None
                job.progress = downloaded / job.total_bytes if job.total_bytes else 0.0
                self._emit({"type": "progress", "job_id": job.job_id, "downloaded": downloaded,
                            "total": job.total_bytes, "speed": job.speed, "eta": job.eta,
                            "progress": job.progress})
            elif status == "finished":
                # The media itself is on disk now; anything that fails after this
                # point is postprocessing, which must not lose the download.
                if state is not None:
                    state["media_done"] = True
                job.output_path = str(data.get("filename") or "")
                self._emit({"type": "progress", "job_id": job.job_id, "downloaded": job.downloaded_bytes,
                            "total": job.total_bytes, "speed": None, "eta": 0, "progress": 1.0})
        return hook

    @staticmethod
    def _prepared_path(ydl: Any, info: dict[str, Any], output_dir: Path, ext: str = "") -> Path:
        path = Path(ydl.prepare_filename(info))
        if path.parent != output_dir:
            path = output_dir / path.name
        return path.with_suffix(f".{ext}") if ext else path

    def _existing_output(
        self, ydl: Any, info: dict[str, Any], config: DownloadConfig, target_dir: Path
    ) -> bool:
        if not info:
            return False
        prepared = self._prepared_path(ydl, info, target_dir)
        candidates = {prepared, prepared.with_suffix(f".{config.target_ext}")}
        return any(path.is_file() and path.stat().st_size > 0 for path in candidates)

    def _status(self, job: DownloadJob, status: str, error: str = "") -> None:
        job.status = status
        if error:
            job.error = error
        self._emit({"type": "status", "job_id": job.job_id, "status": status,
                    "error": job.error, "note": job.note, "output_path": job.output_path,
                    "media_count": job.media_count})

    def _emit(self, event: dict[str, Any]) -> None:
        self.event_queue.put(event)


def find_ffmpeg(configured_path: str = "") -> Optional[str]:
    """Return a usable ffmpeg executable or None."""
    if configured_path:
        candidate = Path(configured_path)
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            for name in ("ffmpeg.exe", "ffmpeg"):
                path = candidate / name
                if path.is_file():
                    return str(path)
    try:
        from ffmpeg_setup import installed_ffmpeg
        downloaded = installed_ffmpeg()
    except Exception:
        downloaded = None
    if downloaded:
        return str(downloaded)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if candidate.is_file():
            return str(candidate)
    return None
