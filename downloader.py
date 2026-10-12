"""Background download service for the Video Batch Downloader GUI."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Optional

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


# Codec -> container extension yt-dlp writes after FFmpegExtractAudio.
AUDIO_FORMATS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "wav": "wav", "flac": "flac"}
LOSSLESS_AUDIO = {"wav", "flac"}


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

    @property
    def audio_only(self) -> bool:
        return bool(self.audio_format)

    @property
    def target_ext(self) -> str:
        return AUDIO_FORMATS.get(self.audio_format, "mp4") if self.audio_only else "mp4"


class DownloadManager:
    """Runs yt-dlp jobs off the Tkinter thread and emits plain dictionaries."""

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
        try:
            options = self._options(job, config)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(job.url, download=False)
                if info and info.get("title"):
                    job.title = str(info["title"])
                    self._emit({"type": "metadata", "job_id": job.job_id, "title": job.title})
                if config.skip_existing and self._existing_output(ydl, info, config):
                    job.output_path = str(self._prepared_path(ydl, info, config.output_dir, config.target_ext))
                    self._status(job, "Skipped")
                    self.logger.info("Skipped existing file: %s", job.url)
                    return
                if self.cancel_event.is_set():
                    self._status(job, "Cancelled")
                    return
                ydl.download([job.url])
            if self.cancel_event.is_set():
                self._status(job, "Cancelled")
            else:
                self._status(job, "Completed")
                self.logger.info("Completed: %s | %s", job.url, job.output_path)
        except Exception as exc:
            if self.cancel_event.is_set():
                self._status(job, "Cancelled")
            else:
                job.error = str(exc).strip() or exc.__class__.__name__
                self._status(job, "Failed", error=job.error)
                self.logger.error("Failed: %s | %s", job.url, job.error)

    def _options(self, job: DownloadJob, config: DownloadConfig) -> dict[str, Any]:
        options: dict[str, Any] = {
            "outtmpl": str(config.output_dir / "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "restrictfilenames": False,
            "noplaylist": True,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
            "progress_hooks": [self._progress_hook(job)],
            "postprocessor_hooks": [self._postprocessor_hook(job)],
            "quiet": True,
            "no_warnings": True,
            "logger": self.logger,
        }
        if config.audio_only:
            options["format"] = "ba/b"
            postprocessor: dict[str, Any] = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": config.audio_format,
            }
            if config.audio_format not in LOSSLESS_AUDIO:
                postprocessor["preferredquality"] = config.audio_quality
            options["postprocessors"] = [postprocessor]
        else:
            options["format"] = self._format_for(config.quality)
            options["merge_output_format"] = "mp4"
        # Point yt-dlp at whatever we resolved rather than letting it search PATH
        # on its own: an auto-downloaded FFmpeg lives beside the app, not on PATH.
        # The directory is passed so ffprobe is picked up alongside ffmpeg.
        resolved = find_ffmpeg(config.ffmpeg_path)
        if resolved:
            options["ffmpeg_location"] = str(Path(resolved).parent)
        elif config.ffmpeg_path:
            options["ffmpeg_location"] = config.ffmpeg_path
        return options

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

    def _progress_hook(self, job: DownloadJob) -> Callable[[dict[str, Any]], None]:
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

    def _existing_output(self, ydl: Any, info: dict[str, Any], config: DownloadConfig) -> bool:
        if not info:
            return False
        prepared = self._prepared_path(ydl, info, config.output_dir)
        candidates = {prepared, prepared.with_suffix(f".{config.target_ext}")}
        return any(path.is_file() and path.stat().st_size > 0 for path in candidates)

    def _status(self, job: DownloadJob, status: str, error: str = "") -> None:
        job.status = status
        if error:
            job.error = error
        self._emit({"type": "status", "job_id": job.job_id, "status": status,
                    "error": job.error, "output_path": job.output_path})

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
