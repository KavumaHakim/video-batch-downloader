"""What the player can open, and one entry of its queue.

Plain Python on purpose: the main window checks files against this on every
card it draws, and must not load QtMultimedia just to do that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts", ".3gp", ".wmv", ".mpg", ".mpeg"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".oga", ".flac", ".wav", ".wma", ".alac", ".aiff", ".weba"}
MEDIA_FILTER = "Media files (" + " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTS | AUDIO_EXTS)) + ");;All files (*)"

# Stream links from most sites last a few hours; resolve again well before that.
STREAM_TTL = 2 * 60 * 60


def is_playable(path: str) -> bool:
    suffix = Path(path).suffix.lower() if path else ""
    return suffix in VIDEO_EXTS or suffix in AUDIO_EXTS


def is_audio_path(path: str) -> bool:
    return bool(path) and Path(path).suffix.lower() in AUDIO_EXTS


@dataclass
class PlayItem:
    """One entry in the play queue: a file on disk, or a page to stream."""

    title: str
    path: str = ""              # a local file; empty for a stream
    page_url: str = ""          # what yt-dlp resolves when there is no file
    thumbnail: str = ""
    audio_only: bool = False    # stream just the soundtrack
    subtitle: str = ""
    # Filled in when a stream is resolved.
    video_url: str = ""
    audio_url: str = ""
    resolved_at: float = 0.0
    has_video: bool = True
    codec: str = ""            # set when the picture is in a codec the player cannot decode

    @property
    def is_stream(self) -> bool:
        return not self.path

    @property
    def key(self) -> str:
        return str(Path(self.path).resolve()).lower() if self.path else self.page_url

    @property
    def is_audio(self) -> bool:
        if self.path:
            return is_audio_path(self.path)
        return self.audio_only or not self.has_video

    @property
    def resolved(self) -> bool:
        return bool(self.video_url) and time.time() - self.resolved_at < STREAM_TTL

    def forget_stream(self) -> None:
        self.video_url = self.audio_url = ""
        self.resolved_at = 0.0
