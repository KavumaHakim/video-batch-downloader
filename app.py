"""PySide6 front end for batch video downloads."""

from __future__ import annotations

import datetime
import json
import logging
import re
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QByteArray, QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QIcon, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest, QSslSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QProgressDialog, QSpinBox, QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from downloader import (
    AUDIO_FORMATS, LOSSLESS_AUDIO, YT_DLP_IMPORT_ERROR, DownloadConfig, DownloadJob, DownloadManager,
    find_ffmpeg, yt_dlp,
)
import ffmpeg_setup
from search import MAX_RESULTS, SEARCH_SITES, SearchResult, format_duration, format_views, search_videos


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

TERMINAL = {"Completed", "Failed", "Cancelled", "Skipped"}
RETRYABLE = {"Failed", "Cancelled"}
STATUS_COLORS = {
    "Completed": "#7ee787",
    "Skipped": "#79c0ff",
    "Failed": "#ff7b72",
    "Cancelled": "#ffa657",
    "Downloading": "#58a6ff",
    "Invalid": "#8b949e",
    "Queued": "#c9d1d9",
}
TEXT = "#c9d1d9"
MUTED = "#8b949e"

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
        size = format_bytes(job.total_bytes or job.downloaded_bytes)
        return f"Done  •  {size}" if job.total_bytes or job.downloaded_bytes else "Done"
    if job.status == "Skipped":
        return "Already downloaded"
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

    def __init__(self, generation: int, query: str, prefix: str, limit: int, logger: logging.Logger) -> None:
        super().__init__()
        self.generation, self.query, self.prefix, self.limit, self.logger = generation, query, prefix, limit, logger

    def run(self) -> None:
        try:
            self.finished_ok.emit(self.generation, search_videos(self.query, self.prefix, self.limit, self.logger))
        except Exception as exc:
            self.failed.emit(self.generation, str(exc).strip() or exc.__class__.__name__)


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
        self.job_rows: dict[int, dict[str, Any]] = {}
        self.settings = self._load_settings()
        self.history: list[dict[str, Any]] = self._load_history()
        self._exiting = False
        self._tray_hint_shown = False
        self.tray: QSystemTrayIcon | None = None
        self._ffmpeg_fetcher: FFmpegFetcher | None = None
        self._ffmpeg_dialog: QProgressDialog | None = None
        self.search_results: list[SearchResult] = []
        self._search_worker: SearchWorker | None = None
        self._search_generation = 0
        self._net = QNetworkAccessManager(self)
        self._thumb_cache: dict[str, QPixmap] = {}

        self._build_ui()
        self._build_tray()
        self._check_tools()
        self._render_history()

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(400)
        self._reload_timer.timeout.connect(self._reload_links)

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
        self.tabs.addTab(self._build_settings_tab(), "Settings")
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

        source = QGroupBox("Links  (one per line, or separated by commas or spaces)")
        sl = QVBoxLayout(source)
        sl.setSpacing(8)
        self.direct_edit = QPlainTextEdit()
        self.direct_edit.setPlaceholderText("Paste video links here — https://…  https://…")
        self.direct_edit.setMinimumHeight(110)
        self.direct_edit.textChanged.connect(lambda: self._reload_timer.start())
        sl.addWidget(self.direct_edit)

        meta = QHBoxLayout()
        self.count_label = QLabel("Videos found: 0")
        self.count_label.setObjectName("muted")
        meta.addWidget(self.count_label, 1)
        self.file_toggle = QToolButton()
        self.file_toggle.setText("Load from a file")
        self.file_toggle.setCheckable(True)
        self.file_toggle.setAutoRaise(True)
        self.file_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.file_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.file_toggle.toggled.connect(self._toggle_file_source)
        meta.addWidget(self.file_toggle)
        sl.addLayout(meta)

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
        sl.addWidget(self.file_row)
        layout.addWidget(source)

        self.jobs_table = QTableWidget(0, len(self.JOB_COLS))
        self.jobs_table.setHorizontalHeaderLabels(self.JOB_COLS)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.jobs_table.setShowGrid(False)
        self.jobs_table.setWordWrap(False)
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 44)
        header.resizeSection(2, 170)
        header.resizeSection(3, 390)
        header.resizeSection(4, 110)
        header.resizeSection(5, 84)
        header.setStretchLastSection(False)
        self.jobs_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.jobs_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.jobs_table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.jobs_table, 1)
        return page

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
        worker = SearchWorker(self._search_generation, query, prefix, self.search_limit.value(), self.logger)
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
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        layout.addWidget(opts)

        note = QLabel("Video quality is a maximum height; lower-resolution sources are never upscaled. "
                      "Audio formats download the best available audio stream and convert it with FFmpeg "
                      "(FLAC and WAV are lossless, so bitrate does not apply). "
                      "Settings are saved when a download starts and on exit.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._mode_changed()
        return page

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
        if self.manager.active:
            return
        urls = self._collect_urls()
        prior = {job.url: job for job in self.jobs}
        self.jobs = []
        for index, url in enumerate(urls, 1):
            old = prior.get(url)
            if not is_basic_url(url):
                job = DownloadJob(index, url, status="Invalid")
            elif old:
                job = DownloadJob(index, url, title=old.title, status=old.status, progress=old.progress,
                                  downloaded_bytes=old.downloaded_bytes, total_bytes=old.total_bytes,
                                  output_path=old.output_path, error=old.error)
            else:
                job = DownloadJob(index, url)
            self.jobs.append(job)
        self.count_label.setText(f"Videos found: {len(self.jobs)}")
        self._render_jobs()

    def _render_jobs(self) -> None:
        table = self.jobs_table
        table.setRowCount(0)
        self.job_rows.clear()
        table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            idx = QTableWidgetItem(f"{job.job_id:02d}")
            idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            idx.setForeground(QColor(MUTED))
            table.setItem(row, 0, idx)
            title = QTableWidgetItem(job.title or job.url)
            title.setToolTip(job.url)
            table.setItem(row, 1, title)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper)
            wl.setContentsMargins(8, 0, 8, 0)
            wl.addWidget(bar)
            table.setCellWidget(row, 2, wrapper)
            detail = QTableWidgetItem()
            detail.setFont(MONO_FONT())
            table.setItem(row, 3, detail)
            status = QTableWidgetItem()
            status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 4, status)
            retry = QPushButton("Retry")
            retry.setObjectName("small")
            retry.clicked.connect(lambda _=False, j=job: self._retry_jobs([j]))
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(4, 3, 6, 3)
            rl.addWidget(retry)
            retry.setMinimumWidth(64)
            table.setCellWidget(row, 5, rw)
            self.job_rows[job.job_id] = {"row": row, "bar": bar, "retry": retry, "title": title, "detail": detail, "status": status}
            self._sync_row(job)
        self._update_summary()

    def _sync_row(self, job: DownloadJob) -> None:
        w = self.job_rows.get(job.job_id)
        if not w:
            return
        w["title"].setText(job.title or job.url)
        w["status"].setText(job.status)
        w["status"].setForeground(QColor(STATUS_COLORS.get(job.status, TEXT)))
        w["retry"].setVisible(job.status in RETRYABLE and not self.manager.active)
        text = job_detail(job)
        w["detail"].setText(text)
        w["detail"].setToolTip(text if job.status == "Failed" else "")
        w["detail"].setForeground(QColor(STATUS_COLORS["Failed"] if job.status == "Failed" else MUTED if job.status != "Downloading" else TEXT))
        bar: QProgressBar = w["bar"]
        if job.status == "Downloading" and not job.total_bytes:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 1000)
            bar.setValue(1000 if job.status in {"Completed", "Skipped"} else int(job.progress * 1000))

    def _update_summary(self) -> None:
        completed = sum(j.status == "Completed" for j in self.jobs)
        downloading = sum(j.status == "Downloading" for j in self.jobs)
        queued = sum(j.status == "Queued" for j in self.jobs)
        failed = sum(j.status == "Failed" for j in self.jobs)
        skipped = sum(j.status == "Skipped" for j in self.jobs)
        self.summary_label.setText(
            f"{completed} / {len(self.jobs)} completed   •   {downloading} downloading   •   {queued} queued   •   {skipped} skipped   •   {failed} failed"
        )
        retryable = any(j.status in RETRYABLE for j in self.jobs) and not self.manager.active
        self.retry_btn.setEnabled(retryable)

    # ------------------------------------------------------------- actions
    def _audio_format(self) -> str:
        label = self.format_box.currentText()
        return next((codec for name, codec in FORMAT_CHOICES if name == label), "")

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

    def _require_ffmpeg_for_audio(self) -> bool:
        """True when the batch may proceed; offers the download when it may not."""
        if not self._audio_format() or find_ffmpeg(self.ffmpeg_edit.text().strip()):
            return True
        if not ffmpeg_setup.is_supported():
            QMessageBox.critical(self, "FFmpeg required",
                                 "Audio downloads need FFmpeg. Install it and set its path in Settings.")
            return False
        if QMessageBox.question(
            self, "FFmpeg required",
            f"Saving as {self._audio_format().upper()} needs FFmpeg, which was not found.\n\n"
            "Download it now?",
        ) == QMessageBox.StandardButton.Yes:
            self._fetch_ffmpeg()
        return False

    def _start(self) -> None:
        self._reload_links()
        pending = [j for j in self.jobs if j.status in {"Queued", *RETRYABLE} and is_basic_url(j.url)]
        if not pending:
            QMessageBox.information(self, "Nothing to download", "Add at least one valid URL via the links file or the direct links box.")
            return
        if not self._require_ffmpeg_for_audio():
            return
        self._launch(pending)

    def _retry_failed(self) -> None:
        self._retry_jobs([j for j in self.jobs if j.status in RETRYABLE])

    def _retry_jobs(self, jobs: list[DownloadJob]) -> None:
        jobs = [j for j in jobs if j.status in RETRYABLE and is_basic_url(j.url)]
        if not jobs or self.manager.active:
            return
        for job in jobs:
            job.status, job.error, job.output_path = "Queued", "", ""
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
        self.manager.cancel()
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelling…")

    # -------------------------------------------------------------- events
    def _poll_events(self) -> None:
        try:
            while True:
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
        elif kind == "progress":
            job.downloaded_bytes, job.total_bytes = event["downloaded"], event["total"]
            job.speed, job.eta, job.progress = event["speed"], event["eta"], event["progress"]
        elif kind == "status":
            job.status, job.error, job.output_path = event["status"], event.get("error", ""), event.get("output_path", "")
            if job.status in TERMINAL:
                self._record_history(job)
            self._update_summary()
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
            "mode": self.mode_box.currentText(),
            "workers": self.workers_spin.value(),
            "skip_existing": self.skip_check.isChecked(),
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
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _record_history(self, job: DownloadJob) -> None:
        entry = {
            "url": job.url,
            "title": job.title,
            "status": job.status,
            "output_path": job.output_path,
            "error": job.error,
            "downloaded_bytes": job.downloaded_bytes,
            "total_bytes": job.total_bytes,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        for i, existing in enumerate(self.history):
            if existing.get("url") == job.url and existing.get("status") == job.status:
                self.history[i] = entry
                break
        else:
            self.history.append(entry)
        self._flush_history()
        self._render_history()

    def _write_history(self) -> None:
        for job in self.jobs:
            if job.status in TERMINAL:
                self._record_history(job)
        self._flush_history()

    def _flush_history(self) -> None:
        try:
            HISTORY_FILE.write_text(json.dumps(self.history, indent=2), encoding="utf-8")
        except OSError as exc:
            self.logger.error("Failed to write history: %s", exc)

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
