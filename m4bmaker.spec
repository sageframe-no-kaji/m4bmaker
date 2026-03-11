# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for m4bmaker macOS .app bundle
# Run via: scripts/build_macos.sh  OR  python -m PyInstaller m4bmaker.spec

from PyInstaller.utils.hooks import collect_all, collect_data_files

# Pull in all PySide6 binaries, data, and hidden imports so Qt plugins load.
pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")

# Our own resources (icon, svg)
app_datas = collect_data_files(
    "m4bmaker",
    includes=["gui/resources/*"],
)

all_datas = pyside6_datas + app_datas
all_binaries = pyside6_binaries
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
    excludes=["tkinter", "unittest", "xmlrpc"],
    noarchive=False,
)

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
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
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
