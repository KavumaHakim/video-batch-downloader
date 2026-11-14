"""Reading track lists off Spotify links.

Spotify's own audio is DRM-protected and yt-dlp cannot download it — the
project lists open.spotify.com among the sites it explicitly does not support.
What a Spotify link does give us, through the public embed page that needs no
account or API key, is what is on it: the track titles and artists. Those are
turned into search queries so the matching track can be fetched from a site the
downloader does handle, which is what every Spotify "downloader" really does.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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
    artwork: str = ""

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    def search_url(self, prefix: str = DEFAULT_MATCH_SOURCE) -> str:
        """A yt-dlp search URL that resolves to the best match for this track."""
        query = re.sub(r"\s+", " ", f"{self.artist} {self.title}").strip()
        return f"{prefix}1:{query}"


def looks_like_spotify(url: str) -> bool:
    return bool(SPOTIFY_LINK.match(url.strip()))


# --------------------------------------------------------------------- search
# Searching needs the Web API, which needs an app registered at
# developer.spotify.com: anonymous access to the web player's own token is
# refused, and the search page carries no results to read. The client
# credentials flow is app-only, so nobody signs in and no personal data is
# touched; it just identifies the app making the query.
TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - an endpoint, not a secret
SEARCH_URL = "https://api.spotify.com/v1/search"
SEARCH_KINDS: list[tuple[str, str]] = [
    ("Tracks", "track"),
    ("Albums", "album"),
    ("Playlists", "playlist"),
]
MAX_SEARCH_RESULTS = 50


@dataclass
class SpotifyResult:
    """One thing Spotify found: a track, or an album/playlist to expand."""
    kind: str                 # track | album | playlist
    name: str
    subtitle: str = ""        # artists, or the owner of a playlist
    url: str = ""             # its open.spotify.com page
    artwork: str = ""
    duration_ms: Optional[int] = None
    total_tracks: Optional[int] = None

    @property
    def label(self) -> str:
        return f"{self.subtitle} — {self.name}" if self.subtitle else self.name

    def as_track(self) -> SpotifyTrack:
        return SpotifyTrack(self.name, self.subtitle, self.duration_ms)


class SpotifyCredentials:
    """Holds an app's client id and secret, and the token they buy.

    A token lasts an hour, so it is kept rather than re-fetched per search.
    The secret is never logged or put in a URL; it travels in the Basic auth
    header the way Spotify's client credentials flow expects.
    """

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def matches(self, client_id: str, client_secret: str) -> bool:
        return (self.client_id == (client_id or "").strip()
                and self.client_secret == (client_secret or "").strip())

    def token(self) -> str:
        if not self.configured:
            raise SpotifyError(
                "Spotify search needs a Client ID and Secret. Create a free app at "
                "developer.spotify.com/dashboard and paste them into Settings.")
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            pair = f"{self.client_id}:{self.client_secret}".encode()
            request = urllib.request.Request(
                TOKEN_URL,
                data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
                headers={
                    "Authorization": "Basic " + base64.b64encode(pair).decode(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 401):
                    raise SpotifyError(
                        "Spotify rejected those credentials. Check the Client ID and Secret "
                        "in Settings against your app at developer.spotify.com/dashboard."
                    ) from exc
                raise SpotifyError(f"Spotify refused to issue a token: HTTP {exc.code}") from exc
            except (urllib.error.URLError, OSError) as exc:
                raise SpotifyError(f"Could not reach Spotify: {exc}") from exc
            token = str(payload.get("access_token") or "")
            if not token:
                raise SpotifyError("Spotify returned no token for those credentials.")
            # Renew a minute early rather than racing the expiry.
            self._token = token
            self._expires_at = time.monotonic() + max(60, int(payload.get("expires_in") or 3600)) - 60
            return token

    def forget(self) -> None:
        with self._lock:
            self._token, self._expires_at = "", 0.0


def _best_image(images: Any) -> str:
    """Pick cover art near card size rather than the full-resolution original.

    The Web API calls the dimension "width"; the embed page calls it
    "maxWidth". Both shapes turn up, so take whichever is there.
    """
    candidates = [i for i in (images or []) if isinstance(i, dict) and i.get("url")]
    if not candidates:
        return ""
    def width(image: dict[str, Any]) -> Optional[int]:
        for key in ("width", "maxWidth"):
            if isinstance(image.get(key), int):
                return int(image[key])
        return None
    sized = sorted((i for i in candidates if width(i)), key=lambda i: abs(width(i) - 160))
    return str((sized[0] if sized else candidates[-1])["url"])


def _result_from(item: dict[str, Any], kind: str) -> Optional[SpotifyResult]:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    url = str((item.get("external_urls") or {}).get("spotify") or "")
    if kind == "track":
        album = item.get("album") or {}
        return SpotifyResult(
            kind, name, _artist_names(item), url, _best_image(album.get("images")),
            duration_ms=item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None)
    if kind == "album":
        return SpotifyResult(
            kind, name, _artist_names(item), url, _best_image(item.get("images")),
            total_tracks=item.get("total_tracks") if isinstance(item.get("total_tracks"), int) else None)
    owner = str((item.get("owner") or {}).get("display_name") or "")
    tracks = item.get("tracks") or {}
    return SpotifyResult(
        kind, name, owner, url, _best_image(item.get("images")),
        total_tracks=tracks.get("total") if isinstance(tracks.get("total"), int) else None)


def search_spotify(
    query: str,
    credentials: SpotifyCredentials,
    kind: str = "track",
    limit: int = 20,
    logger: Optional[logging.Logger] = None,
) -> list[SpotifyResult]:
    """Search Spotify for tracks, albums or playlists."""
    query = query.strip()
    if not query:
        return []
    limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    params = urllib.parse.urlencode({"q": query, "type": kind, "limit": limit})
    request = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"Authorization": f"Bearer {credentials.token()}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            # The token went stale mid-session; drop it so the next try renews.
            credentials.forget()
            raise SpotifyError("Spotify rejected the saved token. Try the search again.") from exc
        if exc.code == 429:
            raise SpotifyError("Spotify is rate limiting this app. Wait a moment and try again.") from exc
        raise SpotifyError(f"Spotify search failed: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SpotifyError(f"Could not reach Spotify: {exc}") from exc

    bucket = payload.get(f"{kind}s") or {}
    results: list[SpotifyResult] = []
    for item in bucket.get("items") or []:
        if not isinstance(item, dict):
            continue          # Spotify pads playlist results with nulls
        found = _result_from(item, kind)
        if found:
            results.append(found)
    if logger:
        logger.info("Spotify search %r (%s) returned %d result(s)", query, kind, len(results))
    return results


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


def _embed_artwork(entity: dict[str, Any]) -> str:
    art = entity.get("visualIdentity") or entity.get("coverArt") or {}
    if not isinstance(art, dict):
        return ""
    return _best_image(art.get("image") or art.get("sources"))


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
    # The embed gives one cover for the release; its tracks carry no art of
    # their own, so every track of an album or playlist shares it.
    cover = _embed_artwork(entity)
    raw = entity.get("trackList")
    entries = raw if isinstance(raw, list) else []
    if not entries:
        # A single track or episode: the entity itself is the one item.
        title = str(entity.get("name") or entity.get("title") or "")
        if not title:
            raise SpotifyError("That Spotify link holds nothing this app can read.")
        duration = entity.get("duration")
        return name, [SpotifyTrack(title, _artist_names(entity),
                                   int(duration) if isinstance(duration, int) else None,
                                   _embed_artwork(entity))]

    tracks: list[SpotifyTrack] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        duration = entry.get("duration")
        tracks.append(SpotifyTrack(title, _artist_names(entry).strip(),
                                   int(duration) if isinstance(duration, int) else None,
                                   cover))
        if limit > 0 and len(tracks) >= limit:
            break
    if not tracks:
        raise SpotifyError("Spotify listed no tracks for that link.")
    if logger:
        logger.info("Spotify %s %r holds %d track(s)", kind, name, len(tracks))
    return name, tracks
