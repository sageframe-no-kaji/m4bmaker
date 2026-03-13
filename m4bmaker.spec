# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for m4bmaker macOS .app bundle
# Run via: scripts/build_macos.sh  OR  python -m PyInstaller m4bmaker.spec

from PyInstaller.utils.hooks import collect_all, collect_data_files

# Pull in all PySide6 binaries, data, and hidden imports so Qt plugins load,
# then strip the heavy unused modules (WebEngine = 280 MB Chromium, etc.)
pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")

# Modules this app never uses — strip them to reduce bundle size dramatically.
_STRIP = [
    "WebEngine",        # Chromium — 280 MB
    "QtPdf",            # PDF renderer — 8.5 MB
    "Qt3D",             # 3-D rendering stack
    "QtDesigner",       # UI designer tool
    "QtCharts",         # charts
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",       # maps / positioning
    "QtQuick",          # QML/Quick runtime (not used in pure-Widgets app)
    "QtQml",
    "ShaderTools",
    "qmlls",            # QML language-server binary
    "qmlformat",        # QML formatter binary
    "Assistant.app",    # Qt Assistant docs app
    "Linguist.app",     # Qt Linguist translation tool
]

def _keep(path):
    p = str(path)
    return not any(pat in p for pat in _STRIP)

pyside6_datas    = [(s, d)    for s, d    in pyside6_datas    if _keep(s)]
pyside6_binaries = [(s, d) for s, d in pyside6_binaries if _keep(s)]
pyside6_hidden   = [m         for m        in pyside6_hidden   if _keep(m)]

# Bundle ffmpeg and ffprobe so the app is fully self-contained (no system install needed)
# static_ffmpeg provides arm64/x86_64 builds that only depend on macOS system frameworks.
from static_ffmpeg import run as _sfr
_FFMPEG_BIN, _FFPROBE_BIN = _sfr.get_or_fetch_platform_executables_else_raise()

# Our own resources (icon, svg)
app_datas = collect_data_files(
    "m4bmaker",
    includes=["gui/resources/*"],
)

all_datas = pyside6_datas + app_datas
all_binaries = pyside6_binaries + [
    (_FFMPEG_BIN, "."),   # bundled inside m4bmaker.app/Contents/MacOS/
    (_FFPROBE_BIN, "."),
]
all_hidden = pyside6_hidden + [
    # Core package
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
    # GUI package
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
    # Third-party runtime deps
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
        # Heavy Qt modules not used by this app
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

# Post-analysis strip: remove unused Qt frameworks that the dependency scanner
# pulled back in despite the excludes list above.
a.binaries = [(s, d, t) for s, d, t in a.binaries if _keep(s)]
a.datas    = [(s, d, t) for s, d, t in a.datas    if _keep(s)]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="m4bmaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt Qt dylibs on macOS — keep off
    console=False,      # windowed app; no terminal
    argv_emulation=False,
    target_arch=None,   # None = match current machine; set "universal2" for fat binary
    codesign_identity=None,
    entitlements_file=None,
    icon="m4bmaker/gui/resources/audiobookbinder.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="m4bmaker",
)

app = BUNDLE(
    coll,
    name="m4bmaker.app",
    icon="m4bmaker/gui/resources/audiobookbinder.icns",
    bundle_identifier="com.sageframe.m4bmaker",
    info_plist={
        "CFBundleDisplayName": "m4bmaker",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,   # supports dark mode
        "LSMinimumSystemVersion": "13.0",
        "NSHumanReadableCopyright": "© 2026 Sageframe",
        # Allow drag-and-drop of audio folders onto the Dock icon
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Folder",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.folder"],
            },
            {
                "CFBundleTypeName": "M4B Audiobook",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.mpeg-4-audio"],
                "CFBundleTypeExtensions": ["m4b"],
            },
        ],
    },
)
