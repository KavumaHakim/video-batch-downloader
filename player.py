"""The built-in media player: downloaded files, a play queue, and streams.

Kept out of app.py so QtMultimedia (and the FFmpeg it brings) is only loaded
the first time someone actually plays something.
"""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QImage, QKeySequence,
    QPainter, QPainterPath, QPen, QPixmap, QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaFormat, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSizePolicy, QSlider, QStackedWidget, QStyle, QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget,
)

from downloader import best_thumbnail, yt_dlp
from transcode import Transcoder, codec_label, video_codec
from media_files import MEDIA_FILTER, PlayItem

# The video and the separate audio of a stream are two players. A small drift
# is eased out by playing the sound a touch faster or slower, which cannot be
# heard; only a large one is fixed by seeking, which re-buffers the audio.
SYNC_IN_STEP_MS = 40
SYNC_NUDGE_MS = 80
SYNC_JUMP_MS = 450
SYNC_NUDGE_RATE = 0.06
SEEK_STEP_MS = 5000
CONTROLS_HIDE_MS = 2500

ACCENT = "#58a6ff"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
BRIGHT = "#f0f6fc"

# Segoe Fluent Icons (Windows 11) and Segoe MDL2 Assets (Windows 10) share these
# code points; the plain symbols are only for a machine with neither.
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
GLYPHS = {
    "play": ("", "▶"), "pause": ("", "❚❚"), "prev": ("", "⏮"), "next": ("", "⏭"),
    "volume": ("", "🔊"), "mute": ("", "🔇"), "full": ("", "⛶"), "unfull": ("", "⛶"),
    "queue": ("", "☰"), "repeat": ("", "🔁"), "repeat1": ("", "🔂"), "open": ("", "+"),
    "music": ("", "♪"), "video": ("", "▶"),
}
GLYPHS.update({
    "download": (chr(0xE896), "⬇"), "shuffle": (chr(0xE8B1), "🔀"), "radio": (chr(0xE93E), "📻"),
})
REPEAT_MODES = ("off", "all", "one")
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
RADIO_SIZE = 25
VIDEO_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/)([\w-]{11})")


def video_id(url: str) -> str:
    """The YouTube video ID in a link, or "" when it has none."""
    found = VIDEO_ID.search(url or "")
    return found.group(1) if found else ""


def speed_label(rate: float) -> str:
    return f"{rate:g}×"

PLAYER_STYLE = """
QWidget#playerRoot { background: #0d1117; }
QFrame#stage { background: #010409; border: none; }
QFrame#controls { background: #161b22; border-top: 1px solid #30363d; }
QFrame#queuePanel { background: #161b22; border-left: 1px solid #30363d; }
QLabel#nowTitle { color: #f0f6fc; font-weight: 600; font-size: 10.5pt; }
QLabel#nowSub, QLabel#time, QLabel#queueHead { color: #8b949e; font-size: 9pt; }
QLabel#time { font-family: "Cascadia Mono", "Consolas", monospace; }
QLabel#queueHead { font-weight: 600; padding: 2px 4px; }

QToolButton#icon, QToolButton#play { font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol"; }
QToolButton#icon { background: transparent; color: #c9d1d9; border: none; border-radius: 6px; padding: 5px; min-width: 30px; min-height: 30px; font-size: 12pt; }
QToolButton#icon:hover { background: #21262d; color: #f0f6fc; }
QToolButton#icon:pressed { background: #1c2128; }
QToolButton#icon:checked { color: #58a6ff; }
QToolButton#icon:disabled { color: #484f58; }
QToolButton#text { background: transparent; color: #c9d1d9; border: none; border-radius: 6px; padding: 5px 7px; min-height: 30px; font-family: "Segoe UI"; font-size: 9pt; font-weight: 600; }
QToolButton#text:hover { background: #21262d; color: #f0f6fc; }
QToolButton#text::menu-indicator { image: none; width: 0; }
QToolButton#play { background: #1f6feb; color: #ffffff; border: none; border-radius: 19px; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; font-size: 13pt; }
QToolButton#play:hover { background: #388bfd; }
QToolButton#play:pressed { background: #1a5fca; }
QToolButton#play:disabled { background: #21262d; color: #484f58; }

QSlider#seek, QSlider#volume { background: transparent; }
QSlider#seek { min-height: 18px; }
QSlider::groove:horizontal { height: 4px; background: #30363d; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #58a6ff; border-radius: 2px; }
QSlider::add-page:horizontal { background: #30363d; border-radius: 2px; }
QSlider::handle:horizontal { background: #f0f6fc; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: #ffffff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal:disabled { background: #30363d; }
QSlider::handle:horizontal:disabled { background: #484f58; }

QListWidget#queue { background: transparent; border: none; outline: none; }
QListWidget#queue::item { padding: 7px 8px; border-radius: 6px; color: #c9d1d9; }
QListWidget#queue::item:hover { background: #1b2129; }
QListWidget#queue::item:selected { background: #1c2b3d; color: #f0f6fc; }
"""


def format_clock(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


# Muxed is simplest and is what most sites offer. YouTube no longer does, so
# the fallback is a separate picture and soundtrack, each a plain HTTPS file
# FFmpeg can seek in (fragmented DASH cannot be opened from one URL). H.264
# comes first: the FFmpeg that ships with Qt leaves VP9 and AV1 to the
# graphics card, and many cannot decode them, which shows as a black screen.
_PLAIN = "[protocol^=http][protocol!*=dash]"
_H264 = "[vcodec~='^(avc|h264)']"
_NOT_AV1 = "[vcodec!^=?av01]"
STREAM_VIDEO_FORMAT = (
    f"b[height<=1080]{_H264}{_PLAIN}"
    f"/bv*[height<=1080]{_H264}{_PLAIN}+ba[ext=m4a]{_PLAIN}"
    f"/bv*[height<=1080]{_H264}{_PLAIN}+ba{_PLAIN}"
    f"/b[height<=1080]{_NOT_AV1}{_PLAIN}"
    f"/bv*[height<=1080]{_NOT_AV1}{_PLAIN}+ba{_PLAIN}"
    f"/b[height<=1080]{_NOT_AV1}/bv*[height<=1080]{_NOT_AV1}+ba/b"
)
STREAM_AUDIO_FORMAT = f"ba[ext=m4a]{_PLAIN}/ba{_PLAIN}/ba/b"


def resolve_stream(page_url: str, audio_only: bool, logger: logging.Logger | None = None) -> dict[str, Any]:
    """Ask yt-dlp for URLs QMediaPlayer can open directly, without downloading."""
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not available, so links cannot be streamed.")
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlistend": 1,
        "format": STREAM_AUDIO_FORMAT if audio_only else STREAM_VIDEO_FORMAT,
    }
    if logger is not None:
        options["logger"] = logger
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(page_url, download=False)
    # A search ("ytsearch1:…", which is how Spotify tracks are matched) or a
    # playlist comes back as a list; the first entry is the one to play.
    while info and info.get("entries") is not None:
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise RuntimeError("Nothing playable was found for that link.")
        info = entries[0]
    if not info:
        raise RuntimeError("Nothing playable was found for that link.")

    def has(fmt: dict[str, Any], kind: str) -> bool:
        return (fmt.get(kind) or "none") != "none"

    requested = info.get("requested_formats") or []
    if len(requested) >= 2:
        video = next((f for f in requested if has(f, "vcodec")), requested[0])
        audio = next((f for f in requested if f is not video and has(f, "acodec")), requested[1])
        video_url, audio_url, has_video = video.get("url", ""), audio.get("url", ""), True
    else:
        video_url, audio_url = info.get("url", ""), ""
        # Unknown codecs ("None") are common for single-file formats; assume
        # there is a picture unless the format says it is audio only.
        has_video = not audio_only and info.get("vcodec") != "none"
    if not video_url:
        raise RuntimeError("That site did not offer a stream that can be played here.")
    return {
        "title": info.get("title") or "",
        "thumbnail": info.get("thumbnail") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage": info.get("webpage_url") or "",
        "video_url": video_url,
        "audio_url": audio_url,
        "has_video": has_video,
    }


