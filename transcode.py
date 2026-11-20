"""Turning video the player cannot decode into H.264 it can.

Qt's FFmpeg build only carries the decoders it can ship freely, and leaves
VP9, AV1 and HEVC to the graphics card. Many cards cannot do them, so such a
file plays as sound over a black screen. The app's own FFmpeg (the one that
merges downloads) can decode anything, so it re-encodes the picture once and
the file plays from then on, here and in any other player.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

# Keeps a console window from flashing up for each FFmpeg run in the windowed exe.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CODEC_NAMES = {"av1": "AV1", "vp9": "VP9", "vp8": "VP8", "hevc": "HEVC (H.265)", "h264": "H.264"}
# Containers whose audio can go into the new MP4 untouched.
COPY_AUDIO_FROM = {".mp4", ".m4v", ".mov"}


def ffprobe_for(ffmpeg: str) -> str:
    path = Path(ffmpeg)
    probe = path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
    return str(probe) if probe.is_file() else ""


def video_codec(ffmpeg: str, media: str) -> str:
    """The codec of the first real video stream ("" when there is none or it cannot be told).

    Cover art is stored as a video stream too; that is not a picture to play.
    """
    probe = ffprobe_for(ffmpeg)
    if not probe:
        return ""
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=codec_name:stream_disposition=attached_pic", "-of", "json", media],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        streams = json.loads(result.stdout or "{}").get("streams", [])
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    for stream in streams:
        if not (stream.get("disposition") or {}).get("attached_pic"):
            return str(stream.get("codec_name") or "")
    return ""


def codec_label(codec: str) -> str:
    return CODEC_NAMES.get(codec, codec.upper() or "an unsupported format")


def converted_path(source: Path) -> Path:
    """Where the H.264 version ends up: in place of the original.

    An MP4 keeps its name. Anything else becomes an MP4 of the same name,
    unless that name is already some other file.
    """
    if source.suffix.lower() == ".mp4":
        return source
    target = source.with_suffix(".mp4")
    return target if not target.exists() else source.with_name(f"{source.stem} (H.264).mp4")


class Transcoder(QThread):
    """Re-encodes one file's picture to H.264, then puts it in the original's place."""

    progress = Signal(int)          # percent
    done = Signal(str, str)         # original path, new path
    failed = Signal(str, str)       # original path, reason

    def __init__(self, ffmpeg: str, source: str, duration_ms: int, logger: logging.Logger) -> None:
        super().__init__()
        self.ffmpeg, self.source, self.duration_ms, self.logger = ffmpeg, Path(source), duration_ms, logger
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()

    def run(self) -> None:
        source = self.source
        target = converted_path(source)
        temp = source.with_name(f"{source.stem}.converting.mp4")
        audio = "copy" if source.suffix.lower() in COPY_AUDIO_FROM else "aac"
        command = [
            self.ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1",
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", audio, "-c:s", "mov_text", "-movflags", "+faststart",
            str(temp),
        ]
        self.logger.info("Converting to H.264 for playback: %s", source)
        errors = ""
        try:
            self._process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            assert self._process.stdout is not None
            for line in self._process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit() and self.duration_ms > 0:
                    self.progress.emit(min(99, int(int(value) / 1000 * 100 / self.duration_ms)))
            errors = self._process.stderr.read() if self._process.stderr else ""
            code = self._process.wait()
        except OSError as exc:
            code, errors = -1, str(exc)
        if self._cancelled or code != 0:
            temp.unlink(missing_ok=True)
            if self._cancelled:
                self.failed.emit(str(source), "")
            else:
                reason = (errors.strip().splitlines() or ["FFmpeg stopped with an error"])[-1]
                self.logger.error("Conversion failed for %s: %s", source, reason)
                self.failed.emit(str(source), reason)
            return
        try:
            os.replace(temp, target)
            if target != source:
                source.unlink(missing_ok=True)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            self.logger.error("Could not replace %s: %s", source, exc)
            self.failed.emit(str(source), f"the converted file could not replace the original ({exc.strerror})")
            return
        self.logger.info("Converted %s -> %s", source, target)
        self.progress.emit(100)
        self.done.emit(str(source), str(target))
