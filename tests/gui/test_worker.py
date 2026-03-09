"""Phase 6D verification — LoadWorker and ConvertWorker."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from m4bmaker.gui.worker import ConvertWorker, LoadWorker  # noqa: E402
from m4bmaker.models import Book, BookMetadata, Chapter, PipelineResult  # noqa: E402

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_book(tmp_path: Path) -> Book:
    f = tmp_path / "01.mp3"
    f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return Book(
        files=[f],
        chapters=[Chapter(index=1, start_time=0.0, title="Intro", source_file=f)],
        metadata=BookMetadata(title="T", author="A", narrator="N", genre="G"),
        cover=None,
    )


# ── LoadWorker ────────────────────────────────────────────────────────────────


class TestLoadWorker:
    def test_finished_emits_book(self, qapp, tmp_path):
        results: list[Book] = []
        book = _make_book(tmp_path)

        with (
            patch("m4bmaker.gui.worker.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("m4bmaker.gui.worker.load_audiobook", return_value=book),
        ):
            worker = LoadWorker(tmp_path)
            worker.finished.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(results) == 1
        assert results[0] is book

    def test_error_emits_on_exception(self, qapp, tmp_path):
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.load_audiobook", side_effect=RuntimeError("bad")
        ):
            worker = LoadWorker(tmp_path)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors == ["bad"]

    def test_error_emits_on_sysexit(self, qapp, tmp_path):
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.load_audiobook",
            side_effect=SystemExit("no ffprobe"),
        ):
            worker = LoadWorker(tmp_path)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert "no ffprobe" in errors[0]

    def test_no_finished_on_error(self, qapp, tmp_path):
        finished: list = []
        with patch("m4bmaker.gui.worker.load_audiobook", side_effect=RuntimeError("x")):
            worker = LoadWorker(tmp_path)
            worker.finished.connect(finished.append)
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert finished == []


# ── ConvertWorker ─────────────────────────────────────────────────────────────


class TestConvertWorker:
    def test_finished_emits_result(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        out = tmp_path / "out.m4b"
        result = PipelineResult(output_file=out, chapter_count=1, duration_seconds=60.0)
        results: list[PipelineResult] = []

        with (
            patch("m4bmaker.gui.worker.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.gui.worker.run_pipeline", return_value=result),
        ):
            worker = ConvertWorker(book=book, output_path=out)
            worker.finished.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(results) == 1
        assert results[0].output_file == out

    def test_error_emits_on_exception(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.run_pipeline", side_effect=RuntimeError("enc err")
        ):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors == ["enc err"]

    def test_error_emits_on_sysexit(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.run_pipeline",
            side_effect=SystemExit("no ffmpeg"),
        ):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert "no ffmpeg" in errors[0]

    def test_progress_callback_emits_signal(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        out = tmp_path / "out.m4b"
        progress_calls: list[tuple[str, float]] = []

        def _fake_run_pipeline(**kwargs):
            cb = kwargs.get("progress_callback")
            if cb:
                cb("Encoding…", 0.5)
            return PipelineResult(
                output_file=out, chapter_count=1, duration_seconds=1.0
            )

        with patch("m4bmaker.gui.worker.run_pipeline", side_effect=_fake_run_pipeline):
            worker = ConvertWorker(book=book, output_path=out)
            worker.progress.connect(lambda m, f: progress_calls.append((m, f)))
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert ("Encoding…", 0.5) in progress_calls

    def test_bitrate_and_stereo_forwarded(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        out = tmp_path / "out.m4b"
        captured: dict = {}

        def _fake_run_pipeline(**kwargs):
            captured.update(kwargs)
            return PipelineResult(
                output_file=out, chapter_count=1, duration_seconds=1.0
            )

        with patch("m4bmaker.gui.worker.run_pipeline", side_effect=_fake_run_pipeline):
            worker = ConvertWorker(
                book=book, output_path=out, bitrate="192k", stereo=True
            )
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert captured["bitrate"] == "192k"
        assert captured["stereo"] is True

    def test_no_finished_on_error(self, qapp, tmp_path):
        book = _make_book(tmp_path)
        finished: list = []
        with patch("m4bmaker.gui.worker.run_pipeline", side_effect=RuntimeError("x")):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.finished.connect(finished.append)
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert finished == []
