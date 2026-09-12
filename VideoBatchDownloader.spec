# PyInstaller spec — build with:  uv run pyinstaller VideoBatchDownloader.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    # yt-dlp resolves extractors lazily by name, so PyInstaller can't see them statically.
    hiddenimports=collect_submodules("yt_dlp"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Qt modules the app never uses; trimming them keeps the exe well under 100 MB.
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtGraphs", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
        "PySide6.QtHttpServer", "PySide6.QtSpatialAudio", "PySide6.QtSvgWidgets", "PySide6.QtXml", "PySide6.QtConcurrent",
        "tkinter", "unittest", "pydoc",
    ],
    noarchive=False,
)

# PyInstaller resolves OpenSSL DLL names through PATH, so a stray copy (e.g. Git's mingw64\bin)
# can shadow the ones Python's _ssl was built against and break "import ssl" in the bundle.
# Pin the interpreter's own copies and drop Qt's OpenSSL plugin (the app uses Schannel).
_py_dlls = Path(sys.base_prefix) / "DLLs"
_ssl_names = {"libssl-3-x64.dll", "libcrypto-3-x64.dll", "libssl-3.dll", "libcrypto-3.dll"}
a.binaries = [
    b for b in a.binaries
    if Path(b[0]).name.lower() not in _ssl_names and not Path(b[0]).name.lower().startswith("qopensslbackend")
]
for name in _ssl_names:
    candidate = _py_dlls / name
    if candidate.is_file():
        a.binaries.append((name, str(candidate), "BINARY"))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoBatchDownloader",
    icon="assets/app_icon.ico",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
)