# ffprobe's codec names, as QMediaFormat knows them.
_QT_CODECS = {
    "h264": "H264", "hevc": "H265", "vp8": "VP8", "vp9": "VP9", "av1": "AV1", "mpeg4": "MPEG4",
    "mpeg2video": "MPEG2", "mpeg1video": "MPEG1", "wmv1": "WMV", "wmv2": "WMV", "wmv3": "WMV",
    "mjpeg": "MotionJPEG", "theora": "Theora",
}
_decodable: set[str] | None = None


def can_decode(codec: str) -> bool:
    """Whether Qt's FFmpeg, with this PC's graphics card, can show this codec.

    Qt can report a video stream it then never decodes, which plays as a black
    screen, so this asks what it can decode rather than what it found.
    """
    global _decodable
    if _decodable is None:
        _decodable = {codec.name for codec in
                      QMediaFormat().supportedVideoCodecs(QMediaFormat.ConversionMode.Decode)}
    name = _QT_CODECS.get(codec)
    return name is None or name in _decodable     # unknown names get the benefit of the doubt


class StreamResolver(QThread):
    resolved = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, token: int, page_url: str, audio_only: bool, logger: logging.Logger) -> None:
        super().__init__()
        self.token, self.page_url, self.audio_only, self.logger = token, page_url, audio_only, logger

    def run(self) -> None:
        try:
            self.resolved.emit(self.token, resolve_stream(self.page_url, self.audio_only, self.logger))
        except Exception as exc:  # yt-dlp raises many kinds; all mean "cannot stream"
            message = str(exc).replace("ERROR: ", "").strip() or exc.__class__.__name__
            self.logger.warning("Could not stream %s: %s", self.page_url, message)
            self.failed.emit(self.token, message)


class RadioFetcher(QThread):
    """Reads YouTube's Mix for a video: the songs that go with it, as radio."""

    found = Signal(int, list)          # token, [(url, title, thumbnail)]

    def __init__(self, token: int, vid: str, logger: logging.Logger) -> None:
        super().__init__()
        self.token, self.vid, self.logger = token, vid, logger

    def run(self) -> None:
        entries: list[tuple[str, str, str]] = []
        try:
            if yt_dlp is None:
                raise RuntimeError("yt-dlp is not available")
            options = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                       "playlistend": RADIO_SIZE + 1, "logger": self.logger}
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={self.vid}&list=RD{self.vid}",
                                        download=False)
            for entry in (info or {}).get("entries") or []:
                if not entry:
                    continue
                url = entry.get("url") or entry.get("webpage_url") or ""
                if not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={entry.get('id', '')}" if entry.get("id") else ""
                if url and video_id(url) != self.vid:
                    entries.append((url, entry.get("title") or url, best_thumbnail(entry)))
        except Exception as exc:  # network, removed video, a site change...
            self.logger.warning("Radio for %s failed: %s", self.vid, exc)
        self.found.emit(self.token, entries[:RADIO_SIZE])


