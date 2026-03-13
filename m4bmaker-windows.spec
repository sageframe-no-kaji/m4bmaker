# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for m4bmaker Windows .exe
# Built by GitHub Actions on windows-latest runner.

from PyInstaller.utils.hooks import collect_all, collect_data_files

pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")

# Modules this app never uses — strip to reduce bundle size dramatically.
_STRIP = [
    "WebEngine",        # Chromium — 280 MB
    "QtPdf",            # PDF renderer
    "Qt3D",             # 3-D rendering stack
    "QtDesigner",       # UI designer tool
    "QtCharts",
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",
    "QtQuick",          # QML/Quick runtime
    "QtQml",
    "ShaderTools",
    "qmlls",
    "qmlformat",
    "designer.exe",
    "assistant.exe",
    "linguist.exe",
]

def _keep(path):
    p = str(path)
    return not any(pat in p for pat in _STRIP)

pyside6_datas    = [(s, d) for s, d in pyside6_datas    if _keep(s)]
pyside6_binaries = [(s, d) for s, d in pyside6_binaries if _keep(s)]
pyside6_hidden   = [m      for m    in pyside6_hidden   if _keep(m)]

# Bundle static ffmpeg and ffprobe (no system install required)
from static_ffmpeg import run as _sfr
_FFMPEG_BIN, _FFPROBE_BIN = _sfr.get_or_fetch_platform_executables_else_raise()

app_datas = collect_data_files(
    "m4bmaker",
    includes=["gui/resources/*"],
)

all_datas = pyside6_datas + app_datas
all_binaries = pyside6_binaries + [
    (_FFMPEG_BIN, "."),
    (_FFPROBE_BIN, "."),
]
all_hidden = pyside6_hidden + [
    "m4bmaker",
    "m4bmaker.chapters",
    "m4bmaker.chapters_file",
    "m4bmaker.cli",
    "m4bmaker.cover",
    "m4bmaker.encoder",
    "m4bmaker.m4b_editor",
    "m4bmaker.metadata",
    "m4bmaker.models",
    "m4bmaker.pipeline",
    "m4bmaker.preflight",
    "m4bmaker.repair",
    "m4bmaker.scanner",
    "m4bmaker.utils",
    "m4bmaker.gui",
    "m4bmaker.gui.app",
    "m4bmaker.gui.job",
    "m4bmaker.gui.player",
    "m4bmaker.gui.queue_manager",
    "m4bmaker.gui.queue_window",
    "m4bmaker.gui.styles",
    "m4bmaker.gui.widgets",
    "m4bmaker.gui.window",
    "m4bmaker.gui.worker",
    "mutagen",
    "mutagen.mp3",
    "mutagen.mp4",
    "mutagen.flac",
    "mutagen.ogg",
    "mutagen.id3",
    "natsort",
]

a = Analysis(
    ["m4bmaker/gui/app.py"],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "xmlrpc",
        "PySide6.QtWebEngine", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation", "PySide6.Qt3DLogic",
        "PySide6.QtDesigner", "PySide6.QtDesignerComponents",
        "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtGraphs", "PySide6.QtLocation",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQmlCompiler",
        "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets", "PySide6.QtShaderTools",
        "PySide6.QtPositioning", "PySide6.QtSensors",
        "PySide6.QtVirtualKeyboard", "PySide6.QtTextToSpeech",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtStateMachine", "PySide6.QtSpatialAudio",
        "PySide6.QtNfc", "PySide6.QtBluetooth",
        "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    ],
    noarchive=False,
)

# Post-analysis strip: remove unused Qt modules the dependency scanner pulled back in.
a.binaries = [(s, d, t) for s, d, t in a.binaries if _keep(s)]
a.datas    = [(s, d, t) for s, d, t in a.datas    if _keep(s)]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="m4Bookmaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # windowed app; no terminal window
    icon="m4bmaker/gui/resources/audiobookbinder.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="m4Bookmaker",
)
