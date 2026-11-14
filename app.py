"""PySide6 front end for batch video downloads."""

from __future__ import annotations

import datetime
import json
import logging
import re
import sys
import threading
from collections import Counter
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QByteArray, QEvent, QModelIndex, QRect, QRectF, QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QBrush, QCloseEvent, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont,
    QFontMetrics, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest, QSslSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QDoubleSpinBox, QProgressDialog, QScrollArea, QSpinBox, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from downloader import (
    AUDIO_FORMATS, DEFAULT_SUBTITLE_LANGS, EMBED_SUBTITLE_MODES, LOSSLESS_AUDIO, YT_DLP_IMPORT_ERROR,
    DownloadConfig, DownloadJob, DownloadManager, PlaylistEntry, clean_error, expand_playlist,
    find_ffmpeg, is_search_query, looks_like_playlist, subtitle_languages, yt_dlp,
)
import ffmpeg_setup
from search import MAX_RESULTS, SEARCH_SITES, SearchResult, format_duration, format_views, search_videos
from spotify import (
    DEFAULT_MATCH_SOURCE, MATCH_SOURCES, SEARCH_KINDS, SpotifyCredentials, SpotifyError,
    looks_like_spotify, search_spotify, spotify_tracks,
)


FROZEN = bool(getattr(sys, "frozen", False))
# Bundled read-only assets live in the PyInstaller extraction dir; user data sits next to the exe.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "download.log"
HISTORY_FILE = APP_DIR / "download_history.json"
ICON_ICO = BUNDLE_DIR / "assets" / "app_icon.ico"
ICON_PNG = BUNDLE_DIR / "assets" / "app_icon.png"
UI_ASSETS = BUNDLE_DIR / "assets" / "ui"

HISTORY_TAB = 2
# Most events a single poll may handle, so a busy batch cannot starve repaints.
EVENTS_PER_TICK = 500
# Entries kept on disk and in the History table. A few long playlists would
# otherwise grow the file without limit, and every redraw with it.
HISTORY_LIMIT = 2000

# Marks a Search-tab source as Spotify rather than a yt-dlp search prefix.
SPOTIFY_PREFIX = "spotify:"
QUEUE_FILTERS = ("All", "Active", "Done", "Failed")
TERMINAL = {"Completed", "Failed", "Cancelled", "Skipped"}
RETRYABLE = {"Failed", "Cancelled"}
STATUS_COLORS = {
    "Completed": "#7ee787",
    "Skipped": "#79c0ff",
    "Failed": "#ff7b72",
    "Cancelled": "#ffa657",
    "Downloading": "#58a6ff",
    "Waiting": "#d29922",
    "Invalid": "#8b949e",
    "Queued": "#c9d1d9",
}
TEXT = "#c9d1d9"
MUTED = "#8b949e"
BRIGHT = "#f0f6fc"
# Card surfaces, kept beside the status colours they sit against.
CARD_BG = "#161b22"
CARD_HOVER = "#1b2129"
CARD_SELECTED = "#1c2b3d"
CARD_BORDER = "#2a3038"
ART_BG = "#21262d"
TRACK_BG = "#21262d"
ACTION_BG = "#21262d"
ACTION_HOVER = "#2d343d"

# Hostname fragment -> what to call it on a card.
SOURCE_NAMES: list[tuple[str, str]] = [
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"), ("instagram.com", "Instagram"),
    ("tiktok.com", "TikTok"), ("twitter.com", "X"), ("x.com", "X"), ("facebook.com", "Facebook"),
    ("soundcloud.com", "SoundCloud"), ("vimeo.com", "Vimeo"), ("bilibili.com", "Bilibili"),
    ("twitch.tv", "Twitch"), ("reddit.com", "Reddit"), ("dailymotion.com", "Dailymotion"),
    ("spotify.com", "Spotify"),
]


def source_label(url: str) -> str:
    """A short, friendly name for where a download comes from."""
    if is_search_query(url):
        prefix = url.split(":", 1)[0].lower()
        return "SoundCloud match" if prefix.startswith("scsearch") else "YouTube match"
    host = urlparse(url).netloc.lower()
    if not host:
        return "Link"
    for fragment, name in SOURCE_NAMES:
        if fragment in host:
            return name
    return host[4:] if host.startswith("www.") else host

# Combo label -> DownloadConfig.audio_format ("" keeps the video pipeline).
FORMAT_CHOICES: list[tuple[str, str]] = [
    ("Video (MP4)", ""),
    ("Audio: MP3", "mp3"),
    ("Audio: M4A", "m4a"),
    ("Audio: Opus", "opus"),
    ("Audio: FLAC", "flac"),
    ("Audio: WAV", "wav"),
]
AUDIO_BITRATES = ["320", "256", "192", "128", "96"]

# Combo label -> DownloadConfig.subtitle_mode ("" leaves subtitles alone).
SUBTITLE_CHOICES: list[tuple[str, str]] = [
    ("No subtitles", ""),
    ("Save as .srt file", "file"),
    ("Embed in the video", "embed"),
    ("Embed and keep the file", "both"),
]


def MONO_FONT() -> QFont:
    font = QFont()
    font.setFamilies(["Cascadia Mono", "Consolas", "Courier New", "monospace"])
    font.setPointSize(9)
    return font

STYLE = """
QMainWindow { background: #0d1117; }
QWidget { color: #c9d1d9; font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; }
QLabel, QCheckBox, QRadioButton { background: transparent; }

QTabWidget::pane { border: 1px solid #30363d; border-radius: 10px; background: #161b22; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #8b949e; padding: 8px 18px; margin-right: 4px; border: none; border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: #f0f6fc; border-bottom: 2px solid #58a6ff; }
QTabBar::tab:hover:!selected { color: #c9d1d9; }

QGroupBox { border: 1px solid #30363d; border-radius: 8px; margin-top: 16px; padding: 14px 10px 10px 10px; background: #1b2028; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: 3px; padding: 0 6px; color: #8b949e; background: #161b22; border-radius: 4px; font-weight: 600; }

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: #0d1117; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px; padding: 6px 9px; selection-background-color: #1f6feb; selection-color: #ffffff; }
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #3d444d; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #58a6ff; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #6e7681; background: #12171e; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@ui/arrow_down.png); width: 12px; height: 8px; margin-right: 6px; }
QComboBox::down-arrow:disabled { image: url(@ui/arrow_down_dim.png); }
QComboBox QAbstractItemView { background: #161b22; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px; padding: 4px; selection-background-color: #1f6feb; outline: none; }
QSpinBox { padding-right: 24px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 22px; border: none; background: transparent; border-radius: 3px; }
QSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #21262d; }
QSpinBox::up-arrow { image: url(@ui/arrow_up.png); width: 12px; height: 8px; }
QSpinBox::down-arrow { image: url(@ui/arrow_down.png); width: 12px; height: 8px; }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off { image: url(@ui/arrow_up_dim.png); }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off { image: url(@ui/arrow_down_dim.png); }

QPushButton { background: #21262d; color: #e6edf3; border: 1px solid #363c45; border-radius: 6px; padding: 7px 16px; font-weight: 600; }
QPushButton:hover { background: #2b313a; border-color: #8b949e; }
QPushButton:pressed { background: #1c2128; }
QPushButton:disabled { color: #545d68; background: #161b22; border-color: #21262d; }
QPushButton#primary { background: #238636; border-color: #2ea043; color: #ffffff; }
QPushButton#primary:hover { background: #2ea043; }
QPushButton#primary:pressed { background: #1f7a2f; }
QPushButton#primary:disabled { background: #1a3a22; border-color: #1a3a22; color: #5c7a63; }
QPushButton#danger { background: #b62324; border-color: #da3633; color: #ffffff; }
QPushButton#danger:hover { background: #da3633; }
QPushButton#danger:disabled { background: #3a1b1b; border-color: #3a1b1b; color: #7a4a4a; }
QPushButton#warn { background: #9e6a03; border-color: #bb8009; color: #ffffff; }
QPushButton#warn:hover { background: #bb8009; }
QPushButton#warn:disabled { background: #3a2c0a; border-color: #3a2c0a; color: #7a6540; }
QPushButton#small { padding: 3px 10px; font-size: 9pt; font-weight: 500; }
QPushButton#chip { background: transparent; color: #8b949e; border: 1px solid #30363d; border-radius: 13px; padding: 4px 14px; font-weight: 600; font-size: 9pt; }
QPushButton#chip:hover { color: #c9d1d9; border-color: #8b949e; }
QPushButton#chip:checked { background: #1f6feb; border-color: #58a6ff; color: #ffffff; }

QFrame#panel { background: #1b2028; border: 1px solid #30363d; border-radius: 10px; }
QFrame#panel QPlainTextEdit { background: #0d1117; }
QListWidget#cards { background: transparent; border: none; outline: none; }
QListWidget#cards::item { border: none; background: transparent; }
QListWidget#cards::item:selected { background: transparent; }

QTableWidget { background: #0d1117; alternate-background-color: #11161d; color: #c9d1d9; border: 1px solid #30363d; border-radius: 8px; gridline-color: #21262d; selection-background-color: #1c2b3d; selection-color: #f0f6fc; outline: none; }
QTableWidget::item { padding: 4px 10px; border: none; }
QTableWidget::item:hover { background: #161b22; }
QTableWidget::item:selected { background: #1c2b3d; }
QHeaderView { background: transparent; }
QHeaderView::section { background: #161b22; color: #8b949e; border: none; border-bottom: 1px solid #30363d; padding: 7px 10px; font-weight: 600; font-size: 9pt; }
QHeaderView::section:first { border-top-left-radius: 8px; }
QHeaderView::section:last { border-top-right-radius: 8px; }
QTableCornerButton::section { background: #161b22; border: none; }

QProgressBar { background: #21262d; border: none; border-radius: 5px; text-align: center; color: #e6edf3; font-size: 9pt; min-height: 12px; max-height: 12px; }
QProgressBar::chunk { background: #58a6ff; border-radius: 5px; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #3d444d; border-radius: 4px; background: #0d1117; }
QCheckBox::indicator:hover { border-color: #8b949e; }
QCheckBox::indicator:checked { background: #1f6feb; border-color: #58a6ff; image: url(@ui/check.png); }
QCheckBox::indicator:checked:hover { background: #388bfd; }
QTableWidget::indicator { width: 16px; height: 16px; border: 1px solid #3d444d; border-radius: 4px; background: #0d1117; }
QTableWidget::indicator:hover { border-color: #8b949e; }
QTableWidget::indicator:checked { background: #1f6feb; border-color: #58a6ff; image: url(@ui/check.png); }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #30363d; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #484f58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #30363d; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; width: 0; }

QLabel#title { font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif; font-size: 20pt; font-weight: 600; color: #f0f6fc; letter-spacing: -0.3px; }
QLabel#muted { color: #8b949e; }
QLabel#mono { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; }

QMenu { background: #161b22; color: #e6edf3; border: 1px solid #30363d; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: #1f6feb; color: #ffffff; }
QMenu::separator { height: 1px; background: #30363d; margin: 4px 8px; }

QToolTip { background: #161b22; color: #e6edf3; border: 1px solid #30363d; padding: 5px 8px; border-radius: 4px; }
QMessageBox, QDialog { background: #161b22; }
QMessageBox QLabel { color: #e6edf3; }
"""


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("video_batch_downloader")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def parse_urls(text: str) -> list[str]:
    """Split mixed whitespace/comma input, retaining valid URL order and uniqueness."""
    values = re.split(r"[\s,]+", text)
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = value.strip()
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def is_basic_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and "." in parsed.netloc
    except ValueError:
        return False