class ElidedLabel(QLabel):
    """A one-line label that ends in an ellipsis instead of being cut off."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt's name
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(10, self.width())
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width))


class SeekSlider(QSlider):
    """A slider that jumps to where it is clicked, then drags from there."""

    seek_requested = Signal(int)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                                 QStyle.SubControl.SC_SliderGroove, self)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                                 QStyle.SubControl.SC_SliderHandle, self)
            if not handle.contains(event.position().toPoint()):
                span = groove.width() - handle.width()
                x = int(event.position().x()) - groove.x() - handle.width() // 2
                value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), x, max(1, span))
                self.setValue(value)
                self.seek_requested.emit(value)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        dragged = self.isSliderDown()
        super().mouseReleaseEvent(event)
        if dragged:
            self.seek_requested.emit(self.value())

    def wheelEvent(self, event: Any) -> None:
        event.ignore()      # scrolling past it must not scrub the video


class ArtView(QWidget):
    """What fills the stage for audio, and while a stream is being fetched."""

    double_clicked = Signal()
    action_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.pixmap: QPixmap | None = None
        self.title = ""
        self.subtitle = ""
        self.message = ""
        self.message_is_error = False
        self.glyph_font = QFont()
        self.glyph = "♪"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.button = QPushButton(self)
        self.button.setObjectName("primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.clicked.connect(self.action_clicked)
        self.button.hide()

    def show_item(self, title: str, subtitle: str, pixmap: QPixmap | None) -> None:
        self.title, self.subtitle, self.pixmap = title, subtitle, pixmap
        self._place_button()
        self.update()

    def set_message(self, text: str, error: bool = False) -> None:
        self.message, self.message_is_error = text, error
        self._place_button()
        self.update()

    def set_action(self, text: str) -> None:
        """Offer one button under the message; an empty text takes it away."""
        self.button.setText(text)
        self.button.setVisible(bool(text))
        self.button.adjustSize()
        self._place_button()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._place_button()

    def _art_rect(self) -> QRect:
        width, height = self.width(), self.height()
        side = int(min(width * 0.6, height * 0.55, 420))
        return QRect((width - side) // 2, int(height * 0.42) - side // 2, side, side)

    def _fonts(self) -> tuple[QFont, QFont]:
        title = QFont(self.font())
        title.setPointSize(14)
        title.setBold(True)
        line = QFont(self.font())
        line.setPointSize(10)
        return title, line

    def _text_bottom(self) -> int:
        title_font, line_font = self._fonts()
        y = self._art_rect().bottom() + 22
        if self.title:
            y += QFontMetrics(title_font).height() + 4
        lines = int(bool(self.subtitle)) + int(bool(self.message))
        return y + lines * (QFontMetrics(line_font).height() + 4)

    def _place_button(self) -> None:
        if not self.button.isHidden():      # placed even while the art view is off screen
            size = self.button.sizeHint()
            self.button.setGeometry((self.width() - size.width()) // 2, self._text_bottom() + 10,
                                    size.width(), size.height())

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.double_clicked.emit()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#010409"))
        width = self.width()
        art = self._art_rect()
        side = art.width()
        if self.title or self.message:
            path = QPainterPath()
            path.addRoundedRect(QRectF(art), 14, 14)
            if self.pixmap is not None and not self.pixmap.isNull():
                # Fill the square: centre-crop whatever shape the artwork is.
                scaled = self.pixmap.scaled(art.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
                source = QRect((scaled.width() - side) // 2, (scaled.height() - side) // 2, side, side)
                painter.save()
                painter.setClipPath(path)
                painter.drawPixmap(art, scaled, source)
                painter.restore()
            else:
                painter.fillPath(path, QBrush(QColor("#161b22")))
                painter.setPen(QPen(QColor("#30363d"), 1))
                painter.drawPath(path)
                font = QFont(self.glyph_font)
                font.setPixelSize(max(24, side // 3))
                painter.setFont(font)
                painter.setPen(QColor("#484f58"))
                painter.drawText(art, Qt.AlignmentFlag.AlignCenter, self.glyph)

        y = art.bottom() + 22
        text_width = min(width - 48, 640)
        left = (width - text_width) // 2
        title_font, line_font = self._fonts()
        if self.title:
            font = title_font
            metrics = QFontMetrics(font)
            painter.setFont(font)
            painter.setPen(QColor(BRIGHT))
            painter.drawText(QRect(left, y, text_width, metrics.height()), Qt.AlignmentFlag.AlignCenter,
                             metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, text_width))
            y += metrics.height() + 4
        lines = [(self.subtitle, MUTED)] if self.subtitle else []
        if self.message:
            lines.append((self.message, "#ff7b72" if self.message_is_error else ACCENT))
        metrics = QFontMetrics(line_font)
        painter.setFont(line_font)
        for text, colour in lines:
            painter.setPen(QColor(colour))
            painter.drawText(QRect(left, y, text_width, metrics.height()), Qt.AlignmentFlag.AlignCenter,
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_width))
            y += metrics.height() + 4
        painter.end()


class PlayerWindow(QWidget):
    """A window of its own, so it can sit beside the downloader or go fullscreen."""

    volume_changed = Signal(int)
    file_replaced = Signal(str, str)        # old path, new path, after a conversion
    download_requested = Signal(str, str)   # page URL, title: save what is streaming

    def __init__(self, logger: logging.Logger, volume: int = 80, icon: Any = None,
                 ffmpeg_locator: Callable[[], str | None] | None = None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.logger = logger
        self._find_ffmpeg = ffmpeg_locator or (lambda: None)
        self._transcoder: Transcoder | None = None
        self._probed: set[str] = set()          # files whose missing picture has been looked into
        self.setObjectName("playerRoot")
        self.setWindowTitle("Player — Video Batch Downloader")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(PLAYER_STYLE)
        self.setMinimumSize(560, 380)
        self.resize(1120, 660)

        self.items: list[PlayItem] = []
        self.current: PlayItem | None = None
        self.repeat = "off"
        self.shuffle = False
        self._shuffle_keys: list[str] = []  # play order while shuffle is on
        self.rate = 1.0
        self.autoplay = True                # when the queue ends, carry on with its radio
        self._radio_token = 0
        self._radio_seed = ""               # the song whose radio was last fetched
        self._radio_append_and_play = False
        self._radio_replace = False
        self._token = 0                     # stream resolves that finish late are ignored
        self._resolvers: set[StreamResolver] = set()
        self._want_play = False             # start once every part of the media has loaded
        self._announced: PlayItem | None = None   # logged once playback really got going
        self._was_maximized = False
        self._last_toggle = 0.0
        self._thumbs: dict[str, QPixmap] = {}
        self._net = QNetworkAccessManager(self)
        self._icon_font = self._pick_icon_font()

        self.audio_out = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_out)
        # A stream's soundtrack, when the site sends it apart from the picture.
        self.companion_out = QAudioOutput(self)
        self.companion = QMediaPlayer(self)
        self.companion.setAudioOutput(self.companion_out)
        try:
            # Keeps the voice at its own pitch while the drift is eased out.
            self.companion.setPitchCompensation(True)
        except (AttributeError, RuntimeError):
            pass
        self._companion_active = False

        self._build_ui()
        self.player.setVideoOutput(self.video)
        self._wire_player()
        self._set_volume(volume)
        self._install_shortcuts()
        self._refresh_queue()
        self._update_controls()

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(400)
        self._sync_timer.timeout.connect(self._sync_companion)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(CONTROLS_HIDE_MS)
        self._hide_timer.timeout.connect(self._hide_chrome)
        self._watch_video()

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _pick_icon_font() -> str:
        families = set(QFontDatabase.families())
        return next((name for name in ICON_FONTS if name in families), "")

    def _glyph(self, name: str) -> str:
        fluent, fallback = GLYPHS[name]
        return fluent if self._icon_font else fallback

    def _icon_button(self, glyph: str, tip: str, name: str = "icon", checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName(name)
        button.setText(self._glyph(glyph))
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _text_button(text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("text")
        button.setText(text)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        self.stage = QFrame()
        self.stage.setObjectName("stage")
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.setStyleSheet("background: #010409;")
        self.art = ArtView()
        if self._icon_font:
            self.art.glyph_font = QFont(self._icon_font)
        self.art.glyph = self._glyph("music")
        self.art.double_clicked.connect(self.toggle_fullscreen)
        self.art.action_clicked.connect(self._art_action)
        self.stack.addWidget(self.art)
        self.stack.addWidget(self.video)
        stage_layout.addWidget(self.stack)
        main.addWidget(self.stage, 1)

        self.controls = QFrame()
        self.controls.setObjectName("controls")
        cl = QVBoxLayout(self.controls)
        cl.setContentsMargins(16, 8, 16, 10)
        cl.setSpacing(4)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.time_label = QLabel("0:00")
        self.time_label.setObjectName("time")
        self.length_label = QLabel("0:00")
        self.length_label.setObjectName("time")
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
        self.seek.setObjectName("seek")
        self.seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seek.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek.seek_requested.connect(self._seek_to)
        self.seek.sliderMoved.connect(lambda value: self.time_label.setText(format_clock(value)))
        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.length_label)
        cl.addLayout(seek_row)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.prev_btn = self._icon_button("prev", "Previous (Ctrl+Left)")
        self.prev_btn.clicked.connect(self.previous)
        self.play_btn = self._icon_button("play", "Play / pause (Space)", name="play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn = self._icon_button("next", "Next (Ctrl+Right)")
        self.next_btn.clicked.connect(self.next)
        self.back_btn = self._text_button("−10", "Back 10 seconds (J)")
        self.back_btn.clicked.connect(lambda: self._skip(-10_000))
        self.fwd_btn = self._text_button("+10", "Forward 10 seconds (L)")
        self.fwd_btn.clicked.connect(lambda: self._skip(10_000))
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.back_btn)
        bar.addWidget(self.play_btn)
        bar.addWidget(self.fwd_btn)
        bar.addWidget(self.next_btn)
        bar.addSpacing(10)

        now = QVBoxLayout()
        now.setSpacing(0)
        self.now_title = ElidedLabel("Nothing playing")
        self.now_title.setObjectName("nowTitle")
        self.now_title.setMinimumWidth(80)
        self.now_sub = ElidedLabel("Play something from Downloads, History or Search, or open a file")
        self.now_sub.setObjectName("nowSub")
        now.addWidget(self.now_title)
        now.addWidget(self.now_sub)
        bar.addLayout(now, 1)

        self.download_btn = self._icon_button("download", "Download this (follows the Format setting)")
        self.download_btn.clicked.connect(self._download_current)
        self.shuffle_btn = self._icon_button("shuffle", "Shuffle: off (S)", checkable=True)
        self.shuffle_btn.toggled.connect(self._set_shuffle)
        self.radio_btn = self._icon_button("radio", "", checkable=True)
        self.radio_btn.setChecked(self.autoplay)
        self.radio_btn.toggled.connect(self._set_autoplay)
        self._set_autoplay(self.autoplay)
        self.speed_btn = self._text_button(speed_label(1.0), "Playback speed")
        speed_menu = QMenu(self.speed_btn)
        for rate in SPEEDS:
            speed_menu.addAction(speed_label(rate), lambda r=rate: self.set_speed(r))
        self.speed_btn.setMenu(speed_menu)
        self.speed_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.repeat_btn = self._icon_button("repeat", "Repeat: off", checkable=True)
        self.repeat_btn.clicked.connect(self._cycle_repeat)
        self.mute_btn = self._icon_button("volume", "Mute (M)")
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("volume")
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(80)
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume.valueChanged.connect(self._volume_moved)
        self.queue_btn = self._icon_button("queue", "Show the queue (Q)", checkable=True)
        self.queue_btn.setChecked(True)
        self.queue_btn.toggled.connect(self._toggle_queue)
        self.full_btn = self._icon_button("full", "Fullscreen (F)")
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        for widget in (self.download_btn, self.shuffle_btn, self.repeat_btn, self.speed_btn,
                       self.mute_btn, self.volume, self.queue_btn, self.full_btn):
            bar.addWidget(widget)
        cl.addLayout(bar)
        main.addWidget(self.controls)
        root.addLayout(main, 1)

        self.queue_panel = QFrame()
        self.queue_panel.setObjectName("queuePanel")
        self.queue_panel.setFixedWidth(300)
        ql = QVBoxLayout(self.queue_panel)
        ql.setContentsMargins(10, 10, 10, 10)
        ql.setSpacing(6)
        head = QHBoxLayout()
        self.queue_head = QLabel("UP NEXT")
        self.queue_head.setObjectName("queueHead")
        head.addWidget(self.queue_head, 1)
        head.addWidget(self.radio_btn)
        open_btn = self._icon_button("open", "Add files to the queue (Ctrl+O)")
        open_btn.clicked.connect(self.open_files)
        head.addWidget(open_btn)
        ql.addLayout(head)
        self.queue = QListWidget()
        self.queue.setObjectName("queue")
        self.queue.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.queue.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.queue.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.queue.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.queue.setWordWrap(False)
        self.queue.itemDoubleClicked.connect(lambda item: self.play_index(self.queue.row(item)))
        self.queue.model().rowsMoved.connect(lambda *_: self._queue_reordered())
        self.queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        ql.addWidget(self.queue, 1)
        self.queue_hint = QLabel("Double-click to play · drag to reorder · Del removes")
        self.queue_hint.setObjectName("nowSub")
        self.queue_hint.setWordWrap(True)
        ql.addWidget(self.queue_hint)
        root.addWidget(self.queue_panel)

    def _watch_video(self) -> None:
        # Double-clicks on the picture land on the video widget or the surface
        # inside it. Installing again is harmless: Qt keeps one filter per object.
        for widget in (self.video, *self.video.findChildren(QWidget)):
            widget.installEventFilter(self)

    def _install_shortcuts(self) -> None:
        context = Qt.ShortcutContext.WindowShortcut
        bindings: list[tuple[Any, Callable[[], None]]] = [
            (Qt.Key.Key_Space, self.toggle_play),
            (Qt.Key.Key_K, self.toggle_play),
            (Qt.Key.Key_MediaPlay, self.toggle_play),
            (Qt.Key.Key_MediaTogglePlayPause, self.toggle_play),
            (Qt.Key.Key_Right, lambda: self._skip(SEEK_STEP_MS)),
            (Qt.Key.Key_Left, lambda: self._skip(-SEEK_STEP_MS)),
            (Qt.Key.Key_L, lambda: self._skip(10_000)),
            (Qt.Key.Key_J, lambda: self._skip(-10_000)),
            (Qt.Key.Key_Up, lambda: self.volume.setValue(self.volume.value() + 5)),
            (Qt.Key.Key_Down, lambda: self.volume.setValue(self.volume.value() - 5)),
            (Qt.Key.Key_M, self.toggle_mute),
            (Qt.Key.Key_F, self.toggle_fullscreen),
            (Qt.Key.Key_F11, self.toggle_fullscreen),
            (Qt.Key.Key_Escape, self._leave_fullscreen),
            (Qt.Key.Key_Q, lambda: self.queue_btn.toggle()),
            (Qt.Key.Key_S, lambda: self.shuffle_btn.toggle()),
            (Qt.Key.Key_BracketLeft, lambda: self._step_speed(-1)),
            (Qt.Key.Key_BracketRight, lambda: self._step_speed(1)),
            (Qt.Key.Key_Delete, self._remove_selected),
            (Qt.Key.Key_MediaNext, self.next),
            (Qt.Key.Key_MediaPrevious, self.previous),
            (QKeySequence("Ctrl+Right"), self.next),
            (QKeySequence("Ctrl+Left"), self.previous),
            (QKeySequence("N"), self.next),
            (QKeySequence("P"), self.previous),
            (QKeySequence.StandardKey.Open, self.open_files),
        ]
        for key, slot in bindings:
            shortcut = QShortcut(key if isinstance(key, QKeySequence) else QKeySequence(key), self)
            shortcut.setContext(context)
            shortcut.activated.connect(slot)

    def _wire_player(self) -> None:
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(lambda _state: self._update_controls())
        self.player.mediaStatusChanged.connect(self._status_changed)
        self.player.errorOccurred.connect(self._error)
        self.player.hasVideoChanged.connect(lambda _has: self._choose_stage())
        self.player.metaDataChanged.connect(self._metadata_changed)
        self.companion.mediaStatusChanged.connect(self._companion_status)
        self.companion.errorOccurred.connect(self._companion_error)

    # -------------------------------------------------------------- queue
    def play_items(self, items: list[PlayItem], replace: bool = False) -> None:
        """Play the first of these now; any others follow it in the queue."""
        if not items:
            return
        if replace:
            self.stop()
            self.items = list(items)
            self._refresh_queue()
            self.play_index(0)
            return
        # New ones go straight after what is playing; ones already queued stay put.
        at = self.items.index(self.current) + 1 if self.current in self.items else len(self.items)
        for item in items:
            if self._index_of(item) < 0:
                self.items.insert(at, item)
                at += 1
        self._refresh_queue()
        self.play_index(self._index_of(items[0]))

    def enqueue(self, items: list[PlayItem]) -> int:
        added = [item for item in items if self._index_of(item) < 0]
        self.items.extend(added)
        self._refresh_queue()
        if self.current is None and added:
            self.play_index(self.items.index(added[0]))
        else:
            self._update_controls()
        return len(added)

    def _index_of(self, item: PlayItem) -> int:
        return next((i for i, existing in enumerate(self.items) if existing.key == item.key), -1)

    def _refresh_queue(self) -> None:
        self.queue.blockSignals(True)
        self.queue.clear()
        for item in self.items:
            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, item.key)
            self._label_row(row, item)
            self.queue.addItem(row)
        self.queue.blockSignals(False)
        count = len(self.items)
        self.queue_head.setText(f"UP NEXT  ·  {count}" if count else "UP NEXT")

    def _label_row(self, row: QListWidgetItem, item: PlayItem) -> None:
        playing = item is self.current
        kind = "Stream" if item.is_stream else ("Audio" if item.is_audio else "Video")
        row.setText(("▶  " if playing else "") + item.title)
        row.setToolTip(f"{item.title}\n{kind} · {item.path or item.page_url}")
        font = QFont(self.queue.font())
        font.setBold(playing)
        row.setFont(font)
        row.setForeground(QColor(ACCENT if playing else TEXT))

    def _restyle_queue(self) -> None:
        for row in range(self.queue.count()):
            if row < len(self.items):
                self._label_row(self.queue.item(row), self.items[row])

    def _queue_reordered(self) -> None:
        by_key = {item.key: item for item in self.items}
        order = [self.queue.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.queue.count())]
        self.items = [by_key[key] for key in order if key in by_key]
        self._update_controls()

    def _remove_selected(self) -> None:
        rows = sorted({self.queue.row(item) for item in self.queue.selectedItems()}, reverse=True)
        if not rows:
            return
        removing_current = any(self.items[row] is self.current for row in rows if row < len(self.items))
        for row in rows:
            if row < len(self.items):
                del self.items[row]
        if removing_current:
            self.stop()
            self.current = None
            self._show_idle()
        self._refresh_queue()
        self._update_controls()

    def _clear_queue(self) -> None:
        self.stop()
        self.items = []
        self.current = None
        self._show_idle()
        self._refresh_queue()
        self._update_controls()

    def _queue_menu(self, point: QPoint) -> None:
        row_item = self.queue.itemAt(point)
        menu = QMenu(self)
        if row_item is not None:
            row = self.queue.row(row_item)
            item = self.items[row] if row < len(self.items) else None
            menu.addAction("Play", lambda: self.play_index(row))
            if item is not None and item.path:
                menu.addAction("Show in folder",
                               lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.path).parent))))
            if item is not None and item.page_url.startswith("http"):
                menu.addAction("Open the source page", lambda: QDesktopServices.openUrl(QUrl(item.page_url)))
            if item is not None and video_id(item.webpage or item.page_url):
                menu.addAction("Start radio from this", lambda: self.start_radio(item))
            if item is not None and item.is_stream:
                menu.addAction("Download", lambda: self._download_item(item))
            menu.addAction("Remove from the queue", self._remove_selected)
            menu.addSeparator()
        menu.addAction("Add files…", self.open_files)
        if self.items:
            menu.addAction("Clear the queue", self._clear_queue)
        menu.exec(self.queue.viewport().mapToGlobal(point))

    def open_files(self) -> None:
        start = str(Path(self.current.path).parent) if self.current and self.current.path else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Add media files", start, MEDIA_FILTER)
        items = [PlayItem(title=Path(path).stem, path=path) for path in paths]
        if items:
            if self.current is None:
                self.play_items(items)
            else:
                self.enqueue(items)

    # ------------------------------------------------------------ playback
    def play_index(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        self.stop()
        self.current = item
        self._restyle_queue()
        self.queue.setCurrentRow(index)
        self.setWindowTitle(f"{item.title} — Player")
        self.now_title.setText(item.title)
        self.now_sub.setText(self._describe(item))
        self.art.glyph = self._glyph("music" if item.is_audio else "video")
        self.art.show_item(item.title, self._describe(item), self._thumb_for(item))
        self.art.set_message("")
        self._show_conversion_state(item)
        self._choose_stage()
        self._update_controls()
        if self._converting(item):
            return                  # the file is being rewritten; it plays when that is done
        self._probe(item)
        if item.path:
            if not Path(item.path).is_file():
                self.art.set_message("That file is no longer where it was saved.", error=True)
                self.stack.setCurrentWidget(self.art)
                return
            self._load(QUrl.fromLocalFile(item.path))
        elif item.resolved:
            self._load(QUrl(item.video_url), QUrl(item.audio_url) if item.audio_url else None)
        else:
            self._resolve(item)

    def _describe(self, item: PlayItem) -> str:
        if item.subtitle:
            return item.subtitle
        if item.path:
            return f"{'Audio' if item.is_audio else 'Video'} · {Path(item.path).name}"
        return "Streaming"

    def _resolve(self, item: PlayItem) -> None:
        self._token += 1
        self.stack.setCurrentWidget(self.art)
        self.art.set_message("Fetching the stream…")
        resolver = StreamResolver(self._token, item.page_url, item.audio_only, self.logger)
        resolver.resolved.connect(self._stream_ready)
        resolver.failed.connect(self._stream_failed)
        resolver.finished.connect(lambda r=resolver: self._resolvers.discard(r))
        resolver.finished.connect(resolver.deleteLater)
        self._resolvers.add(resolver)
        resolver.start()

    def _stream_ready(self, token: int, data: dict) -> None:
        item = self.current
        if token != self._token or item is None or not item.is_stream:
            return
        item.video_url, item.audio_url = data["video_url"], data["audio_url"]
        item.has_video = bool(data["has_video"])
        item.webpage = data.get("webpage") or item.webpage
        item.resolved_at = time.time()
        if data.get("title") and (not item.title or item.title == item.page_url):
            item.title = data["title"]
            self.now_title.setText(item.title)
        if data.get("thumbnail") and not item.thumbnail:
            item.thumbnail = data["thumbnail"]
        if data.get("uploader") and not item.subtitle:
            item.subtitle = f"Streaming · {data['uploader']}"
            self.now_sub.setText(item.subtitle)
        self.art.show_item(item.title, self._describe(item), self._thumb_for(item))
        self.art.set_message("")
        self._restyle_queue()
        self._load(QUrl(item.video_url), QUrl(item.audio_url) if item.audio_url else None)

    def _stream_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self.art.set_message(f"Can't stream this: {message}", error=True)
        self.stack.setCurrentWidget(self.art)
        self._update_controls()

    def _load(self, source: QUrl, audio: QUrl | None = None) -> None:
        self._want_play = True
        self.player.setPlaybackRate(self.rate)
        self.companion.setPlaybackRate(self.rate)
        self._companion_active = audio is not None
        if audio is not None:
            self.companion.setSource(audio)
        self.player.setSource(source)
        self._watch_video()
        self._choose_stage()
        self._maybe_start()

    def _ready(self, player: QMediaPlayer) -> bool:
        return player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                                        QMediaPlayer.MediaStatus.BufferingMedia)

    def _maybe_start(self) -> None:
        if not self._want_play or not self._ready(self.player):
            return
        if self._companion_active and not self._ready(self.companion):
            return
        self._want_play = False
        self.play()

    def play(self) -> None:
        if self.current is None and self.items:
            self.play_index(0)
            return
        if self.player.source().isEmpty():
            if self.current is not None:
                self.play_index(self.items.index(self.current) if self.current in self.items else 0)
            return
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self._seek_to(0)
        self.player.play()
        if self._companion_active:
            self.companion.setPosition(self.player.position())
            self.companion.play()
            self._sync_timer.start()

    def pause(self) -> None:
        self.player.pause()
        if self._companion_active:
            self.companion.pause()
        self._sync_timer.stop()

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._token += 1            # a stream still resolving is no longer wanted
        self._want_play = False
        self._sync_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.companion.stop()
        self.companion.setSource(QUrl())
        self.companion.setPlaybackRate(1.0)
        self._companion_active = False
        self.seek.setRange(0, 0)
        self.time_label.setText("0:00")
        self.length_label.setText("0:00")

    def _order(self) -> list[int]:
        """Queue positions in the order they play: as listed, or shuffled."""
        if not self.shuffle:
            return list(range(len(self.items)))
        keys = [item.key for item in self.items]
        if sorted(self._shuffle_keys) != sorted(keys):
            # New or removed entries: shuffle again, keeping what plays now first.
            current = self.current.key if self.current in self.items else ""
            rest = [key for key in keys if key != current]
            random.shuffle(rest)
            self._shuffle_keys = ([current] if current else []) + rest
        position = {key: i for i, key in enumerate(keys)}
        return [position[key] for key in self._shuffle_keys]

    def _neighbour(self, step: int) -> int:
        """The queue index [step] places away in play order, or -1 at either end."""
        order = self._order()
        if not order:
            return -1
        if self.current not in self.items:
            return order[0]
        at = order.index(self.items.index(self.current)) + step
        if 0 <= at < len(order):
            return order[at]
        if self.repeat == "all":
            return order[at % len(order)]
        return -1

    def next(self) -> None:
        index = self._neighbour(1)
        if index >= 0:
            self.play_index(index)
        elif self.current is not None:
            self._autoplay_radio(play_next=True)

    def previous(self) -> None:
        # Like most players: back to the start first, then the previous item.
        if self.player.position() > 3000 or self.current not in self.items:
            self._seek_to(0)
            return
        index = self._neighbour(-1)
        if index >= 0:
            self.play_index(index)
        else:
            self._seek_to(0)

    def _seek_to(self, position: int) -> None:
        self.player.setPosition(position)
        if self._companion_active:
            self.companion.setPosition(position)
        self.time_label.setText(format_clock(position))

    def _skip(self, delta: int) -> None:
        if self.player.isSeekable():
            duration = self.player.duration() or 0
            self._seek_to(max(0, min(duration, self.player.position() + delta)))

    def _sync_companion(self) -> None:
        if not self._companion_active:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        stalled = self.player.mediaStatus() in (QMediaPlayer.MediaStatus.StalledMedia,
                                                QMediaPlayer.MediaStatus.BufferingMedia)
        if playing and stalled:
            if self.companion.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.companion.pause()
            return
        if playing and self.companion.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.companion.play()
        drift = self.companion.position() - self.player.position()     # > 0: sound is ahead
        if abs(drift) > SYNC_JUMP_MS:
            self.companion.setPosition(self.player.position())
            self.companion.setPlaybackRate(self.player.playbackRate())
        elif abs(drift) > SYNC_NUDGE_MS:
            nudge = -SYNC_NUDGE_RATE if drift > 0 else SYNC_NUDGE_RATE
            self.companion.setPlaybackRate(self.player.playbackRate() * (1 + nudge))
        elif abs(drift) < SYNC_IN_STEP_MS:
            self.companion.setPlaybackRate(self.player.playbackRate())

    def shutdown(self) -> None:
        self.stop()
        if self._transcoder is not None and self._transcoder.isRunning():
            self._transcoder.cancel()
            self._transcoder.wait(5000)
        for resolver in list(self._resolvers):
            resolver.wait(2000)

    # ---------------------------------------------------------- feedback
    def _status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._choose_stage()        # whether there is a picture is only certain now
            self._maybe_start()
            self._check_picture()
            if (status == QMediaPlayer.MediaStatus.BufferedMedia and self.current is not None
                    and self._announced is not self.current
                    and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
                self._announced = self.current
                self.logger.info("Playing %s (%s, %s)", self.current.path or self.current.page_url,
                                 "video" if self.player.hasVideo() else "audio only",
                                 "separate audio stream" if self._companion_active else "single source")
            if self.art.message and not self.art.message_is_error:
                self.art.set_message("")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._finished()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.art.set_message("This file can't be played.", error=True)
            self.stack.setCurrentWidget(self.art)
        self._update_controls()

    # ------------------------------------------------- undecodable video
    def _probe(self, item: PlayItem) -> None:
        """Before playing a file, find out whether its picture can be shown here."""
        if not item.path or item.is_audio or item.key in self._probed:
            self._show_conversion_state(item)
            return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return                  # cannot tell yet; _check_picture looks again once it loads
        self._probed.add(item.key)
        codec = video_codec(ffmpeg, item.path)
        item.codec = codec if codec and not can_decode(codec) else ""
        self._show_conversion_state(item)
        self._choose_stage()

    def _check_picture(self) -> None:
        """Explain a picture that did not come, when probing could not foresee it."""
        item = self.current
        if item is None or item.is_audio or item.codec or self.player.hasVideo():
            return
        if item.is_stream:
            if item.has_video:
                self.art.set_message("This stream's video format can't be shown here; playing the sound only.",
                                     error=True)
            return
        if not self._find_ffmpeg():
            self._probed.add(item.key)
            self._show_conversion_state(item)

    def _show_conversion_state(self, item: PlayItem) -> None:
        codec = item.codec
        if self._converting(item):
            self.art.set_message("Converting to H.264…  0%")
            self.art.set_action("Cancel")
        elif codec:
            self.art.set_message(f"This video is {codec_label(codec)}, which this PC can't show here. "
                                 "Converting it to H.264 makes it play everywhere.", error=True)
            self.art.set_action("Convert to H.264")
        elif item.path and not item.is_audio and item.key in self._probed and not self._find_ffmpeg():
            self.art.set_message("This video's format can't be shown here. Get FFmpeg in Settings to convert it.",
                                 error=True)
            self.art.set_action("")
        else:
            self.art.set_action("")

    def _converting(self, item: PlayItem | None) -> bool:
        return (item is not None and self._transcoder is not None
                and self._transcoder.isRunning() and item.path == str(self._transcoder.source))

    def _art_action(self) -> None:
        item = self.current
        if item is None:
            return
        if self._converting(item):
            self._transcoder.cancel()
            return
        if self._transcoder is not None and self._transcoder.isRunning():
            self.art.set_message("Another video is being converted; try again when it is done.", error=True)
            return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return
        duration = self.player.duration()
        self.stop()                 # Windows will not replace a file that is open
        transcoder = Transcoder(ffmpeg, item.path, duration, self.logger)
        transcoder.progress.connect(self._conversion_progress)
        transcoder.done.connect(self._conversion_done)
        transcoder.failed.connect(self._conversion_failed)
        transcoder.finished.connect(transcoder.deleteLater)
        self._transcoder = transcoder
        transcoder.start()
        self.stack.setCurrentWidget(self.art)
        self._show_conversion_state(item)

    def _conversion_progress(self, percent: int) -> None:
        if self._converting(self.current):
            self.art.set_message(f"Converting to H.264…  {percent}%")

    def _conversion_done(self, old: str, new: str) -> None:
        self._transcoder = None
        for item in self.items:
            if item.path == old:
                item.path = new
                item.codec = ""
        self.file_replaced.emit(old, new)
        self._refresh_queue()
        current = self.current
        if current is not None and current.path == new and current in self.items:
            self.play_index(self.items.index(current))

    def _conversion_failed(self, old: str, reason: str) -> None:
        self._transcoder = None
        current = self.current
        if current is None or current.path != old:
            return
        self._show_conversion_state(current)
        if reason:
            self.art.set_message(f"Conversion failed: {reason}", error=True)
            self.art.set_action("Try again")

    def _companion_status(self, _status: QMediaPlayer.MediaStatus) -> None:
        self._maybe_start()

    def _finished(self) -> None:
        self._sync_timer.stop()
        if self._companion_active:
            self.companion.pause()
        if self.repeat == "one":
            self._seek_to(0)
            self.play()
            return
        index = self._neighbour(1)
        if index >= 0:
            self.play_index(index)
        else:
            self._autoplay_radio(play_next=True)

    def _error(self, _error: QMediaPlayer.Error, message: str) -> None:
        item = self.current
        self.logger.warning("Player error on %s: %s", item.path or item.page_url if item else "?", message)
        if item is not None and item.is_stream:
            item.forget_stream()        # an expired link is the usual cause; fetch afresh next time
        self.art.set_message(f"Playback failed: {message}" if message else "Playback failed.", error=True)
        self.stack.setCurrentWidget(self.art)
        self._update_controls()

    def _companion_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        self.logger.warning("Player audio error: %s", message)
        self._companion_active = False
        self.now_sub.setText("Playing without sound: the audio stream failed")

    def _position_changed(self, position: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
            self.time_label.setText(format_clock(position))

    def _duration_changed(self, duration: int) -> None:
        self.seek.setRange(0, max(0, duration))
        self.length_label.setText(format_clock(duration))

    def _choose_stage(self) -> None:
        item = self.current
        if item is None:
            self.stack.setCurrentWidget(self.art)
            return
        if item.is_audio:
            show_video = False
        elif not self.player.source().isEmpty() and self.player.mediaStatus() not in (
                QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.NoMedia):
            show_video = self.player.hasVideo()
        else:
            show_video = not item.is_stream and not item.is_audio
        if self.art.message_is_error or item.codec or self._converting(item):
            show_video = False
        self.stack.setCurrentWidget(self.video if show_video else self.art)

    def _metadata_changed(self) -> None:
        item = self.current
        if item is None or item.thumbnail:
            return
        data = self.player.metaData()
        for key in (QMediaMetaData.Key.CoverArtImage, QMediaMetaData.Key.ThumbnailImage):
            image = data.value(key)
            if isinstance(image, QImage) and not image.isNull():
                self.art.show_item(item.title, self._describe(item), QPixmap.fromImage(image))
                return

    def _show_idle(self) -> None:
        self.setWindowTitle("Player — Video Batch Downloader")
        self.now_title.setText("Nothing playing")
        self.now_sub.setText("Play something from Downloads, History or Search, or open a file")
        self.art.show_item("", "", None)
        self.art.set_message("")
        self.stack.setCurrentWidget(self.art)

    def _update_controls(self) -> None:
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText(self._glyph("pause" if playing else "play"))
        self.play_btn.setEnabled(bool(self.items))
        index = self.items.index(self.current) if self.current in self.items else -1
        self.prev_btn.setEnabled(index >= 0)
        self.next_btn.setEnabled(0 <= index and (self._neighbour(1) >= 0 or self._can_autoplay()))
        self.back_btn.setEnabled(index >= 0)
        self.fwd_btn.setEnabled(index >= 0)
        streaming = self.current is not None and self.current.is_stream
        self.download_btn.setVisible(streaming)
        self.seek.setEnabled(self.player.isSeekable())
        if self.isFullScreen() and not playing:
            self._show_chrome()

    # ------------------------------------------------------------- volume
    def _set_volume(self, value: int) -> None:
        self.volume.setValue(max(0, min(100, int(value))))
        self._volume_moved(self.volume.value())

    def _volume_moved(self, value: int) -> None:
        # Ears hear loudness on a curve; a squared slider feels even across its length.
        level = (value / 100) ** 2
        self.audio_out.setVolume(level)
        self.companion_out.setVolume(level)
        if value and self.audio_out.isMuted():
            self._mute(False)
        self._update_mute_icon()
        self.volume_changed.emit(value)

    def toggle_mute(self) -> None:
        self._mute(not self.audio_out.isMuted())

    def _mute(self, muted: bool) -> None:
        self.audio_out.setMuted(muted)
        self.companion_out.setMuted(muted)
        self._update_mute_icon()

    def _update_mute_icon(self) -> None:
        silent = self.audio_out.isMuted() or self.volume.value() == 0
        self.mute_btn.setText(self._glyph("mute" if silent else "volume"))
        self.mute_btn.setToolTip("Unmute (M)" if silent else "Mute (M)")

    # --------------------------------------------- shuffle, speed, radio
    def _set_shuffle(self, on: bool) -> None:
        self.shuffle = on
        self._shuffle_keys = []
        self.shuffle_btn.setToolTip("Shuffle: on (S)" if on else "Shuffle: off (S)")
        self._update_controls()

    def set_speed(self, rate: float) -> None:
        self.rate = rate
        self.player.setPlaybackRate(rate)
        if self._companion_active:
            self.companion.setPlaybackRate(rate)
        self.speed_btn.setText(speed_label(rate))

    def _step_speed(self, step: int) -> None:
        at = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self.rate))
        self.set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, at + step))])

    def _set_autoplay(self, on: bool) -> None:
        self.autoplay = on
        self.radio_btn.setToolTip("Autoplay: on. When the queue ends, similar songs keep playing"
                                  if on else "Autoplay: off. Playback stops at the end of the queue")
        self._update_controls()

    def _can_autoplay(self) -> bool:
        item = self.current
        return bool(self.autoplay and item is not None and item.is_stream
                    and video_id(item.webpage or item.page_url))

    def _autoplay_radio(self, play_next: bool) -> None:
        """At the end of the queue, with autoplay on, line up the last song's radio."""
        if not self._can_autoplay():
            return
        item = self.current
        if self._radio_seed == item.key:
            return
        self._fetch_radio(item, replace_rest=False, play_next=play_next)

    def start_radio(self, item: PlayItem | None = None) -> None:
        """Keep [item] (or what plays now) and replace what follows with its radio."""
        item = item or self.current
        if item is None:
            return
        if item is not self.current and item in self.items:
            self.play_index(self.items.index(item))
        self._fetch_radio(item, replace_rest=True, play_next=False)

    def _fetch_radio(self, item: PlayItem, replace_rest: bool, play_next: bool) -> None:
        vid = video_id(item.webpage or item.page_url)
        if not vid:
            return
        self._radio_seed = item.key
        self._radio_token += 1
        self._radio_replace = replace_rest
        self._radio_append_and_play = play_next
        self.now_sub.setText("Finding songs like this…")
        fetcher = RadioFetcher(self._radio_token, vid, self.logger)
        fetcher.found.connect(lambda token, entries, it=item: self._radio_found(token, entries, it))
        fetcher.finished.connect(lambda f=fetcher: self._resolvers.discard(f))
        self._resolvers.add(fetcher)
        fetcher.start()

    def _radio_found(self, token: int, entries: list, seed: PlayItem) -> None:
        if token != self._radio_token:
            return
        self.now_sub.setText(self._describe(self.current) if self.current else "")
        known = {item.key for item in self.items}
        fresh = [PlayItem(title=title, page_url=url, thumbnail=thumb, audio_only=seed.audio_only,
                          subtitle="Radio · YouTube") for url, title, thumb in entries if url not in known]
        if not fresh:
            self.now_sub.setText("No similar songs were found.")
            return
        if self._radio_replace and seed in self.items:
            del self.items[self.items.index(seed) + 1:]
            self._shuffle_keys = []
        start = len(self.items)
        self.items.extend(fresh)
        self._refresh_queue()
        self._restyle_queue()
        if self._radio_append_and_play:
            self._radio_append_and_play = False
            self.play_index(start)
        else:
            self._update_controls()

    def _download_current(self) -> None:
        if self.current is not None:
            self._download_item(self.current)

    def _download_item(self, item: PlayItem) -> None:
        url = item.webpage or item.page_url
        if url:
            self.download_requested.emit(url, item.title)

    def _cycle_repeat(self) -> None:
        self.repeat = REPEAT_MODES[(REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)]
        self.repeat_btn.setChecked(self.repeat != "off")
        self.repeat_btn.setText(self._glyph("repeat1" if self.repeat == "one" else "repeat"))
        self.repeat_btn.setToolTip({"off": "Repeat: off", "all": "Repeat: the whole queue",
                                    "one": "Repeat: this one"}[self.repeat])
        self._update_controls()

    # --------------------------------------------------------- fullscreen
    def toggle_fullscreen(self) -> None:
        # A double-click can reach both the video surface and the window.
        if time.monotonic() - self._last_toggle < 0.35:
            return
        self._last_toggle = time.monotonic()
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._was_maximized = self.isMaximized()
            self.queue_panel.setVisible(False)
            # Any mouse movement brings the controls back, wherever it lands;
            # only watched while fullscreen, so normal use pays nothing for it.
            QApplication.instance().installEventFilter(self)
            self.showFullScreen()
            self.full_btn.setText(self._glyph("unfull"))
            self.full_btn.setToolTip("Exit fullscreen (F / Esc)")
            self._hide_timer.start()

    def _leave_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self._hide_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._show_chrome()
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.queue_panel.setVisible(self.queue_btn.isChecked())
        self.full_btn.setText(self._glyph("full"))
        self.full_btn.setToolTip("Fullscreen (F)")

    def _toggle_queue(self, shown: bool) -> None:
        if not self.isFullScreen():
            self.queue_panel.setVisible(shown)

    def _hide_chrome(self) -> None:
        if self.isFullScreen() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.controls.setVisible(False)
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.video.setCursor(Qt.CursorShape.BlankCursor)

    def _show_chrome(self) -> None:
        self.controls.setVisible(True)
        self.unsetCursor()
        self.video.unsetCursor()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseMove and self.isFullScreen():
            if not self.controls.isVisible():
                self._show_chrome()
            self._hide_timer.start()
        elif (kind == QEvent.Type.MouseButtonDblClick and isinstance(watched, QWidget)
              and (watched is self.video or self.video.isAncestorOf(watched))):
            self.toggle_fullscreen()
            return True
        return False

    def closeEvent(self, event: Any) -> None:
        # Closing the window stops the sound; the queue stays for next time.
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        if self.isFullScreen():
            self._leave_fullscreen()
        super().closeEvent(event)

    # ------------------------------------------------------------ artwork
    def _thumb_for(self, item: PlayItem) -> QPixmap | None:
        if not item.thumbnail:
            return None
        cached = self._thumbs.get(item.thumbnail)
        if cached is not None:
            return cached
        url = item.thumbnail
        reply = self._net.get(QNetworkRequest(QUrl(url)))

        def done() -> None:
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(reply.readAll()):
                        self._thumbs[url] = pixmap
                        if self.current is not None and self.current.thumbnail == url:
                            self.art.show_item(self.current.title, self._describe(self.current), pixmap)
            finally:
                reply.deleteLater()

        reply.finished.connect(done)
        return None
