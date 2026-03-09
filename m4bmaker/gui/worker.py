"""Background workers for folder loading and audiobook conversion.

Both workers are QThread subclasses that emit typed signals so the GUI
thread never blocks.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from m4bmaker.models import Book
from m4bmaker.pipeline import load_audiobook, run_pipeline


class LoadWorker(QThread):
    """Scan a folder and build a :class:`Book` (may be slow for many files)."""

    finished = Signal(object)  # Book
    error = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        try:
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            book = load_audiobook(self._folder, ffprobe)
            self.finished.emit(book)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class ConvertWorker(QThread):
    """Run :func:`run_pipeline` off the UI thread."""

    progress = Signal(str, float)  # message, 0.0–1.0
    finished = Signal(object)  # PipelineResult
    error = Signal(str)

    def __init__(
        self,
        book: Book,
        output_path: Path,
        bitrate: str = "96k",
        stereo: bool = False,
    ) -> None:
        super().__init__()
        self._book = book
        self._output_path = output_path
        self._bitrate = bitrate
        self._stereo = stereo

    def run(self) -> None:
        try:
            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            result = run_pipeline(
                book=self._book,
                output_path=self._output_path,
                bitrate=self._bitrate,
                stereo=self._stereo,
                cover=self._book.cover,
                progress_callback=self._on_progress,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            self.finished.emit(result)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    def _on_progress(self, message: str, fraction: float) -> None:
        self.progress.emit(message, fraction)
