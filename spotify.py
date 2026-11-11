"""Reading track lists off Spotify links.

Spotify's own audio is DRM-protected and yt-dlp cannot download it — the
project lists open.spotify.com among the sites it explicitly does not support.
What a Spotify link does give us, through the public embed page that needs no
account or API key, is what is on it: the track titles and artists. Those are
turned into search queries so the matching track can be fetched from a site the
downloader does handle, which is what every Spotify "downloader" really does.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

SPOTIFY_LINK = re.compile(
    r"^https?://(?:open|play)\.spotify\.com/(?:intl-[a-z]{2,5}(?:-[a-z]+)?/)?"
    r"(track|album|playlist|artist|show|episode)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
EMBED_URL = "https://open.spotify.com/embed/{kind}/{sid}"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
# Generic client string: nothing here identifies the person running the app.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# yt-dlp search prefixes a matched track can be looked for with.
MATCH_SOURCES: list[tuple[str, str]] = [
    ("YouTube", "ytsearch"),
    ("SoundCloud", "scsearch"),
]
DEFAULT_MATCH_SOURCE = "ytsearch"


class SpotifyError(RuntimeError):
    pass


@dataclass
class SpotifyTrack:
    title: str
    artist: str = ""
    duration_ms: Optional[int] = None

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    def search_url(self, prefix: str = DEFAULT_MATCH_SOURCE) -> str:
        """A yt-dlp search URL that resolves to the best match for this track."""
        query = re.sub(r"\s+", " ", f"{self.artist} {self.title}").strip()
        return f"{prefix}1:{query}"


def looks_like_spotify(url: str) -> bool:
    return bool(SPOTIFY_LINK.match(url.strip()))


def _fetch(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def _entity(payload: dict[str, Any]) -> dict[str, Any]:
    state = (payload.get("props") or {}).get("pageProps") or {}
    data = (state.get("state") or {}).get("data") or state.get("data") or {}
    entity = data.get("entity")
    return entity if isinstance(entity, dict) else (data if isinstance(data, dict) else {})


def _artist_names(entry: dict[str, Any]) -> str:
    artists = entry.get("artists")
    if isinstance(artists, list):
        names = [str(a.get("name")) for a in artists if isinstance(a, dict) and a.get("name")]
        if names:
            return ", ".join(names)
    # Album and playlist track lists carry the artist as a plain subtitle.
    return str(entry.get("subtitle") or "")


def spotify_tracks(
    url: str,
    logger: Optional[logging.Logger] = None,
    limit: int = 0,
) -> tuple[str, list[SpotifyTrack]]:
    """Return (collection name, tracks) for a Spotify link.

    A /track/ link yields one track; albums, playlists and artist pages yield
    the list the embed page carries.
    """
    match = SPOTIFY_LINK.match(url.strip())
    if not match:
        return "", []
    kind, sid = match.group(1).lower(), match.group(2)
    try:
        html = _fetch(EMBED_URL.format(kind=kind, sid=sid))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SpotifyError(f"Could not reach Spotify: {exc}") from exc

    found = NEXT_DATA.search(html)
    if not found:
        raise SpotifyError("Spotify did not return the data this page usually carries.")
    try:
        entity = _entity(json.loads(found.group(1)))
    except (json.JSONDecodeError, AttributeError) as exc:
        raise SpotifyError(f"Could not read the Spotify page: {exc}") from exc
    if not entity:
        raise SpotifyError("That Spotify link holds nothing this app can read.")

    name = str(entity.get("name") or entity.get("title") or kind.title())
    raw = entity.get("trackList")
    entries = raw if isinstance(raw, list) else []
    if not entries:
        # A single track or episode: the entity itself is the one item.
        title = str(entity.get("name") or entity.get("title") or "")
        if not title:
            raise SpotifyError("That Spotify link holds nothing this app can read.")
        duration = entity.get("duration")
        return name, [SpotifyTrack(title, _artist_names(entity),
                                   int(duration) if isinstance(duration, int) else None)]

    tracks: list[SpotifyTrack] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        duration = entry.get("duration")
        tracks.append(SpotifyTrack(title, _artist_names(entry).strip(),
                                   int(duration) if isinstance(duration, int) else None))
        if limit > 0 and len(tracks) >= limit:
            break
    if not tracks:
        raise SpotifyError("Spotify listed no tracks for that link.")
    if logger:
        logger.info("Spotify %s %r holds %d track(s)", kind, name, len(tracks))
    return name, tracks
