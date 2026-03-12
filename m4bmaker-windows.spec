# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for m4bmaker Windows .exe
# Built by GitHub Actions on windows-latest runner.

from PyInstaller.utils.hooks import collect_all, collect_data_files

pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")

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
    upx=False,
    console=False,           # windowed app; no terminal window
    argv_emulation=False,
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