def is_queueable(url: str) -> bool:
    """A target yt-dlp can take: a real link, or a search the app queued itself."""
    return is_basic_url(url) or is_search_query(url)


def format_eta(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    if minutes:
        return f"{minutes:d}:{secs:02d}"
    return f"{secs}s"


def format_bytes(value: Any) -> str:
    number = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} GB"


def job_detail(job: DownloadJob) -> str:
    if job.status == "Downloading":
        if job.total_bytes:
            amount = f"{format_bytes(job.downloaded_bytes)} / {format_bytes(job.total_bytes)}"
            percent = f"{job.progress:.0%}"
        else:
            amount, percent = format_bytes(job.downloaded_bytes), "…"
        speed = f"{format_bytes(job.speed)}/s" if job.speed else "—"
        return f"{percent:>4}  {amount} • {speed} • ETA {format_eta(job.eta)}"
    if job.status == "Completed":
        if job.media_count > 1:
            done = f"Done  •  {job.media_count} files"
        else:
            size = format_bytes(job.total_bytes or job.downloaded_bytes)
            done = f"Done  •  {size}" if job.total_bytes or job.downloaded_bytes else "Done"
        return f"{done}  •  no subtitles" if job.note else done
    if job.status == "Skipped":
        return "Already downloaded"
    if job.status == "Waiting":
        return "Holding off — the site is rate limiting"
    if job.status == "Cancelled":
        return "Cancelled"
    if job.status == "Invalid":
        return "Not a valid http(s) URL"
    if job.status == "Failed":
        return job.error or "Failed"
    return "Waiting…"


def default_output_dir() -> str:
    """A folder under Videos; the app's own directory is a poor default once
    the app is installed under Program Files or LocalAppData."""
    for location in (QStandardPaths.StandardLocation.MoviesLocation,
                     QStandardPaths.StandardLocation.DownloadLocation):
        base = QStandardPaths.writableLocation(location)
        if base:
            return str(Path(base) / "Video Batch Downloader")
    return str(APP_DIR / "downloads")


def app_icon() -> QIcon:
    for path in (ICON_ICO, ICON_PNG):
        if path.is_file():
            return QIcon(str(path))
    return QIcon()


class SearchWorker(QThread):
    finished_ok = Signal(int, list)
    failed = Signal(int, str)

    def __init__(self, generation: int, query: str, prefix: str, limit: int,
                 logger: logging.Logger, credentials: Any = None) -> None:
        super().__init__()
        self.generation, self.query, self.prefix, self.limit, self.logger = generation, query, prefix, limit, logger
        self.credentials = credentials

    def run(self) -> None:
        try:
            if self.prefix.startswith(SPOTIFY_PREFIX):
                results = self._spotify(self.prefix[len(SPOTIFY_PREFIX):])
            else:
                results = search_videos(self.query, self.prefix, self.limit, self.logger)
            self.finished_ok.emit(self.generation, results)
        except Exception as exc:
            self.failed.emit(self.generation, clean_error(exc) or exc.__class__.__name__)

    def _spotify(self, kind: str) -> list[SearchResult]:
        """Spotify's own results, shaped like every other search result.

        The URL kept is the Spotify page: queueing it goes through the same
        expansion a pasted Spotify link does, so one album becomes its tracks.
        """
        found = search_spotify(self.query, self.credentials, kind, self.limit, self.logger)
        results: list[SearchResult] = []
        for item in found:
            note = item.subtitle
            if item.total_tracks:
                note = f"{note}  ·  {item.total_tracks} tracks" if note else f"{item.total_tracks} tracks"
            results.append(SearchResult(
                title=item.name,
                url=item.url,
                site="Spotify",
                uploader=note,
                duration=item.duration_ms / 1000 if item.duration_ms else None,
                thumbnail=item.artwork,
            ))
        return results


class PlaylistWorker(QThread):
    """Resolves playlist, channel and Spotify links into individual entries.

    Runs off the GUI thread: a long playlist takes a few seconds to enumerate
    and a channel can take considerably longer.
    """

    progressed = Signal(str)
    # {source url: [PlaylistEntry]}, [(url, error)], cancelled
    finished_ok = Signal(dict, list, bool)

    def __init__(self, urls: list[str], limit: int, source: str, logger: logging.Logger) -> None:
        super().__init__()
        self.urls, self.limit, self.logger = urls, limit, logger
        self.source = source           # yt-dlp search prefix for Spotify tracks
        self.cancel = threading.Event()

    def run(self) -> None:
        found: dict[str, list[PlaylistEntry]] = {}
        problems: list[tuple[str, str]] = []
        for position, url in enumerate(self.urls, 1):
            if self.cancel.is_set():
                break
            spotify = looks_like_spotify(url)
            self.progressed.emit(
                f"Reading {'Spotify link' if spotify else 'playlist'} {position} of {len(self.urls)}…")
            try:
                entries = self._spotify(url) if spotify else expand_playlist(
                    url, self.logger, self.limit, self.cancel)
            except Exception as exc:
                # A link that cannot be read this way stays a single job rather
                # than blocking the batch (YouTube mixes, for instance).
                message = clean_error(exc) or exc.__class__.__name__
                self.logger.warning("Not expanded: %s | %s", url, message)
                problems.append((url, message))
                continue
            if entries:
                found[url] = entries
                self.logger.info("%s expanded to %d item(s)", url, len(entries))
        self.finished_ok.emit(found, problems, self.cancel.is_set())

    def _spotify(self, url: str) -> list[PlaylistEntry]:
        """Spotify's own audio is DRM-locked, so queue a search for each track."""
        name, tracks = spotify_tracks(url, self.logger, self.limit)
        if not tracks:
            raise SpotifyError("Spotify listed no tracks for that link.")
        # One track on its own is not a collection, so it gets no folder.
        collection = name if len(tracks) > 1 else ""
        return [PlaylistEntry(track.search_url(self.source), track.label, collection, url, index)
                for index, track in enumerate(tracks, 1)]


