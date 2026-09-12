"""Video search via yt-dlp's built-in search extractors."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

try:
    import yt_dlp
except Exception:
    yt_dlp = None  # type: ignore[assignment]


SEARCH_SITES: list[tuple[str, str]] = [
    ("YouTube", "ytsearch"),
    ("SoundCloud", "scsearch"),
    ("Bilibili", "bilisearch"),
    ("Niconico", "nicosearch"),
    ("Yahoo Video", "yvsearch"),
]

MAX_RESULTS = 50


@dataclass
class SearchResult:
    title: str
    url: str
    site: str
    uploader: str = ""
    duration: Optional[float] = None
    view_count: Optional[int] = None
    thumbnail: str = ""


def _best_thumbnail(entry: dict[str, Any]) -> str:
    if entry.get("thumbnail"):
        return str(entry["thumbnail"])
    thumbs = entry.get("thumbnails") or []
    candidates = [t for t in thumbs if t.get("url")]
    if not candidates:
        return ""
    # Prefer something small enough for a list row; fall back to the last (usually largest) one.
    sized = sorted((t for t in candidates if t.get("width")), key=lambda t: abs(int(t["width"]) - 320))
    return str((sized[0] if sized else candidates[-1])["url"])


def _entry_url(entry: dict[str, Any]) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    return str(entry.get("url") or "")


def search_videos(query: str, prefix: str, limit: int, logger: logging.Logger | None = None) -> list[SearchResult]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed.")
    query = query.strip()
    if not query:
        return []
    limit = max(1, min(int(limit), MAX_RESULTS))
    site = next((name for name, key in SEARCH_SITES if key == prefix), prefix)
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": True,
    }
    if logger:
        options["logger"] = logger
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"{prefix}{limit}:{query}", download=False)
    results: list[SearchResult] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        url = _entry_url(entry)
        if not url:
            continue
        results.append(SearchResult(
            title=str(entry.get("title") or url),
            url=url,
            site=site,
            uploader=str(entry.get("uploader") or entry.get("channel") or ""),
            duration=float(entry["duration"]) if entry.get("duration") else None,
            view_count=int(entry["view_count"]) if entry.get("view_count") is not None else None,
            thumbnail=_best_thumbnail(entry),
        ))
    return results


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_views(count: Optional[int]) -> str:
    if count is None:
        return "—"
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
