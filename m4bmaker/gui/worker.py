"""Background workers for folder loading and audiobook conversion.

Both workers are QThread subclasses that emit typed signals so the GUI
thread never blocks.

Signal naming
-------------
Every worker's *custom completion* signal is named ``result_ready`` (or a
descriptive per-class name) rather than ``finished``.  ``QThread`` already
defines a native no-argument ``finished`` signal that fires when the thread's
``run()`` returns; shadowing it with a custom ``finished = Signal(object)``
breaks lifecycle cleanup (``deleteLater`` on native ``finished``).  The custom
signals below never collide with the native one.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from m4bmaker.errors import EncodeCancelled, M4BError
from m4bmaker.models import Book, BookMetadata, Chapter
from m4bmaker.pipeline import load_audiobook, run_pipeline
from m4bmaker.utils import find_ffmpeg, find_ffprobe, get_temp_root, subprocess_flags


class LoadWorker(QThread):
    """Scan a folder and build a :class:`Book` (may be slow for many files)."""

    result_ready = Signal(object)  # Book
    error = Signal(str)

    #: Scan generation stamped by the window at creation; slots read it back
    #: via ``sender()`` to drop results from a superseded scan (H5).
    generation: int = -1

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        try:
            ffprobe = find_ffprobe()
            book = load_audiobook(self._folder, ffprobe)
            self.result_ready.emit(book)
        except M4BError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class ConvertWorker(QThread):
    """Run :func:`run_pipeline` off the UI thread."""

    progress = Signal(str, float)  # message, 0.0–1.0
    result_ready = Signal(object)  # PipelineResult
    cancelled = Signal()  # user cancellation (not an error)
    error = Signal(str)

    def __init__(
        self,
        book: Book,
        output_path: Path,
        bitrate: str = "96k",
        stereo: bool = False,
        sample_rate: int | None = None,
        normalize: bool = False,
    ) -> None:
        super().__init__()
        self._book = book
        self._output_path = output_path
        self._bitrate = bitrate
        self._stereo = stereo
        self._sample_rate = sample_rate
        self._normalize = normalize
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """Signal the running ffmpeg subprocess to stop."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            ffmpeg = find_ffmpeg()
            ffprobe = find_ffprobe()
            result = run_pipeline(
                book=self._book,
                output_path=self._output_path,
                bitrate=self._bitrate,
                stereo=self._stereo,
                sample_rate=self._sample_rate,
                cover=self._book.cover,
                progress_callback=self._on_progress,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                cancel_event=self._cancel_event,
                normalize=self._normalize,
            )
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.result_ready.emit(result)
        except EncodeCancelled:
            self.cancelled.emit()
        except M4BError as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.error.emit(str(exc))

    def _on_progress(self, message: str, fraction: float) -> None:
        self.progress.emit(message, fraction)


class PreflightWorker(QThread):
    """Run audio preflight analysis off the UI thread."""

    result_ready = Signal(object)  # AudioAnalysis
    error = Signal(str)

    def __init__(self, files: list[Path]) -> None:
        super().__init__()
        self._files = files

    def run(self) -> None:
        try:
            ffprobe = find_ffprobe()
            from m4bmaker.preflight import run_preflight

            analysis = run_preflight(self._files, ffprobe)
            self.result_ready.emit(analysis)
        except M4BError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class LoadM4bWorker(QThread):
    """Load chapters and metadata from an existing .m4b file."""

    result_ready = Signal(object)  # tuple (Book, float total_duration_s)
    error = Signal(str)

    #: Scan generation stamped by the window at creation; slots read it back
    #: via ``sender()`` to drop results from a superseded scan (H5).
    generation: int = -1

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            ffprobe = find_ffprobe()
            from m4bmaker.m4b_editor import load_m4b_chapters
            from m4bmaker.metadata import extract_metadata
            from m4bmaker.models import BookMetadata

            chapters, total_duration = load_m4b_chapters(self._path, ffprobe)
            raw_meta = extract_metadata(self._path)
            metadata = BookMetadata(
                title=raw_meta.get("title", ""),
                author=raw_meta.get("author", ""),
                narrator=raw_meta.get("narrator", ""),
                genre=raw_meta.get("genre", ""),
            )
            # Cover extraction via mutagen only — no subprocess.
            # Calling ffmpeg (subprocess.run/fork) from a QThread deadlocks on macOS
            # because Qt multimedia holds CoreAudio locks on the main thread that the
            # forked child inherits in a permanently-locked state.
            cover_path = self._extract_cover_mutagen(self._path)
            book = Book(
                files=[self._path],
                chapters=chapters,
                metadata=metadata,
                cover=cover_path,
                total_duration=total_duration,
            )
            self.result_ready.emit((book, total_duration))
        except M4BError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @staticmethod
    def _extract_cover_mutagen(path: Path) -> "Path | None":
        """Extract cover art using mutagen only — no subprocess, fork-safe."""
        import tempfile

        # .m4b/.m4a: iTunes covr atom
        try:
            from mutagen.mp4 import MP4

            # mutagen ships no type stubs, so its calls are untyped.
            audio = MP4(str(path))  # type: ignore[no-untyped-call]
            covr = audio.tags.get("covr") if audio.tags else None
            if covr:
                cover_data = bytes(covr[0])
                tmp_dir = Path(
                    tempfile.mkdtemp(prefix="m4bmaker_cover_", dir=get_temp_root())
                )
                dest = tmp_dir / "cover.jpg"
                dest.write_bytes(cover_data)
                if dest.stat().st_size > 100:
                    return dest
        except Exception:  # noqa: BLE001
            pass

        # MP3: ID3 APIC frame
        try:
            from mutagen.id3 import ID3

            # mutagen ships no type stubs, so its calls are untyped.
            tags = ID3(str(path))  # type: ignore[no-untyped-call]
            apic_frames = tags.getall("APIC")  # type: ignore[no-untyped-call]
            if apic_frames:
                frame = next((f for f in apic_frames if f.type == 3), apic_frames[0])
                ext = ".jpg" if "jpeg" in frame.mime.lower() else ".png"
                tmp_dir = Path(
                    tempfile.mkdtemp(prefix="m4bmaker_cover_", dir=get_temp_root())
                )
                dest = tmp_dir / f"cover{ext}"
                dest.write_bytes(frame.data)
                if dest.stat().st_size > 100:
                    return dest
        except Exception:  # noqa: BLE001
            pass

        return None