class FFmpegFetcher(QThread):
    """Downloads FFmpeg off the GUI thread."""

    progressed = Signal(int, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            path = ffmpeg_setup.download_ffmpeg(
                progress=lambda done, total: self.progressed.emit(done, total),
                cancel=self.cancel,
            )
        except ffmpeg_setup.DownloadCancelled:
            self.failed.emit("")
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.succeeded.emit(str(path))


class JobCardDelegate(QStyledItemDelegate):
    """Draws a download as a card.

    Every card is painted, not built: a queue of a few thousand videos would
    otherwise mean tens of thousands of widgets, and only the handful on
    screen are ever drawn this way.
    """

    HEIGHT = 92
    PAD = 11
    ART = QSize(104, 58)
    ACTION = QSize(74, 25)
    PILL = 20

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._hovered = -1          # job id the pointer is over

    # -------------------------------------------------------------- geometry
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, self.HEIGHT)

    def _job(self, index: QModelIndex) -> DownloadJob | None:
        return self.window.jobs_by_id.get(index.data(Qt.ItemDataRole.UserRole))

    def _art_rect(self, card: QRect) -> QRect:
        return QRect(card.left() + self.PAD,
                     card.top() + (card.height() - self.ART.height()) // 2,
                     self.ART.width(), self.ART.height())

    def _action_rect(self, card: QRect) -> QRect:
        # Sits under the status pill, so both share one right-hand column.
        return QRect(card.right() - self.PAD - self.ACTION.width(),
                     card.top() + self.PAD + self.PILL + 8,
                     self.ACTION.width(), self.ACTION.height())

    @staticmethod
    def _action_for(job: DownloadJob) -> str:
        if job.status in RETRYABLE:
            return "Retry"
        if job.status in {"Completed", "Skipped"} and job.output_path:
            return "Open"
        return ""

    # --------------------------------------------------------------- painting
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        job = self._job(index)
        if job is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = option.rect.adjusted(4, 3, -4, -3)
        hovered = job.job_id == self._hovered
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        path = QPainterPath()
        path.addRoundedRect(QRectF(card), 10, 10)
        painter.fillPath(path, QBrush(QColor(CARD_SELECTED if selected
                                             else CARD_HOVER if hovered else CARD_BG)))
        painter.setPen(QPen(QColor(CARD_BORDER), 1))
        painter.drawPath(path)
        # A tint down the left edge carries the status at a glance.
        accent = QColor(STATUS_COLORS.get(job.status, MUTED))
        edge = QPainterPath()
        edge.addRoundedRect(QRectF(card.left(), card.top() + 10, 3.0, card.height() - 20), 1.5, 1.5)
        painter.fillPath(edge, QBrush(accent))

        self._paint_art(painter, self._art_rect(card), job)

        small = painter.font()
        small.setPointSize(max(7, small.pointSize() - 1))
        small_metrics = QFontMetrics(small)
        action = self._action_for(job)
        # The pill and the action share one right-hand column, so the text
        # beside them is cut to the same width on every line.
        pill_width = small_metrics.horizontalAdvance(job.status) + 18
        column = max(pill_width, self.ACTION.width() if action else 0)
        text_left = self._art_rect(card).right() + self.PAD
        width = max(60, card.right() - self.PAD - column - 12 - text_left)
        # Anchored from both edges rather than stacked downwards: the font a
        # machine actually has decides these heights, and a taller one must
        # not push a line out of the card.
        title_font = painter.font()
        title_font.setBold(True)
        metrics = QFontMetrics(title_font)
        line = small_metrics.height()
        progress_top = card.bottom() - self.PAD - 5
        meta_top = progress_top - 7 - line
        title_top = card.top() + self.PAD

        painter.setPen(QColor(BRIGHT))
        painter.setFont(title_font)
        painter.drawText(QRect(text_left, title_top, width, min(metrics.height(), meta_top - title_top)),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(job.title or job.url, Qt.TextElideMode.ElideRight, width))

        # Where it came from, then how it is going, on one line in two
        # colours so a failure still stands out without its own row.
        small.setBold(False)
        painter.setFont(small)
        source = self._subtitle(job) + "  ·  "
        source_width = min(small_metrics.horizontalAdvance(source), width)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRect(text_left, meta_top, source_width, line),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         small_metrics.elidedText(source, Qt.TextElideMode.ElideRight, source_width))
        detail_width = width - source_width
        if detail_width > 30:
            painter.setPen(QColor(STATUS_COLORS["Failed"] if job.status == "Failed" else TEXT))
            painter.drawText(QRect(text_left + source_width, meta_top, detail_width, line),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             small_metrics.elidedText(job_detail(job), Qt.TextElideMode.ElideRight, detail_width))

        self._paint_progress(painter, QRect(text_left, progress_top, width, 5), job, accent)

        self._paint_status(painter, card, job, accent, small_metrics, pill_width)
        if action:
            self._paint_action(painter, self._action_rect(card), action, hovered)
        painter.restore()

    def _subtitle(self, job: DownloadJob) -> str:
        bits = []
        if job.playlist_title:
            bits.append(job.playlist_title)
        if job.media_count > 1:
            bits.append(f"{job.media_count} files")
        bits.append(source_label(job.url))
        return "  ·  ".join(bits)

    def _paint_art(self, painter: QPainter, rect: QRect, job: DownloadJob) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        painter.fillPath(path, QBrush(QColor(ART_BG)))
        pixmap = self.window.thumbnail_for(job)
        if pixmap is not None and not pixmap.isNull():
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect, pixmap)
            painter.restore()
            return
        # Nothing to show yet: the first letter stands in for the artwork.
        painter.setPen(QColor(MUTED))
        letter = painter.font()
        letter.setPointSize(16)
        letter.setBold(True)
        painter.setFont(letter)
        initial = (job.title or job.url).strip()
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         initial[:1].upper() if initial else "?")

    def _paint_progress(self, painter: QPainter, rect: QRect, job: DownloadJob, accent: QColor) -> None:
        track = QPainterPath()
        track.addRoundedRect(QRectF(rect), 2.5, 2.5)
        painter.fillPath(track, QBrush(QColor(TRACK_BG)))
        if job.status in {"Completed", "Skipped"}:
            fraction = 1.0
        elif job.status == "Downloading" and not job.total_bytes:
            fraction = 0.0        # size unknown; the detail line carries it
        else:
            fraction = max(0.0, min(1.0, job.progress))
        if fraction <= 0:
            return
        filled = QPainterPath()
        filled.addRoundedRect(QRectF(rect.adjusted(0, 0, -int(rect.width() * (1 - fraction)), 0)), 2.5, 2.5)
        painter.fillPath(filled, QBrush(accent))

    def _paint_status(self, painter: QPainter, card: QRect, job: DownloadJob,
                      accent: QColor, metrics: QFontMetrics, width: int) -> None:
        text = job.status
        # Tall enough for descenders in whatever font this machine has.
        height = max(self.PILL, metrics.height() + 2)
        rect = QRect(card.right() - self.PAD - width, card.top() + self.PAD, width, height)
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(rect), 10, 10)
        tint = QColor(accent)
        tint.setAlpha(38)
        painter.fillPath(pill, QBrush(tint))
        painter.setPen(QColor(accent))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_action(self, painter: QPainter, rect: QRect, text: str, hovered: bool) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        painter.fillPath(path, QBrush(QColor(ACTION_HOVER if hovered else ACTION_BG)))
        painter.setPen(QPen(QColor(CARD_BORDER), 1))
        painter.drawPath(path)
        painter.setPen(QColor(BRIGHT if hovered else TEXT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ----------------------------------------------------------- interaction
    def editorEvent(self, event: QEvent, model: Any, option: QStyleOptionViewItem,
                    index: QModelIndex) -> bool:
        job = self._job(index)
        if job is None:
            return False
        if event.type() == QEvent.Type.MouseMove:
            if self._hovered != job.job_id:
                self._hovered = job.job_id
                self.window.jobs_list.viewport().update()
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            card = option.rect.adjusted(4, 3, -4, -3)
            action = self._action_for(job)
            if action and self._action_rect(card).contains(event.pos()):
                self.window.card_action(job, action)
                return True
        return False


class MainWindow(QMainWindow):
    JOB_COLS = ("#", "Video", "Progress", "Details", "Status", "")
    HIST_COLS = ("Time", "Title", "Status", "URL", "Output / Error")
    SEARCH_COLS = ("", "", "Title", "Uploader", "Duration", "Views")
    THUMB_SIZE = QSize(96, 54)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Batch Downloader")
        self.setWindowIcon(app_icon())
        self.resize(1180, 820)
        self.setMinimumSize(900, 620)
        self.setAcceptDrops(True)

        self.logger = setup_logger()
        self.events: Queue[dict[str, Any]] = Queue()
        self.manager = DownloadManager(self.events, self.logger)
        self.jobs: list[DownloadJob] = []
        self.jobs_by_id: dict[int, DownloadJob] = {}
        self._card_rows: dict[int, int] = {}      # job id -> row in the card list
        self.queue_filter = "All"
        self.settings = self._load_settings()
        self.history: list[dict[str, Any]] = self._load_history()
        self._history_index: dict[tuple[str, str], int] = {}
        self._history_dirty = False
        self._history_stale = False
        self._reindex_history()
        self._exiting = False
        self._tray_hint_shown = False
        self.tray: QSystemTrayIcon | None = None
        self._ffmpeg_fetcher: FFmpegFetcher | None = None
        self._ffmpeg_dialog: QProgressDialog | None = None
        self.search_results: list[SearchResult] = []
        self._search_worker: SearchWorker | None = None
        self._search_generation = 0
        # Playlist URL -> the videos behind it, so a second Start does not have
        # to re-read every playlist over the network.
        self._expanded: dict[str, list[PlaylistEntry]] = {}
        self._not_playlists: set[str] = set()
        self._playlist_worker: PlaylistWorker | None = None
        self._net = QNetworkAccessManager(self)
        self._thumb_cache: dict[str, QPixmap] = {}
        self._thumb_pending: set[str] = set()
        self.spotify_creds = SpotifyCredentials(
            self.settings.get("spotify_client_id", ""), self.settings.get("spotify_client_secret", ""))

        self._build_ui()
        self._build_tray()
        self._check_tools()
        self._render_history()

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(400)
        self._reload_timer.timeout.connect(self._reload_links)

        # A card that moves in or out of the current filter needs the list
        # rebuilt; during a batch that can happen many times a second, so the
        # rebuilds are coalesced rather than run per event.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._render_jobs)
        # Likewise for artwork arriving: repaint once, not once per image.
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(120)
        self._thumb_timer.timeout.connect(lambda: self.jobs_list.viewport().update())
        # The counts and chips do not need redrawing for every event a busy
        # batch produces; a few times a second reads the same to a person.
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(150)
        self._summary_timer.timeout.connect(self._update_summary)

        # Saving history and redrawing its table wait for a run of finished
        # jobs to settle, so a long playlist does not do either per video.
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(1500)
        self._history_timer.timeout.connect(self._settle_history)
        self.tabs.currentChanged.connect(self._tab_changed)

        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_events)
        self._poll.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)

        title = QLabel("Video Batch Downloader")
        title.setObjectName("title")
        self.tool_label = QLabel("Checking yt-dlp and FFmpeg…")
        self.tool_label.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(self.tool_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_downloads_tab(), "Downloads")
        self.tabs.addTab(self._build_search_tab(), "Search")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._scrollable(self._build_settings_tab()), "Settings")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setObjectName("muted")
        bottom.addWidget(self.summary_label, 1)
        format_label = QLabel("Format")
        format_label.setObjectName("muted")
        bottom.addWidget(format_label)
        self.format_box = QComboBox()
        for label, _codec in FORMAT_CHOICES:
            self.format_box.addItem(label)
        self.format_box.setCurrentText(self.settings.get("format", FORMAT_CHOICES[0][0]))
        self.format_box.setMinimumWidth(130)
        self.format_box.setToolTip("Audio formats extract the soundtrack with FFmpeg")
        self.format_box.currentTextChanged.connect(self._format_changed)
        bottom.addWidget(self.format_box)
        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.setObjectName("warn")
        self.retry_btn.setEnabled(False)
        self.retry_btn.clicked.connect(self._retry_failed)
        self.start_btn = QPushButton("Start download")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        for btn in (self.retry_btn, self.start_btn, self.cancel_btn):
            btn.setMinimumWidth(120)
            bottom.addWidget(btn)
        layout.addLayout(bottom)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("muted")
        status_row.addWidget(self.status_label, 1)
        self.format_hint = QLabel()
        self.format_hint.setObjectName("muted")
        self.format_hint.setVisible(False)
        status_row.addWidget(self.format_hint)
        layout.addLayout(status_row)
        self._format_changed()
        self._update_summary()

    def _build_downloads_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- adding links: a compact bar that gets out of the way -----------
        self.add_panel = QFrame()
        self.add_panel.setObjectName("panel")
        sl = QVBoxLayout(self.add_panel)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.add_toggle = QToolButton()
        self.add_toggle.setText("Add links")
        self.add_toggle.setCheckable(True)
        self.add_toggle.setChecked(True)
        self.add_toggle.setAutoRaise(True)
        self.add_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.add_toggle.toggled.connect(self._toggle_add_panel)
        head.addWidget(self.add_toggle)
        self.count_label = QLabel("Nothing queued yet")
        self.count_label.setObjectName("muted")
        head.addWidget(self.count_label, 1)
        self.file_toggle = QToolButton()
        self.file_toggle.setText("From a file")
        self.file_toggle.setCheckable(True)
        self.file_toggle.setAutoRaise(True)
        self.file_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.file_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.file_toggle.toggled.connect(self._toggle_file_source)
        head.addWidget(self.file_toggle)
        sl.addLayout(head)

        self.add_body = QWidget()
        body = QVBoxLayout(self.add_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.direct_edit = QPlainTextEdit()
        self.direct_edit.setPlaceholderText(
            "Paste links — a video, a playlist, a channel, an Instagram post, a Spotify album…")
        self.direct_edit.setFixedHeight(76)
        self.direct_edit.textChanged.connect(lambda: self._reload_timer.start())
        body.addWidget(self.direct_edit)

        self.file_row = QWidget()
        grid = QGridLayout(self.file_row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        self.links_edit = QLineEdit()
        self.links_edit.setPlaceholderText("Choose a .txt file of links, or drop one onto the window")
        self.links_edit.editingFinished.connect(self._reload_links)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_links)
        self.links_clear_btn = QPushButton("Clear")
        self.links_clear_btn.clicked.connect(self._clear_links_file)
        grid.addWidget(self.links_edit, 0, 0)
        grid.addWidget(browse, 0, 1)
        grid.addWidget(self.links_clear_btn, 0, 2)
        grid.setColumnStretch(0, 1)
        self.file_row.setVisible(False)
        body.addWidget(self.file_row)
        sl.addWidget(self.add_body)
        layout.addWidget(self.add_panel)

        # --- the queue: filters, overall progress, then the cards -----------
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.filter_buttons: dict[str, QPushButton] = {}
        for name in QUEUE_FILTERS:
            chip = QPushButton(name)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setChecked(name == "All")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, n=name: self._set_filter(n))
            self.filter_buttons[name] = chip
            bar.addWidget(chip)
        bar.addStretch(1)
        self.clear_done_btn = QPushButton("Clear finished")
        self.clear_done_btn.setObjectName("small")
        self.clear_done_btn.setToolTip("Take everything that finished or was skipped out of the queue")
        self.clear_done_btn.clicked.connect(self._clear_finished)
        bar.addWidget(self.clear_done_btn)
        layout.addLayout(bar)

        self.batch_bar = QProgressBar()
        self.batch_bar.setRange(0, 1000)
        self.batch_bar.setTextVisible(False)
        self.batch_bar.setFixedHeight(6)
        layout.addWidget(self.batch_bar)

        self.jobs_list = QListWidget()
        self.jobs_list.setObjectName("cards")
        self.jobs_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.jobs_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.jobs_list.setUniformItemSizes(True)      # lets the view skip measuring every row
        self.jobs_list.setMouseTracking(True)
        self.jobs_list.setSpacing(0)
        self.card_delegate = JobCardDelegate(self)
        self.jobs_list.setItemDelegate(self.card_delegate)
        self.jobs_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.jobs_list.customContextMenuRequested.connect(self._job_menu)
        self.jobs_list.itemDoubleClicked.connect(self._card_double_clicked)
        self.empty_label = QLabel("Paste a link above to get started.")
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.jobs_list, 1)
        return page

    def _toggle_add_panel(self, shown: bool) -> None:
        self.add_body.setVisible(shown)
        self.add_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def _build_search_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search for videos…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._run_search)
        self.search_site = QComboBox()
        for name, key in SEARCH_SITES:
            self.search_site.addItem(name, key)
        for label, kind in SEARCH_KINDS:
            self.search_site.addItem(f"Spotify {label.lower()}", SPOTIFY_PREFIX + kind)
        self.search_site.setMinimumWidth(140)
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, MAX_RESULTS)
        self.search_limit.setValue(int(self.settings.get("search_limit", 15)))
        self.search_limit.setSuffix(" results")
        self.search_limit.setMinimumWidth(110)
        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._run_search)
        bar.addWidget(self.search_edit, 1)
        bar.addWidget(self.search_site)
        bar.addWidget(self.search_limit)
        bar.addWidget(self.search_btn)
        layout.addLayout(bar)

        self.search_table = QTableWidget(0, len(self.SEARCH_COLS))
        self.search_table.setHorizontalHeaderLabels(self.SEARCH_COLS)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.verticalHeader().setDefaultSectionSize(62)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.search_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.search_table.setShowGrid(False)
        self.search_table.setWordWrap(False)
        self.search_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.search_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        h = self.search_table.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeMode.Fixed, QHeaderView.ResizeMode.Fixed, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.Interactive, QHeaderView.ResizeMode.Fixed, QHeaderView.ResizeMode.Fixed)):
            h.setSectionResizeMode(col, mode)
        h.resizeSection(0, 36)
        h.resizeSection(1, self.THUMB_SIZE.width() + 16)
        h.resizeSection(3, 200)
        h.resizeSection(4, 90)
        h.resizeSection(5, 80)
        h.setStretchLastSection(False)
        self.search_table.cellDoubleClicked.connect(self._search_row_double_clicked)
        self.search_table.itemChanged.connect(lambda _item: self._update_search_selection())
        layout.addWidget(self.search_table, 1)

        footer = QHBoxLayout()
        self.search_status = QLabel("Enter a query to search YouTube and other supported sites.")
        self.search_status.setObjectName("muted")
        footer.addWidget(self.search_status, 1)
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._set_all_search_checks(True))
        select_none = QPushButton("Select none")
        select_none.clicked.connect(lambda: self._set_all_search_checks(False))
        self.add_selected_btn = QPushButton("Add selected to queue")
        self.add_selected_btn.setObjectName("primary")
        self.add_selected_btn.setEnabled(False)
        self.add_selected_btn.clicked.connect(self._add_selected_results)
        for btn in (select_all, select_none, self.add_selected_btn):
            footer.addWidget(btn)
        layout.addLayout(footer)
        return page

    # -------------------------------------------------------------- search
    def _run_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        if is_basic_url(query):
            self._append_direct(query)
            self.search_status.setText("That looks like a link — added it to the direct links box.")
            self.tabs.setCurrentIndex(0)
            return
        self._search_generation += 1
        prefix = self.search_site.currentData()
        self.search_btn.setEnabled(False)
        self.search_btn.setText("Searching…")
        self.search_status.setText(f"Searching {self.search_site.currentText()} for “{query}”…")
        worker = SearchWorker(self._search_generation, query, prefix, self.search_limit.value(),
                              self.logger, self.spotify_creds)
        worker.finished_ok.connect(self._search_finished)
        worker.failed.connect(self._search_failed)
        worker.finished.connect(worker.deleteLater)
        self._search_worker = worker
        worker.start()

    def _search_done(self) -> None:
        self.search_btn.setEnabled(True)
        self.search_btn.setText("Search")

    def _search_finished(self, generation: int, results: list) -> None:
        if generation != self._search_generation:
            return
        self._search_done()
        self.search_results = list(results)
        self._render_search_results()
        site = self.search_site.currentText()
        self.search_status.setText(f"{len(results)} result{'s' if len(results) != 1 else ''} from {site}." if results else f"No results on {site}.")

    def _search_failed(self, generation: int, error: str) -> None:
        if generation != self._search_generation:
            return
        self._search_done()
        self.search_status.setText(f"Search failed: {error}")
        self.logger.error("Search failed: %s", error)

    def _render_search_results(self) -> None:
        table = self.search_table
        table.blockSignals(True)
        table.setRowCount(0)
        table.setRowCount(len(self.search_results))
        for row, result in enumerate(self.search_results):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            table.setItem(row, 0, check)
            thumb = QLabel()
            thumb.setFixedSize(self.THUMB_SIZE)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("background: #21262d; border-radius: 4px;")
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper)
            wl.setContentsMargins(8, 4, 8, 4)
            wl.addWidget(thumb)
            table.setCellWidget(row, 1, wrapper)
            self._load_thumbnail(result.thumbnail, thumb)
            title = QTableWidgetItem(result.title)
            title.setToolTip(f"{result.title}\n{result.url}")
            table.setItem(row, 2, title)
            uploader = QTableWidgetItem(result.uploader)
            uploader.setForeground(QColor(MUTED))
            table.setItem(row, 3, uploader)
            duration = QTableWidgetItem(format_duration(result.duration))
            duration.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            duration.setFont(MONO_FONT())
            table.setItem(row, 4, duration)
            views = QTableWidgetItem(format_views(result.view_count))
            views.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            views.setFont(MONO_FONT())
            table.setItem(row, 5, views)
        table.blockSignals(False)
        self._update_search_selection()

    def _load_thumbnail(self, url: str, label: QLabel) -> None:
        if not url:
            return
        cached = self._thumb_cache.get(url)
        if cached is not None:
            label.setPixmap(cached)
            return
        reply = self._net.get(QNetworkRequest(QUrl(url)))

        def done() -> None:
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(reply.readAll()):
                        scaled = pixmap.scaled(self.THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                        x = max(0, (scaled.width() - self.THUMB_SIZE.width()) // 2)
                        y = max(0, (scaled.height() - self.THUMB_SIZE.height()) // 2)
                        cropped = scaled.copy(x, y, self.THUMB_SIZE.width(), self.THUMB_SIZE.height())
                        self._thumb_cache[url] = cropped
                        try:
                            label.setPixmap(cropped)
                        except RuntimeError:
                            pass
            finally:
                reply.deleteLater()

        reply.finished.connect(done)

    def _checked_results(self) -> list[SearchResult]:
        picked = []
        for row, result in enumerate(self.search_results):
            item = self.search_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                picked.append(result)
        return picked

    def _update_search_selection(self) -> None:
        count = len(self._checked_results())
        self.add_selected_btn.setEnabled(count > 0)
        self.add_selected_btn.setText(f"Add {count} to queue" if count else "Add selected to queue")

    def _set_all_search_checks(self, checked: bool) -> None:
        self.search_table.blockSignals(True)
        for row in range(self.search_table.rowCount()):
            item = self.search_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.search_table.blockSignals(False)
        self._update_search_selection()

    def _search_row_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.search_results):
            self._queue_results([self.search_results[row]])

    def _add_selected_results(self) -> None:
        self._queue_results(self._checked_results())

    def _queue_results(self, results: list[SearchResult]) -> None:
        if not results:
            return
        existing = set(self._collect_urls())
        new_urls = [r.url for r in results if r.url not in existing]
        if new_urls:
            self._append_direct("\n".join(new_urls))
            self._reload_links()
        skipped = len(results) - len(new_urls)
        msg = f"Added {len(new_urls)} link{'s' if len(new_urls) != 1 else ''} to the queue"
        if skipped:
            msg += f" ({skipped} already queued)"
        self.search_status.setText(msg + ".")
        self.status_label.setText(msg + ".")
        self._set_all_search_checks(False)
        self.tabs.setCurrentIndex(0)

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        self.history_count = QLabel()
        self.history_count.setObjectName("muted")
        bar.addWidget(self.history_count, 1)
        hint = QLabel("Double-click a row to open its folder")
        hint.setObjectName("muted")
        bar.addWidget(hint)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._render_history)
        clear = QPushButton("Clear")
        clear.setObjectName("danger")
        clear.clicked.connect(self._clear_history)
        bar.addWidget(refresh)
        bar.addWidget(clear)
        layout.addLayout(bar)

        self.history_table = QTableWidget(0, len(self.HIST_COLS))
        self.history_table.setHorizontalHeaderLabels(self.HIST_COLS)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSortingEnabled(True)
        self.history_table.setShowGrid(False)
        self.history_table.setWordWrap(False)
        h = self.history_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        h.resizeSection(3, 260)
        h.resizeSection(4, 320)
        self.history_table.cellDoubleClicked.connect(self._open_history_row)
        layout.addWidget(self.history_table, 1)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        paths = QGroupBox("Paths")
        pg = QGridLayout(paths)
        pg.setHorizontalSpacing(8)
        self.output_edit = QLineEdit(self.settings.get("output_folder", default_output_dir()))
        self.ffmpeg_edit = QLineEdit(self.settings.get("ffmpeg_path", ""))
        self.ffmpeg_edit.editingFinished.connect(self._check_tools)
        self.ffmpeg_edit.setPlaceholderText("Leave blank to use ffmpeg from PATH")
        self.ffmpeg_edit.editingFinished.connect(self._check_tools)
        out_btn = QPushButton("Browse")
        out_btn.clicked.connect(self._browse_output)
        ff_btn = QPushButton("Browse")
        ff_btn.clicked.connect(self._browse_ffmpeg)
        pg.addWidget(QLabel("Output folder"), 0, 0)
        pg.addWidget(self.output_edit, 0, 1)
        pg.addWidget(out_btn, 0, 2)
        pg.addWidget(QLabel("FFmpeg path"), 1, 0)
        pg.addWidget(self.ffmpeg_edit, 1, 1)
        pg.addWidget(ff_btn, 1, 2)
        self.ffmpeg_get_btn = QPushButton("Download")
        self.ffmpeg_get_btn.setToolTip("Fetch a static FFmpeg build from gyan.dev into the app folder")
        self.ffmpeg_get_btn.clicked.connect(self._fetch_ffmpeg)
        self.ffmpeg_get_btn.setVisible(ffmpeg_setup.is_supported())
        pg.addWidget(self.ffmpeg_get_btn, 1, 3)
        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setObjectName("muted")
        self.ffmpeg_status.setWordWrap(True)
        pg.addWidget(self.ffmpeg_status, 2, 1, 1, 3)
        pg.setColumnStretch(1, 1)
        layout.addWidget(paths)

        opts = QGroupBox("Download options")
        form = QGridLayout(opts)
        form.setHorizontalSpacing(12)
        self.quality_box = QComboBox()
        self.quality_box.addItems(["Best available", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        self.quality_box.setCurrentText(self.settings.get("quality", "Best available"))
        self.bitrate_box = QComboBox()
        self.bitrate_box.addItems([f"{rate} kbps" for rate in AUDIO_BITRATES])
        self.bitrate_box.setCurrentText(f"{self.settings.get('audio_quality', '192')} kbps")
        self.mode_box = QComboBox()
        self.mode_box.addItems(["Sequential", "Parallel"])
        self.mode_box.setCurrentText(self.settings.get("mode", "Parallel"))
        self.mode_box.currentTextChanged.connect(self._mode_changed)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 5)
        self.workers_spin.setValue(int(self.settings.get("workers", 3)))
        self.skip_check = QCheckBox("Skip files that already exist in the output folder")
        self.skip_check.setChecked(bool(self.settings.get("skip_existing", True)))
        self.quality_label = QLabel("Quality")
        form.addWidget(self.quality_label, 0, 0)
        form.addWidget(self.quality_box, 0, 1)
        form.addWidget(self.bitrate_box, 0, 1)
        form.addWidget(QLabel("Mode"), 0, 2)
        form.addWidget(self.mode_box, 0, 3)
        form.addWidget(QLabel("Workers"), 0, 4)
        form.addWidget(self.workers_spin, 0, 5)
        form.addWidget(self.skip_check, 1, 0, 1, 6)

        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 5.0)
        self.pause_spin.setSingleStep(0.25)
        self.pause_spin.setDecimals(2)
        self.pause_spin.setSuffix(" s")
        self.pause_spin.setSpecialValueText("Off")
        self.pause_spin.setValue(float(self.settings.get("request_pause", 0.75)))
        self.pause_spin.setToolTip("A gap between the requests each download makes, so a long "
                                   "batch is less likely to be throttled")
        self.pause_spin.valueChanged.connect(self._pacing_changed)
        self.throttle_retry_spin = QSpinBox()
        self.throttle_retry_spin.setRange(0, 5)
        self.throttle_retry_spin.setValue(int(self.settings.get("rate_limit_retries", 2)))
        self.throttle_retry_spin.setToolTip("How many further goes a download gets when the site "
                                            "turns it away rather than the video being unavailable")
        self.throttle_retry_spin.valueChanged.connect(self._pacing_changed)
        form.addWidget(QLabel("Pause between requests"), 2, 0)
        form.addWidget(self.pause_spin, 2, 1)
        form.addWidget(QLabel("Retry if throttled"), 2, 2)
        form.addWidget(self.throttle_retry_spin, 2, 3)
        self.pacing_hint = QLabel()
        self.pacing_hint.setObjectName("muted")
        self.pacing_hint.setWordWrap(True)
        form.addWidget(self.pacing_hint, 3, 0, 1, 6)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        layout.addWidget(opts)

        lists = QGroupBox("Playlists and channels")
        lg = QGridLayout(lists)
        lg.setHorizontalSpacing(12)
        self.playlist_check = QCheckBox("Download every video behind a playlist, channel or album link")
        self.playlist_check.setChecked(bool(self.settings.get("playlists", True)))
        self.playlist_check.toggled.connect(self._playlists_changed)
        self.playlist_folder_check = QCheckBox("Save each playlist in its own subfolder")
        self.playlist_folder_check.setChecked(bool(self.settings.get("playlist_folders", True)))
        self.playlist_folder_check.toggled.connect(self._playlists_changed)
        self.playlist_limit_spin = QSpinBox()
        self.playlist_limit_spin.setRange(0, 5000)
        self.playlist_limit_spin.setValue(int(self.settings.get("playlist_limit", 0)))
        self.playlist_limit_spin.setSpecialValueText("All")
        self.playlist_limit_spin.setFixedWidth(96)
        self.playlist_limit_spin.setToolTip("A cap on how many videos one playlist contributes; 0 takes all of them")
        self.playlist_limit_spin.valueChanged.connect(self._playlist_limit_changed)
        self.playlist_limit_label = QLabel("Videos per playlist")
        lg.addWidget(self.playlist_check, 0, 0, 1, 2)
        lg.addWidget(self.playlist_limit_label, 0, 2)
        lg.addWidget(self.playlist_limit_spin, 0, 3)
        lg.addWidget(self.playlist_folder_check, 1, 0, 1, 4)
        self.playlist_hint = QLabel()
        self.playlist_hint.setObjectName("muted")
        self.playlist_hint.setWordWrap(True)
        lg.addWidget(self.playlist_hint, 2, 0, 1, 4)
        lg.setColumnStretch(1, 1)
        layout.addWidget(lists)

        spot = QGroupBox("Spotify")
        sp = QGridLayout(spot)
        sp.setHorizontalSpacing(12)
        self.spotify_check = QCheckBox("Queue Spotify links as the matching tracks")
        self.spotify_check.setChecked(bool(self.settings.get("spotify", True)))
        self.spotify_check.toggled.connect(self._spotify_changed)
        self.spotify_source = QComboBox()
        for label, prefix in MATCH_SOURCES:
            self.spotify_source.addItem(label, prefix)
        saved_source = self.settings.get("spotify_source", DEFAULT_MATCH_SOURCE)
        index = self.spotify_source.findData(saved_source)
        self.spotify_source.setCurrentIndex(index if index >= 0 else 0)
        self.spotify_source.setMinimumWidth(140)
        self.spotify_source.currentTextChanged.connect(self._spotify_changed)
        self.spotify_source_label = QLabel("Find tracks on")
        self.spotify_hint = QLabel()
        self.spotify_hint.setObjectName("muted")
        self.spotify_hint.setWordWrap(True)
        sp.addWidget(self.spotify_check, 0, 0, 1, 2)
        sp.addWidget(self.spotify_source_label, 0, 2)
        sp.addWidget(self.spotify_source, 0, 3)
        sp.addWidget(self.spotify_hint, 1, 0, 1, 4)

        self.spotify_id_edit = QLineEdit(self.settings.get("spotify_client_id", ""))
        self.spotify_id_edit.setPlaceholderText("Client ID from your Spotify app")
        self.spotify_id_edit.editingFinished.connect(self._spotify_creds_changed)
        self.spotify_secret_edit = QLineEdit(self.settings.get("spotify_client_secret", ""))
        self.spotify_secret_edit.setPlaceholderText("Client Secret")
        self.spotify_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.spotify_secret_edit.editingFinished.connect(self._spotify_creds_changed)
        sp.addWidget(QLabel("Client ID"), 2, 0)
        sp.addWidget(self.spotify_id_edit, 2, 1, 1, 3)
        sp.addWidget(QLabel("Client Secret"), 3, 0)
        sp.addWidget(self.spotify_secret_edit, 3, 1, 1, 3)
        creds_row = QHBoxLayout()
        self.spotify_creds_status = QLabel()
        self.spotify_creds_status.setObjectName("muted")
        self.spotify_creds_status.setWordWrap(True)
        creds_row.addWidget(self.spotify_creds_status, 1)
        self.spotify_test_btn = QPushButton("Test")
        self.spotify_test_btn.setToolTip("Ask Spotify for a token with these credentials")
        self.spotify_test_btn.clicked.connect(self._test_spotify_creds)
        creds_row.addWidget(self.spotify_test_btn)
        dash_btn = QPushButton("Get credentials")
        dash_btn.setToolTip("Open the Spotify developer dashboard")
        dash_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://developer.spotify.com/dashboard")))
        creds_row.addWidget(dash_btn)
        sp.addLayout(creds_row, 4, 0, 1, 4)
        sp.setColumnStretch(1, 1)
        layout.addWidget(spot)

        subs = QGroupBox("Subtitles")
        sg = QGridLayout(subs)
        sg.setHorizontalSpacing(12)
        self.subs_box = QComboBox()
        for label, _mode in SUBTITLE_CHOICES:
            self.subs_box.addItem(label)
        self.subs_box.setCurrentText(self.settings.get("subtitles", SUBTITLE_CHOICES[0][0]))
        self.subs_box.setMinimumWidth(170)
        self.subs_box.currentTextChanged.connect(self._subtitles_changed)
        self.subs_lang_edit = QLineEdit(self.settings.get("subtitle_langs", DEFAULT_SUBTITLE_LANGS))
        self.subs_lang_edit.setPlaceholderText("en, es  —  or all for every language offered")
        self.subs_lang_edit.textChanged.connect(self._subtitles_changed)
        self.subs_auto_check = QCheckBox("Accept auto-generated captions when there is no human-made track")
        self.subs_auto_check.setChecked(bool(self.settings.get("subtitle_auto", True)))
        self.subs_hint = QLabel()
        self.subs_hint.setObjectName("muted")
        self.subs_hint.setWordWrap(True)
        sg.addWidget(QLabel("Subtitles"), 0, 0)
        sg.addWidget(self.subs_box, 0, 1)
        self.subs_lang_label = QLabel("Languages")
        sg.addWidget(self.subs_lang_label, 0, 2)
        sg.addWidget(self.subs_lang_edit, 0, 3)
        sg.addWidget(self.subs_auto_check, 1, 0, 1, 4)
        sg.addWidget(self.subs_hint, 2, 0, 1, 4)
        sg.setColumnStretch(3, 1)
        layout.addWidget(subs)

        note = QLabel("Video quality is a maximum height; lower-resolution sources are never upscaled. "
                      "Audio formats download the best available audio stream and convert it with FFmpeg "
                      "(FLAC and WAV are lossless, so bitrate does not apply). "
                      "Subtitles never fail a download: when a video has none in the languages asked for, "
                      "or the caption file will not come down, the video is kept anyway. "
                      "Settings are saved when a download starts and on exit.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._mode_changed()
        self._pacing_changed()
        self._update_spotify_creds_status()
        self._spotify_changed()
        self._playlists_changed()
        return page

    @staticmethod
    def _scrollable(page: QWidget) -> QWidget:
        """Let a tab scroll rather than squash its controls on a short window."""
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        area.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return area

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = app_icon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Video Batch Downloader")
        menu = QMenu()
        show = QAction("Show", menu)
        show.triggered.connect(self._show_window)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self._exit_app)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)

    # ---------------------------------------------------------------- links
    def _toggle_file_source(self, checked: bool) -> None:
        self.file_row.setVisible(checked)
        self.file_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def _show_file_source(self) -> None:
        if not self.file_toggle.isChecked():
            self.file_toggle.setChecked(True)

    def _clear_links_file(self) -> None:
        self.links_edit.clear()
        self._reload_links()

    def _browse_links(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose links file", "", "Text files (*.txt);;All files (*.*)")
        if path:
            self.links_edit.setText(path)
            self._show_file_source()
            self._reload_links()

    def _collect_urls(self) -> list[str]:
        urls: list[str] = []
        path_text = self.links_edit.text().strip()
        if path_text:
            try:
                urls.extend(parse_urls(Path(path_text).read_text(encoding="utf-8", errors="replace")))
            except OSError as exc:
                QMessageBox.critical(self, "Cannot read links file", str(exc))
        urls.extend(parse_urls(self.direct_edit.toPlainText()))
        seen: set[str] = set()
        merged: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                merged.append(url)
        return merged

    def _reload_links(self) -> None:
        if self.manager.active or self._playlist_worker is not None:
            return
        prior = {job.url: job for job in self.jobs}
        self.jobs = []
        playlists = 0
        for url in self._collect_urls():
            entries = self._expanded.get(url) if self._expands(url) else None
            if entries:
                playlists += 1
                for entry in entries:
                    self._add_job(prior, entry.url, title=entry.title, playlist_title=entry.playlist_title,
                                  playlist_url=entry.playlist_url, playlist_index=entry.playlist_index,
                                  thumbnail=entry.thumbnail)
            else:
                self._add_job(prior, url)
        self.count_label.setText(self._count_text(len(self.jobs), playlists))
        self._render_jobs()

    def _add_job(self, prior: dict[str, DownloadJob], url: str, title: str = "", **extra: Any) -> None:
        """Append one job, carrying over the state of a job for the same URL."""
        index = len(self.jobs) + 1
        if not is_queueable(url):
            self.jobs.append(DownloadJob(index, url, title=title, status="Invalid", **extra))
            return
        old = prior.get(url)
        if old:
            self.jobs.append(DownloadJob(
                index, url, title=old.title or title, status=old.status, progress=old.progress,
                downloaded_bytes=old.downloaded_bytes, total_bytes=old.total_bytes,
                output_path=old.output_path, error=old.error, note=old.note,
                media_count=old.media_count, **extra))
        else:
            self.jobs.append(DownloadJob(index, url, title=title, **extra))

    @staticmethod
    def _count_text(videos: int, expanded: int) -> str:
        text = f"Videos found: {videos}"
        if expanded:
            text += f"   ({expanded} link{'s' if expanded != 1 else ''} expanded)"
        return text

    # --------------------------------------------------------------- queue
    @staticmethod
    def _passes_filter(job: DownloadJob, name: str) -> bool:
        if name == "Active":
            return job.status in {"Queued", "Downloading", "Waiting"}
        if name == "Done":
            return job.status in {"Completed", "Skipped"}
        if name == "Failed":
            return job.status in RETRYABLE
        return True

    def _render_jobs(self) -> None:
        """Rebuild the card list. One list item per job, all of them painted."""
        self.jobs_by_id = {job.job_id: job for job in self.jobs}
        self.jobs_list.setUpdatesEnabled(False)
        self.jobs_list.clear()
        self._card_rows.clear()
        for job in self.jobs:
            if not self._passes_filter(job, self.queue_filter):
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, job.job_id)
            item.setSizeHint(QSize(0, JobCardDelegate.HEIGHT))
            self._card_rows[job.job_id] = self.jobs_list.count()
            self.jobs_list.addItem(item)
            if job.thumbnail:
                self._want_thumbnail(job.thumbnail)
        self.jobs_list.setUpdatesEnabled(True)
        self._update_summary()

    def _sync_row(self, job: DownloadJob) -> None:
        """Repaint one card, without touching the rest of the list."""
        self.jobs_by_id[job.job_id] = job
        if job.thumbnail:
            self._want_thumbnail(job.thumbnail)
        if not self._passes_filter(job, self.queue_filter):
            # It no longer belongs in the view this filter shows.
            if job.job_id in self._card_rows:
                self._refresh_timer.start()
            return
        row = self._card_rows.get(job.job_id)
        if row is None:
            self._refresh_timer.start()     # newly matches the filter
            return
        index = self.jobs_list.model().index(row, 0)
        self.jobs_list.update(index)

    def _update_summary(self) -> None:
        # One pass: this runs on every status event, of which a long playlist
        # produces thousands.
        tally: Counter[str] = Counter(job.status for job in self.jobs)
        completed, downloading = tally["Completed"], tally["Downloading"]
        queued = tally["Queued"] + tally["Waiting"]
        failed, skipped = tally["Failed"], tally["Skipped"]
        total = len(self.jobs)
        done = completed + skipped + failed
        self.summary_label.setText(
            f"{completed} / {total} completed   •   {downloading} downloading   •   {queued} queued   •   {skipped} skipped   •   {failed} failed"
            if total else "Nothing queued"
        )
        counts = {"All": total, "Active": downloading + queued,
                  "Done": completed + skipped, "Failed": failed}
        for name, chip in self.filter_buttons.items():
            chip.setText(f"{name}  {counts[name]}" if counts[name] else name)
            chip.setChecked(name == self.queue_filter)
        self.batch_bar.setVisible(bool(total))
        self.batch_bar.setValue(int(done / total * 1000) if total else 0)
        self.empty_label.setVisible(not self.jobs_list.count())
        if not total:
            self.empty_label.setText("Paste a link above to get started.")
        elif not self.jobs_list.count():
            self.empty_label.setText(f"Nothing here under “{self.queue_filter}”.")
        self.clear_done_btn.setEnabled(bool(counts["Done"]) and not self.manager.active)
        retryable = bool(tally.keys() & RETRYABLE) and not self.manager.active
        self.retry_btn.setEnabled(retryable)

    def _set_filter(self, name: str) -> None:
        self.queue_filter = name
        self._render_jobs()

    def _clear_finished(self) -> None:
        if self.manager.active:
            return
        keep = [job for job in self.jobs if job.status not in {"Completed", "Skipped"}]
        if len(keep) == len(self.jobs):
            return
        # The links box is the source of truth for what is queued, so the
        # finished entries have to leave it too or the next reload brings
        # them straight back.
        self._drop_from_sources({job.url for job in self.jobs if job not in keep})
        self.jobs = keep
        for position, job in enumerate(self.jobs, 1):
            job.job_id = position
        self._render_jobs()

    def _drop_from_sources(self, gone: set[str]) -> None:
        """Remove links from the box, and from the expansions they came from."""
        kept_lines = [line for line in self.direct_edit.toPlainText().splitlines()
                      if line.strip() not in gone]
        for url, entries in list(self._expanded.items()):
            remaining = [e for e in entries if e.url not in gone]
            if not remaining:
                self._expanded.pop(url, None)
                kept_lines = [line for line in kept_lines if line.strip() != url]
            else:
                self._expanded[url] = remaining
        self.direct_edit.blockSignals(True)
        self.direct_edit.setPlainText("\n".join(kept_lines))
        self.direct_edit.blockSignals(False)

    def _remove_jobs(self, jobs: list[DownloadJob]) -> None:
        if self.manager.active or not jobs:
            return
        gone = {job.url for job in jobs}
        self._drop_from_sources(gone)
        self.jobs = [job for job in self.jobs if job.url not in gone]
        for position, job in enumerate(self.jobs, 1):
            job.job_id = position
        self._render_jobs()

    def _selected_jobs(self) -> list[DownloadJob]:
        picked = [self.jobs_by_id.get(item.data(Qt.ItemDataRole.UserRole))
                  for item in self.jobs_list.selectedItems()]
        return [job for job in picked if job is not None]

    def card_action(self, job: DownloadJob, action: str) -> None:
        """The button painted on a card was clicked."""
        if action == "Retry":
            self._retry_jobs([job])
        elif action == "Open":
            self._reveal(job.output_path)

    def _card_double_clicked(self, item: QListWidgetItem) -> None:
        job = self.jobs_by_id.get(item.data(Qt.ItemDataRole.UserRole))
        if job is None:
            return
        if job.output_path:
            self._reveal(job.output_path)
        elif is_basic_url(job.url):
            QDesktopServices.openUrl(QUrl(job.url))

    def _reveal(self, path: str) -> None:
        target = Path(path)
        if not path or not target.exists():
            QMessageBox.information(self, "Not found",
                                    "That file is no longer where it was saved.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _job_menu(self, point: Any) -> None:
        item = self.jobs_list.itemAt(point)
        if item is None:
            return
        job = self.jobs_by_id.get(item.data(Qt.ItemDataRole.UserRole))
        if job is None:
            return
        selected = self._selected_jobs() or [job]
        menu = QMenu(self)
        if job.output_path:
            menu.addAction("Open containing folder", lambda: self._reveal(job.output_path))
        if is_basic_url(job.url):
            menu.addAction("Open the source page", lambda: QDesktopServices.openUrl(QUrl(job.url)))
        menu.addAction("Copy link", lambda: QApplication.clipboard().setText(job.url))
        if job.error:
            menu.addAction("Copy the error", lambda: QApplication.clipboard().setText(job.error))
        retryable = [j for j in selected if j.status in RETRYABLE]
        if retryable and not self.manager.active:
            menu.addSeparator()
            menu.addAction(f"Retry {len(retryable)} selected" if len(retryable) > 1 else "Retry",
                           lambda: self._retry_jobs(retryable))
        if not self.manager.active:
            menu.addSeparator()
            menu.addAction(f"Remove {len(selected)} from the queue" if len(selected) > 1
                           else "Remove from the queue", lambda: self._remove_jobs(selected))
        menu.exec(self.jobs_list.viewport().mapToGlobal(point))

    # ----------------------------------------------------------- thumbnails
    def thumbnail_for(self, job: DownloadJob) -> QPixmap | None:
        return self._thumb_cache.get(job.thumbnail) if job.thumbnail else None

    def _want_thumbnail(self, url: str) -> None:
        """Fetch artwork once, then repaint whatever is on screen."""
        if not url or url in self._thumb_cache or url in self._thumb_pending:
            return
        self._thumb_pending.add(url)
        reply = self._net.get(QNetworkRequest(QUrl(url)))

        def done() -> None:
            try:
                self._thumb_pending.discard(url)
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    return
                pixmap = QPixmap()
                if not pixmap.loadFromData(reply.readAll()):
                    return
                self._thumb_cache[url] = self._crop(pixmap, JobCardDelegate.ART)
                self._thumb_timer.start()
            finally:
                reply.deleteLater()

        reply.finished.connect(done)

    @staticmethod
    def _crop(pixmap: QPixmap, size: QSize) -> QPixmap:
        scaled = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        return scaled.copy(x, y, size.width(), size.height())

    # ------------------------------------------------------------- actions
    def _audio_format(self) -> str:
        label = self.format_box.currentText()
        return next((codec for name, codec in FORMAT_CHOICES if name == label), "")

    def _subtitle_mode(self) -> str:
        label = self.subs_box.currentText()
        return next((mode for name, mode in SUBTITLE_CHOICES if name == label), "")

    def _config(self) -> DownloadConfig:
        return DownloadConfig(
            Path(self.output_edit.text()).expanduser(),
            self.quality_box.currentText(),
            self.mode_box.currentText(),
            self.workers_spin.value(),
            self.skip_check.isChecked(),
            self.ffmpeg_edit.text().strip(),
            self._audio_format(),
            self.bitrate_box.currentText().split()[0],
            self._subtitle_mode(),
            self.subs_lang_edit.text().strip() or DEFAULT_SUBTITLE_LANGS,
            self.subs_auto_check.isChecked(),
            self.playlist_check.isChecked(),
            self.playlist_limit_spin.value(),
            self.playlist_folder_check.isChecked(),
            self.pause_spin.value(),
            self.throttle_retry_spin.value(),
        )

    def _format_changed(self, _: str = "") -> None:
        codec = self._audio_format()
        audio = bool(codec)
        self.quality_box.setVisible(not audio)
        self.bitrate_box.setVisible(audio)
        self.bitrate_box.setEnabled(codec not in LOSSLESS_AUDIO)
        self.quality_label.setText("Bitrate" if audio else "Quality")
        self.format_hint.setVisible(audio)
        if audio:
            ext = AUDIO_FORMATS[codec]
            if find_ffmpeg(self.ffmpeg_edit.text().strip()):
                self.format_hint.setText(f"Saving as .{ext}")
                self.format_hint.setStyleSheet(f"color: {MUTED}")
            else:
                self.format_hint.setText(f".{ext} needs FFmpeg — not found")
                self.format_hint.setStyleSheet(f"color: {STATUS_COLORS['Cancelled']}")
        self._subtitles_changed()

    def _subtitles_changed(self, _: str = "") -> None:
        mode = self._subtitle_mode()
        audio = bool(self._audio_format())
        active = bool(mode) and not audio
        self.subs_box.setEnabled(not audio)
        for widget in (self.subs_lang_label, self.subs_lang_edit, self.subs_auto_check):
            widget.setEnabled(active)
        if audio:
            self.subs_hint.setText("Subtitles do not apply to audio-only downloads.")
            self.subs_hint.setStyleSheet(f"color: {MUTED}")
            return
        if not mode:
            self.subs_hint.setText("")
            return
        has_ffmpeg = bool(find_ffmpeg(self.ffmpeg_edit.text().strip()))
        if mode in EMBED_SUBTITLE_MODES and not has_ffmpeg:
            self.subs_hint.setText("Embedding subtitles needs FFmpeg — not found.")
            self.subs_hint.setStyleSheet(f"color: {STATUS_COLORS['Cancelled']}")
            return
        langs = subtitle_languages(self.subs_lang_edit.text().strip() or DEFAULT_SUBTITLE_LANGS)
        wanted = "every language offered" if "all" in langs else ", ".join(langs)
        if mode == "embed":
            text = f"Captions ({wanted}) become a subtitle track inside the MP4."
        elif mode == "file":
            text = f"Captions ({wanted}) are saved next to the video"
            text += " as .srt." if has_ffmpeg else " in whatever format the site offers (.srt needs FFmpeg)."
        else:
            text = f"Captions ({wanted}) are embedded in the MP4 and kept as .srt files."
        self.subs_hint.setText(text)
        self.subs_hint.setStyleSheet(f"color: {MUTED}")

    def _require_ffmpeg(self) -> bool:
        """True when the batch may proceed; offers the download when it may not."""
        codec = self._audio_format()
        embedding = not codec and self._subtitle_mode() in EMBED_SUBTITLE_MODES
        if not codec and not embedding:
            return True
        if find_ffmpeg(self.ffmpeg_edit.text().strip()):
            return True
        need = f"Saving as {codec.upper()}" if codec else "Embedding subtitles"
        if not ffmpeg_setup.is_supported():
            QMessageBox.critical(self, "FFmpeg required",
                                 f"{need} needs FFmpeg. Install it and set its path in Settings.")
            return False
        if QMessageBox.question(
            self, "FFmpeg required",
            f"{need} needs FFmpeg, which was not found.\n\nDownload it now?",
        ) == QMessageBox.StandardButton.Yes:
            self._fetch_ffmpeg()
        return False

    def _start(self) -> None:
        if self._playlist_worker is not None:
            return
        self._reload_links()
        if not self.jobs:
            QMessageBox.information(self, "Nothing to download", "Add at least one valid URL via the links file or the direct links box.")
            return
        if not self._require_ffmpeg():
            return
        if self._expand_playlists_then_start():
            return
        self._start_pending()

    def _start_pending(self) -> None:
        pending = [j for j in self.jobs if j.status in {"Queued", *RETRYABLE} and is_queueable(j.url)]
        if not pending:
            QMessageBox.information(self, "Nothing to download", "Add at least one valid URL via the links file or the direct links box.")
            return
        self._launch(pending)

    # ----------------------------------------------------------- playlists
    def _playlists_changed(self, _checked: bool = False) -> None:
        on = self.playlist_check.isChecked()
        for widget in (self.playlist_limit_label, self.playlist_limit_spin, self.playlist_folder_check):
            widget.setEnabled(on)
        if on:
            limit = self.playlist_limit_spin.value()
            cap = "every video" if limit == 0 else f"the first {limit} videos"
            where = "its own subfolder" if self.playlist_folder_check.isChecked() else "the output folder"
            self.playlist_hint.setText(
                f"A playlist, channel or album link is read first and queued as {cap} it holds, "
                f"each one its own row with its own progress, saved into {where}. A post holding "
                f"several photos or clips, such as an Instagram carousel, comes down in full."
            )
        else:
            self.playlist_hint.setText(
                "One link, one file: a playlist link brings down a single video, and only the "
                "first item of a post that holds several."
            )
        # Called while the Settings tab is still being built, before the
        # bottom bar exists; the first real render comes right after.
        if hasattr(self, "retry_btn") and not self.manager.active:
            self._reload_links()

    def _spotify_creds_changed(self) -> None:
        """Rebuild the credentials when either field is edited."""
        client_id = self.spotify_id_edit.text().strip()
        secret = self.spotify_secret_edit.text().strip()
        if not self.spotify_creds.matches(client_id, secret):
            self.spotify_creds = SpotifyCredentials(client_id, secret)
        self._update_spotify_creds_status()

    def _update_spotify_creds_status(self, message: str = "", good: bool = False) -> None:
        if message:
            self.spotify_creds_status.setText(message)
            self.spotify_creds_status.setStyleSheet(
                f"color: {STATUS_COLORS['Completed'] if good else STATUS_COLORS['Failed']}")
            return
        ready = self.spotify_creds.configured
        self.spotify_creds_status.setText(
            "Searching Spotify is ready." if ready else
            "Searching Spotify needs a free app from the dashboard; pasting Spotify links works without one."
        )
        self.spotify_creds_status.setStyleSheet(f"color: {MUTED}")
        self.spotify_test_btn.setEnabled(ready)

    def _test_spotify_creds(self) -> None:
        self._spotify_creds_changed()
        self.spotify_test_btn.setEnabled(False)
        self.spotify_creds_status.setText("Asking Spotify…")
        QApplication.processEvents()
        try:
            self.spotify_creds.token()
        except SpotifyError as exc:
            self._update_spotify_creds_status(str(exc), good=False)
            self.logger.warning("Spotify credentials rejected: %s", exc)
        else:
            self._update_spotify_creds_status("Spotify accepted these credentials.", good=True)
            self.logger.info("Spotify credentials accepted")
        self.spotify_test_btn.setEnabled(self.spotify_creds.configured)

    def _pacing_changed(self, _value: Any = None) -> None:
        pause, retries = self.pause_spin.value(), self.throttle_retry_spin.value()
        if pause > 0:
            text = (f"Each download waits about {pause:.2f}s between the requests it makes, "
                    f"which is what keeps a long batch from being throttled.")
        else:
            text = ("Requests go out as fast as they can, which a long batch of them tends to "
                    "earn a block for.")
        if retries:
            text += (f" A download turned away by the site gets {retries} more "
                     f"{'go' if retries == 1 else 'goes'}, and the whole batch holds off in "
                     f"between rather than burning through the queue.")
        else:
            text += " A download turned away by the site is reported as failed straight away."
        self.pacing_hint.setText(text)

    def _spotify_changed(self, _value: Any = None) -> None:
        on = self.spotify_check.isChecked()
        for widget in (self.spotify_source_label, self.spotify_source):
            widget.setEnabled(on)
        if on:
            where = self.spotify_source.currentText()
            self.spotify_hint.setText(
                f"Spotify streams are copy-protected, so nothing is taken from Spotify itself. "
                f"A track, album or playlist link is read for what is on it, and each track is "
                f"queued as the closest match on {where}."
            )
        else:
            self.spotify_hint.setText("Spotify links are left alone, and will fail as unsupported.")
        # A different source means different matches, so drop what was read.
        self._expanded = {url: entries for url, entries in self._expanded.items()
                          if not looks_like_spotify(url)}
        self._not_playlists = {url for url in self._not_playlists if not looks_like_spotify(url)}
        if hasattr(self, "retry_btn") and not self.manager.active:
            self._reload_links()

    def _playlist_limit_changed(self, _value: int = 0) -> None:
        # A different cap means a different set of videos, so what was read
        # earlier is no longer the answer.
        self._expanded.clear()
        self._not_playlists.clear()
        self._playlists_changed()

    def _expands(self, url: str) -> bool:
        """Whether this link may turn into several queue rows."""
        if looks_like_spotify(url):
            return self.spotify_check.isChecked()
        return self.playlist_check.isChecked() and looks_like_playlist(url)

    def _playlist_candidates(self) -> list[str]:
        """Collected links that may expand and have not been read yet."""
        return [url for url in self._collect_urls()
                if is_basic_url(url) and self._expands(url)
                and url not in self._expanded and url not in self._not_playlists]

    def _expand_playlists_then_start(self) -> bool:
        """Start reading the links that expand; True when the batch must wait."""
        candidates = self._playlist_candidates()
        if not candidates:
            return False
        worker = PlaylistWorker(candidates, self.playlist_limit_spin.value(),
                                self.spotify_source.currentData() or DEFAULT_MATCH_SOURCE, self.logger)
        worker.progressed.connect(self.status_label.setText)
        worker.finished_ok.connect(self._playlists_expanded)
        worker.finished.connect(worker.deleteLater)
        self._playlist_worker = worker
        self.start_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText(
            f"Reading {len(candidates)} link{'s' if len(candidates) != 1 else ''}…")
        worker.start()
        return True

    def _playlists_expanded(self, found: dict, problems: list, cancelled: bool) -> None:
        self._playlist_worker = None
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        for url, entries in found.items():
            self._expanded[url] = entries
        # Links that turned out to be a single video, or could not be read at
        # all, are remembered so Start does not probe them again.
        for url in self._playlist_candidates():
            if url not in found:
                self._not_playlists.add(url)
        self._reload_links()
        if cancelled:
            self.status_label.setText("Cancelled while reading links.")
            return
        added = sum(len(entries) for entries in found.values())
        if added:
            self.status_label.setText(
                f"{len(found)} link{'s' if len(found) != 1 else ''} queued as {added} items.")
        if problems:
            self.logger.info("%d link(s) did not expand", len(problems))
            # A playlist that would not open quietly falls back to one video,
            # but a Spotify link that cannot be read has nothing to fall back
            # to, so say why before the job fails as an unsupported URL.
            stuck = next(((url, why) for url, why in problems if looks_like_spotify(url)), None)
            if stuck:
                self.status_label.setText(f"Could not read that Spotify link — {stuck[1]}")
        self._start_pending()

    def _retry_failed(self) -> None:
        self._retry_jobs([j for j in self.jobs if j.status in RETRYABLE])

    def _retry_jobs(self, jobs: list[DownloadJob]) -> None:
        jobs = [j for j in jobs if j.status in RETRYABLE and is_queueable(j.url)]
        if not jobs or self.manager.active:
            return
        for job in jobs:
            job.status, job.error, job.output_path = "Queued", "", ""
            job.note, job.media_count = "", 0
            job.progress, job.downloaded_bytes, job.total_bytes, job.speed, job.eta = 0.0, 0, None, None, None
            self._sync_row(job)
        self._update_summary()
        self._launch(jobs)

    def _launch(self, jobs: list[DownloadJob]) -> None:
        config = self._config()
        try:
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.manager.start(jobs, config)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to start", str(exc))
            return
        self._save_settings()
        self.start_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText(f"Downloading {len(jobs)} item{'s' if len(jobs) != 1 else ''}…")
        for job in self.jobs:
            self._sync_row(job)

    def _cancel(self) -> None:
        if self._playlist_worker is not None:
            self._playlist_worker.cancel.set()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("Cancelling…")
            return
        self.manager.cancel()
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelling…")

    # -------------------------------------------------------------- events
    def _poll_events(self) -> None:
        # Bounded on purpose: a large batch can queue events faster than they
        # can be drawn, and draining without limit would stop the window
        # repainting. Whatever is left waits for the next tick, 100ms away.
        try:
            for _ in range(EVENTS_PER_TICK):
                self._handle_event(self.events.get_nowait())
        except Empty:
            pass

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "batch_complete":
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self._write_history()
            failed = sum(j.status in RETRYABLE for j in self.jobs)
            completed = sum(j.status == "Completed" for j in self.jobs)
            self.status_label.setText(
                f"Download complete — {failed} failed, use Retry to try again" if failed else "Download complete"
            )
            for job in self.jobs:
                self._sync_row(job)
            self._update_summary()
            if self.tray and not self.isVisible():
                self.tray.showMessage("Video Batch Downloader", f"Batch finished: {completed} completed, {failed} failed.", QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        if kind == "batch_status":
            return
        job_id = event.get("job_id")
        job = next((item for item in self.jobs if item.job_id == job_id), None)
        if not job:
            return
        if kind == "metadata":
            job.title = event["title"]
            if event.get("thumbnail") and not job.thumbnail:
                job.thumbnail = event["thumbnail"]
                self._want_thumbnail(job.thumbnail)
        elif kind == "media_count":
            job.media_count = int(event.get("count") or 0)
        elif kind == "progress":
            job.downloaded_bytes, job.total_bytes = event["downloaded"], event["total"]
            job.speed, job.eta, job.progress = event["speed"], event["eta"], event["progress"]
        elif kind == "status":
            job.status, job.error, job.output_path = event["status"], event.get("error", ""), event.get("output_path", "")
            job.note = event.get("note", "")
            job.media_count = int(event.get("media_count") or 0)
            if job.status in TERMINAL:
                self._record_history(job)
            self._summary_timer.start()
        self._sync_row(job)

    # -------------------------------------------------------------- tools
    def _check_tools(self) -> None:
        if yt_dlp is None:
            self.tool_label.setText(f"yt-dlp failed to load — {YT_DLP_IMPORT_ERROR}" if YT_DLP_IMPORT_ERROR else "yt-dlp is missing — run: uv sync")
            self.tool_label.setToolTip(YT_DLP_IMPORT_ERROR)
            self.logger.error("yt-dlp import failed: %s", YT_DLP_IMPORT_ERROR)
            self.tool_label.setStyleSheet(f"color: {STATUS_COLORS['Failed']}")
        else:
            self.tool_label.setText("yt-dlp ready")
            self.tool_label.setToolTip("")
            self.tool_label.setStyleSheet(f"color: {STATUS_COLORS['Completed']}")
        self._update_ffmpeg_status()

    def _update_ffmpeg_status(self) -> None:
        """Report where FFmpeg resolved to, in Settings rather than the header."""
        if not hasattr(self, "ffmpeg_status"):
            return
        ffmpeg = find_ffmpeg(self.ffmpeg_edit.text().strip())
        if ffmpeg:
            self.ffmpeg_status.setText(f"Using {ffmpeg}")
            self.ffmpeg_status.setToolTip(ffmpeg)
            self.ffmpeg_status.setStyleSheet(f"color: {STATUS_COLORS['Completed']}")
        else:
            self.ffmpeg_status.setText(
                "Not found — audio conversion is unavailable and separate video/audio streams may not merge."
            )
            self.ffmpeg_status.setToolTip("")
            self.ffmpeg_status.setStyleSheet(f"color: {STATUS_COLORS['Cancelled']}")
        if hasattr(self, "ffmpeg_get_btn"):
            self.ffmpeg_get_btn.setText("Download" if not ffmpeg else "Re-download")

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _fetch_ffmpeg(self, _checked: bool = False) -> None:
        if self._ffmpeg_fetcher is not None:
            return
        existing = find_ffmpeg(self.ffmpeg_edit.text().strip())
        if existing and QMessageBox.question(
            self, "FFmpeg already available",
            f"FFmpeg was found at:\n{existing}\n\nDownload another copy anyway?",
        ) != QMessageBox.StandardButton.Yes:
            return
        version = ffmpeg_setup.latest_version()
        label = f"FFmpeg {version}" if version else "FFmpeg"
        if QMessageBox.question(
            self, "Download FFmpeg",
            f"Download {label} (about 115 MB) from gyan.dev into:\n{ffmpeg_setup.install_dir()}\n\n"
            "The archive is checked against the SHA-256 published alongside it. Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return

        dialog = QProgressDialog("Downloading FFmpeg…", "Cancel", 0, 100, self)
        dialog.setWindowTitle("Download FFmpeg")
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        fetcher = FFmpegFetcher(self)
        dialog.canceled.connect(fetcher.cancel.set)
        fetcher.progressed.connect(self._ffmpeg_progress)
        fetcher.succeeded.connect(self._ffmpeg_done)
        fetcher.failed.connect(self._ffmpeg_failed)
        self._ffmpeg_dialog, self._ffmpeg_fetcher = dialog, fetcher
        self.ffmpeg_get_btn.setEnabled(False)
        fetcher.start()
        dialog.show()

    def _ffmpeg_progress(self, done: int, total: int) -> None:
        if not self._ffmpeg_dialog:
            return
        if total:
            self._ffmpeg_dialog.setValue(int(done / total * 100))
            self._ffmpeg_dialog.setLabelText(f"Downloading FFmpeg…  {format_bytes(done)} / {format_bytes(total)}")
        else:
            self._ffmpeg_dialog.setLabelText(f"Downloading FFmpeg…  {format_bytes(done)}")

    def _finish_ffmpeg_fetch(self) -> None:
        if self._ffmpeg_dialog:
            self._ffmpeg_dialog.close()
        self._ffmpeg_dialog = None
        self._ffmpeg_fetcher = None
        self.ffmpeg_get_btn.setEnabled(True)
        self._check_tools()
        self._format_changed()

    def _ffmpeg_done(self, path: str) -> None:
        self._finish_ffmpeg_fetch()
        self.logger.info("FFmpeg installed at %s", path)
        self.status_label.setText(f"FFmpeg ready at {path}")
        QMessageBox.information(self, "FFmpeg ready", f"FFmpeg was installed at:\n{path}")

    def _ffmpeg_failed(self, message: str) -> None:
        self._finish_ffmpeg_fetch()
        if not message:
            self.status_label.setText("FFmpeg download cancelled")
            return
        self.logger.error("FFmpeg download failed: %s", message)
        QMessageBox.critical(self, "FFmpeg download failed", message)

    def _browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg", "", "FFmpeg (ffmpeg.exe ffmpeg);;All files (*.*)")
        if path:
            self.ffmpeg_edit.setText(path)
            self._check_tools()
            self._format_changed()

    def _mode_changed(self, _: str = "") -> None:
        self.workers_spin.setEnabled(self.mode_box.currentText() == "Parallel")

    # ---------------------------------------------------------- persistence
    def _load_settings(self) -> dict[str, Any]:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "output_folder": self.output_edit.text(),
            "quality": self.quality_box.currentText(),
            "format": self.format_box.currentText(),
            "audio_quality": self.bitrate_box.currentText().split()[0],
            "subtitles": self.subs_box.currentText(),
            "subtitle_langs": self.subs_lang_edit.text().strip() or DEFAULT_SUBTITLE_LANGS,
            "subtitle_auto": self.subs_auto_check.isChecked(),
            "mode": self.mode_box.currentText(),
            "workers": self.workers_spin.value(),
            "skip_existing": self.skip_check.isChecked(),
            "playlists": self.playlist_check.isChecked(),
            "playlist_limit": self.playlist_limit_spin.value(),
            "playlist_folders": self.playlist_folder_check.isChecked(),
            "request_pause": self.pause_spin.value(),
            "rate_limit_retries": self.throttle_retry_spin.value(),
            "spotify": self.spotify_check.isChecked(),
            "spotify_source": self.spotify_source.currentData() or DEFAULT_MATCH_SOURCE,
            "spotify_client_id": self.spotify_id_edit.text().strip(),
            "spotify_client_secret": self.spotify_secret_edit.text().strip(),
            "ffmpeg_path": self.ffmpeg_edit.text(),
            "search_limit": self.search_limit.value(),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            self.logger.error("Failed to write settings: %s", exc)

    def _load_history(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data[-HISTORY_LIMIT:] if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _reindex_history(self) -> None:
        """Rebuild the (url, status) -> position map used to update entries.

        Without it, recording a finished job meant scanning the whole history,
        which turns a long playlist into quadratic work.
        """
        self._history_index = {(entry.get("url", ""), entry.get("status", "")): position
                               for position, entry in enumerate(self.history)}

    def _history_changed(self) -> None:
        """Note that history moved on; the disk write and redraw are batched.

        A 500-video playlist finishes 500 jobs. Writing the file and rebuilding
        the table for each one is what used to wedge the app, so both wait for
        the run of completions to settle.
        """
        self._history_dirty = True
        self._history_stale = True
        self._history_timer.start()

    def _settle_history(self) -> None:
        if self._history_dirty:
            self._flush_history()
        if self._history_stale and self.tabs.currentIndex() == HISTORY_TAB:
            self._render_history()

    def _tab_changed(self, index: int) -> None:
        # The table is only worth rebuilding when someone is looking at it.
        if index == HISTORY_TAB and self._history_stale:
            self._render_history()

    def _record_history(self, job: DownloadJob) -> None:
        entry = {
            "url": job.url,
            "title": job.title,
            "status": job.status,
            "output_path": job.output_path,
            "error": job.error,
            "note": job.note,
            "playlist": job.playlist_title,
            "media_count": job.media_count,
            "downloaded_bytes": job.downloaded_bytes,
            "total_bytes": job.total_bytes,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        key = (job.url, job.status)
        position = self._history_index.get(key)
        if position is not None:
            self.history[position] = entry
        else:
            self._history_index[key] = len(self.history)
            self.history.append(entry)
        self._history_changed()

    def _write_history(self) -> None:
        for job in self.jobs:
            if job.status in TERMINAL:
                self._record_history(job)
        self._flush_history()
        self._history_stale = True
        if self.tabs.currentIndex() == HISTORY_TAB:
            self._render_history()

    def _flush_history(self) -> None:
        if len(self.history) > HISTORY_LIMIT:
            # Keep the file, and the table built from it, to a workable size.
            self.history = self.history[-HISTORY_LIMIT:]
            self._reindex_history()
        try:
            HISTORY_FILE.write_text(json.dumps(self.history, indent=2), encoding="utf-8")
        except OSError as exc:
            self.logger.error("Failed to write history: %s", exc)
        self._history_dirty = False

    def _render_history(self) -> None:
        table = self.history_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        table.setRowCount(len(self.history))
        for row, entry in enumerate(reversed(self.history)):
            status = entry.get("status", "")
            cells = [
                entry.get("timestamp", "").replace("T", "  "),
                entry.get("title") or entry.get("url", ""),
                status,
                entry.get("url", ""),
                entry.get("output_path") or entry.get("error") or "",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if col == 2:
                    item.setForeground(QColor(STATUS_COLORS.get(status, TEXT)))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 4 and not entry.get("output_path") and entry.get("error"):
                    item.setForeground(QColor(STATUS_COLORS["Failed"]))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, entry.get("output_path", ""))
                table.setItem(row, col, item)
        table.setSortingEnabled(True)
        n = len(self.history)
        self.history_count.setText(f"{n} entr{'y' if n == 1 else 'ies'}")

    def _open_history_row(self, row: int, _col: int) -> None:
        item = self.history_table.item(row, 0)
        path = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if not path:
            return
        folder = Path(path).parent
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _clear_history(self) -> None:
        if not self.history:
            return
        answer = QMessageBox.question(self, "Clear history", "Remove all saved download history?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.history = []
        self._reindex_history()
        self._flush_history()
        self._render_history()

    # ------------------------------------------------------- drag and drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            local = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            remote = [u.toString() for u in mime.urls() if not u.isLocalFile()]
            if local:
                self.links_edit.setText(local[0])
                self._show_file_source()
            if remote:
                self._append_direct(" ".join(remote))
        elif mime.hasText():
            self._append_direct(mime.text())
        self.tabs.setCurrentIndex(0)
        self._reload_links()
        event.acceptProposedAction()

    def _append_direct(self, text: str) -> None:
        current = self.direct_edit.toPlainText().rstrip()
        self.direct_edit.setPlainText((current + "\n" + text).strip() if current else text.strip())

    # ---------------------------------------------------------- tray/close
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._exiting or self.tray is None:
            if self._confirm_exit():
                self._shutdown()
                event.accept()
                QApplication.instance().quit()
            else:
                event.ignore()
            return
        event.ignore()
        self.hide()
        self.tray.show()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage("Still running", "Video Batch Downloader is in the system tray. Right-click the icon to show or exit.", QSystemTrayIcon.MessageIcon.Information, 4000)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_window()

    def _show_window(self) -> None:
        if self.tray:
            self.tray.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _confirm_exit(self) -> bool:
        if not self.manager.active:
            return True
        answer = QMessageBox.question(self, "Exit", "A batch is running. Cancel and exit?")
        return answer == QMessageBox.StandardButton.Yes

    def _shutdown(self) -> None:
        if self._playlist_worker is not None:
            self._playlist_worker.cancel.set()
            self._playlist_worker.wait(3000)
        if self.manager.active:
            self.manager.cancel()
        self._save_settings()
        self._write_history()
        if self.tray:
            self.tray.hide()

    def _exit_app(self) -> None:
        if self._exiting:
            return
        if not self._confirm_exit():
            return
        self._exiting = True
        self._shutdown()
        QApplication.instance().quit()


def configure_tls() -> None:
    # Qt's OpenSSL backend crashes once Python's own OpenSSL (ssl / yt-dlp) is loaded in-process;
    # the native backend has no such conflict. Falls through silently on non-Windows.
    if sys.platform == "win32" and "schannel" in QSslSocket.availableBackends():
        QSslSocket.setActiveBackend("schannel")


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    base = QFont()
    base.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "sans-serif"])
    base.setPointSize(10)
    base.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(base)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0d1117"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0d1117"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#11161d"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6edf3"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#21262d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6edf3"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1f6feb"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#161b22"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6edf3"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#545d68"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#58a6ff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#545d68"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#545d68"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#545d68"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE.replace("@ui", UI_ASSETS.as_posix()))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Video Batch Downloader")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    configure_tls()
    apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
