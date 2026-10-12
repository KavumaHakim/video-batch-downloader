"""Fetch a static FFmpeg build for Windows into the application folder.

Binaries come from gyan.dev, the Windows build provider linked from
ffmpeg.org/download.html, and are verified against the SHA-256 the same
site publishes alongside the archive.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

BASE_URL = "https://www.gyan.dev/ffmpeg/builds/"
ARCHIVE_URL = BASE_URL + "ffmpeg-release-essentials.zip"
CHECKSUM_URL = ARCHIVE_URL + ".sha256"
VERSION_URL = BASE_URL + "release-version"
USER_AGENT = "video-batch-downloader"

WANTED = ("ffmpeg.exe", "ffprobe.exe")
CHUNK = 256 * 1024
READ_TIMEOUT = 120
MAX_ATTEMPTS = 4
RETRY_DELAY = 2.0


class DownloadCancelled(Exception):
    pass


def install_dir() -> Path:
    """Where a downloaded FFmpeg lives: a folder beside the app itself."""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "ffmpeg"


def installed_ffmpeg() -> Optional[Path]:
    candidate = install_dir() / "ffmpeg.exe"
    return candidate if candidate.is_file() else None


def is_supported() -> bool:
    return os.name == "nt"


def _get(url: str, timeout: int = 60):
    return urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def latest_version() -> str:
    try:
        return _get(VERSION_URL, timeout=20).read().decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _expected_sha256() -> str:
    # The file is "<hex>" or "<hex>  <filename>"; take the first token.
    text = _get(CHECKSUM_URL, timeout=30).read().decode("utf-8", "replace").strip()
    digest = text.split()[0].lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise RuntimeError("FFmpeg checksum file was not in the expected format.")
    return digest


def _download(target: Path, progress: Optional[Callable[[int, int], None]], cancel: Optional[threading.Event]) -> None:
    """Stream the archive, resuming with HTTP Range if the connection drops."""
    done = 0
    total = 0
    last_error: Optional[Exception] = None
    for attempt in range(MAX_ATTEMPTS):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()
        headers = {"User-Agent": USER_AGENT}
        if done:
            headers["Range"] = f"bytes={done}-"
        try:
            response = urlopen(Request(ARCHIVE_URL, headers=headers), timeout=READ_TIMEOUT)
            resuming = response.status == 206
            if done and not resuming:
                done = 0  # Server ignored the range request, so start over.
            length = int(response.headers.get("Content-Length") or 0)
            total = done + length if length else total
            mode = "ab" if done else "wb"
            with target.open(mode) as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            if total and done < total:
                raise OSError(f"connection closed after {done} of {total} bytes")
            return
        except DownloadCancelled:
            raise
        except Exception as exc:
            last_error = exc
            done = target.stat().st_size if target.exists() else 0
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"The FFmpeg download kept failing ({last_error}). Check your connection and try again.")


def _extract(archive: Path, destination: Path, cancel: Optional[threading.Event]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled()
            name = Path(member.filename).name
            if member.is_dir() or name.lower() not in WANTED:
                continue
            # Flatten to a known filename rather than trusting the archive's paths.
            out = destination / name.lower()
            with zf.open(member) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            found[name.lower()] = out
    if "ffmpeg.exe" not in found:
        raise RuntimeError("The downloaded archive did not contain ffmpeg.exe.")
    return found["ffmpeg.exe"]


def download_ffmpeg(
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> Path:
    """Download, verify and unpack FFmpeg. Returns the path to ffmpeg.exe."""
    if not is_supported():
        raise RuntimeError("Automatic FFmpeg download is only implemented for Windows.")
    expected = _expected_sha256()
    temp_dir = Path(tempfile.mkdtemp(prefix="ffmpeg_dl_"))
    archive = temp_dir / "ffmpeg.zip"
    try:
        _download(archive, progress, cancel)
        digest = hashlib.sha256()
        with archive.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected:
            raise RuntimeError(
                "The FFmpeg download did not match the checksum published by gyan.dev "
                f"(expected {expected[:12]}…, got {actual[:12]}…). The file was discarded."
            )
        return _extract(archive, install_dir(), cancel)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