class SaveChaptersWorker(QThread):
    """Rewrite chapter metadata in an .m4b file without re-encoding."""

    result_ready = Signal(object)  # Path (dest)
    error = Signal(str)

    def __init__(
        self,
        source: Path,
        chapters: list[Chapter],
        total_duration: float,
        dest: Path,
        metadata: BookMetadata | None = None,
    ) -> None:
        super().__init__()
        self._source = source
        self._chapters = chapters
        self._total_duration = total_duration
        self._dest = dest
        self._metadata = metadata

    def run(self) -> None:
        try:
            ffmpeg = find_ffmpeg()
            from m4bmaker.m4b_editor import save_m4b_chapters

            save_m4b_chapters(
                self._source,
                self._chapters,
                self._total_duration,
                self._dest,
                ffmpeg,
                metadata=self._metadata,
            )
            self.result_ready.emit(self._dest)
        except M4BError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class SplitWorker(QThread):
    """Export each chapter of an .m4b file as a separate audio file (stream-copy)."""

    progress = Signal(str, float)  # message, 0.0–1.0
    result_ready = Signal(object)  # output_dir: Path
    cancelled = Signal()  # user cancellation (not an error)
    error = Signal(str)

    def __init__(
        self,
        source: Path,
        chapters: list[Chapter],
        total_duration: float,
        output_dir: Path,
    ) -> None:
        super().__init__()
        self._source = source
        self._chapters = chapters
        self._total_duration = total_duration
        self._output_dir = output_dir
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """Ask the split loop to stop between chapters."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            import subprocess as _sp

            ffmpeg = find_ffmpeg()
            self._output_dir.mkdir(parents=True, exist_ok=True)
            total = len(self._chapters)
            ext = self._source.suffix or ".m4a"

            for i, ch in enumerate(self._chapters):
                if self._cancel_event.is_set():
                    self.cancelled.emit()
                    return
                start = ch.start_time
                end = (
                    self._chapters[i + 1].start_time
                    if i + 1 < total
                    else self._total_duration
                )

                safe_title = (
                    "".join(
                        c if c.isalnum() or c in " ._-" else "_" for c in ch.title
                    ).strip()
                    or f"chapter_{i + 1:02d}"
                )
                out_file = self._output_dir / f"{i + 1:02d} - {safe_title}{ext}"

                self.progress.emit(f"Splitting {i + 1}/{total}: {ch.title}", i / total)

                cmd = [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(start),
                    "-to",
                    str(end),
                    "-i",
                    str(self._source),
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "make_zero",
                    str(out_file),
                ]
                result = _sp.run(
                    cmd, capture_output=True, encoding="utf-8", **subprocess_flags()
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg failed on chapter {i + 1}: {result.stderr.strip()}"
                    )

            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.progress.emit("Split complete.", 1.0)
            self.result_ready.emit(self._output_dir)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
