"""Phase 6D verification — LoadWorker and ConvertWorker."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402

from m4bmaker.errors import EncodeCancelled, M4BError  # noqa: E402
from m4bmaker.gui.worker import (  # noqa: E402
    ConvertWorker,
    LoadWorker,
    PreflightWorker,
    LoadM4bWorker,
    SaveChaptersWorker,
    SplitWorker,
)  # noqa: E402
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
            patch("m4bmaker.gui.worker.find_ffprobe", return_value="/usr/bin/ffprobe"),
            patch("m4bmaker.gui.worker.load_audiobook", return_value=book),
        ):
            worker = LoadWorker(tmp_path)
            worker.result_ready.connect(results.append)
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

    def test_error_emits_on_m4berror(self, qapp, tmp_path):
        """Library now raises M4BError instead of sys.exit; it maps to error."""
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.load_audiobook",
            side_effect=M4BError("no ffprobe"),
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
            worker.result_ready.connect(finished.append)
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
            patch("m4bmaker.gui.worker.find_ffmpeg", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.gui.worker.run_pipeline", return_value=result),
        ):
            worker = ConvertWorker(book=book, output_path=out)
            worker.result_ready.connect(results.append)
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

    def test_error_emits_on_m4berror(self, qapp, tmp_path):
        """run_pipeline now raises M4BError instead of sys.exit."""
        book = _make_book(tmp_path)
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.run_pipeline",
            side_effect=M4BError("no ffmpeg"),
        ):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert "no ffmpeg" in errors[0]

    def test_encode_cancelled_emits_cancelled_not_error(self, qapp, tmp_path):
        """EncodeCancelled maps to the cancelled signal, never to error."""
        book = _make_book(tmp_path)
        cancelled: list = []
        errors: list[str] = []
        results: list = []

        with patch(
            "m4bmaker.gui.worker.run_pipeline",
            side_effect=EncodeCancelled("stopped"),
        ):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.cancelled.connect(lambda: cancelled.append(True))
            worker.error.connect(errors.append)
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert cancelled == [True]
        assert errors == []
        assert results == []

    def test_request_cancel_sets_event_and_cancelled_wins(self, qapp, tmp_path):
        """When cancel is requested, a returning pipeline emits cancelled."""
        book = _make_book(tmp_path)
        out = tmp_path / "out.m4b"
        cancelled: list = []
        results: list = []

        def _fake_run_pipeline(**kwargs):
            # Simulate the user cancelling while the encode is mid-flight.
            worker.request_cancel()
            return PipelineResult(
                output_file=out, chapter_count=1, duration_seconds=1.0
            )

        with patch("m4bmaker.gui.worker.run_pipeline", side_effect=_fake_run_pipeline):
            worker = ConvertWorker(book=book, output_path=out)
            worker.cancelled.connect(lambda: cancelled.append(True))
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert cancelled == [True]
        assert results == []

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
            worker.result_ready.connect(finished.append)
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert finished == []


# ── PreflightWorker ───────────────────────────────────────────────────────────


class TestPreflightWorker:
    def test_finished_emits_analysis(self, qapp, tmp_path):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        analysis = AudioAnalysis(file_count=1, sample_rates=Counter({44100: 1}))
        results = []

        f = tmp_path / "t.mp3"
        f.write_bytes(b"\x00")

        with (
            patch("m4bmaker.gui.worker.find_ffprobe", return_value="/usr/bin/ffprobe"),
            patch("m4bmaker.preflight.run_preflight", return_value=analysis),
        ):
            worker = PreflightWorker([f])
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(results) == 1
        assert results[0] is analysis

    def test_error_on_exception(self, qapp, tmp_path):
        errors = []
        f = tmp_path / "t.mp3"
        f.write_bytes(b"\x00")

        with patch("m4bmaker.preflight.run_preflight", side_effect=RuntimeError("bad")):
            worker = PreflightWorker([f])
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors == ["bad"]


# ── LoadM4bWorker ─────────────────────────────────────────────────────────────


class TestLoadM4bWorker:
    def test_finished_emits_book_and_duration(self, qapp, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        chapter = Chapter(index=1, start_time=0.0, title="Ch1", source_file=p)
        results = []

        with (
            patch("m4bmaker.gui.worker.find_ffprobe", return_value="/usr/bin/ffprobe"),
            patch(
                "m4bmaker.m4b_editor.load_m4b_chapters", return_value=([chapter], 120.0)
            ),
            patch(
                "m4bmaker.metadata.extract_metadata",
                return_value={"title": "T", "author": "A", "narrator": "N"},
            ),
        ):
            worker = LoadM4bWorker(p)
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(results) == 1
        book, duration = results[0]
        assert duration == 120.0
        assert book.metadata.title == "T"

    def test_error_on_exception(self, qapp, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        errors = []

        with patch(
            "m4bmaker.m4b_editor.load_m4b_chapters", side_effect=RuntimeError("fail")
        ):
            worker = LoadM4bWorker(p)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors == ["fail"]


# ── SaveChaptersWorker ────────────────────────────────────────────────────────


class TestSaveChaptersWorker:
    def _chapters(self, tmp_path: Path) -> list[Chapter]:
        f = tmp_path / "book.m4b"
        f.write_bytes(b"\x00" * 32)
        return [Chapter(index=1, start_time=0.0, title="Ch1", source_file=f)]

    def test_finished_emits_dest(self, qapp, tmp_path):
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00")
        dest = tmp_path / "out.m4b"
        chapters = self._chapters(tmp_path)
        results = []

        with (
            patch("m4bmaker.gui.worker.find_ffmpeg", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.m4b_editor.save_m4b_chapters"),
        ):
            worker = SaveChaptersWorker(source, chapters, 60.0, dest)
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert results == [dest]

    def test_metadata_passed_to_save(self, qapp, tmp_path):
        """BookMetadata supplied to the worker must be forwarded to save_m4b_chapters."""
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00")
        dest = tmp_path / "out.m4b"
        chapters = self._chapters(tmp_path)
        meta = BookMetadata(title="Test", author="Auth", narrator="Narr", genre="Gen")
        captured: list[dict] = []

        def fake_save(src, ch, dur, dst, ffmpeg, *, metadata=None):
            captured.append({"metadata": metadata})

        with patch("m4bmaker.m4b_editor.save_m4b_chapters", side_effect=fake_save):
            worker = SaveChaptersWorker(source, chapters, 60.0, dest, metadata=meta)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert captured, "save_m4b_chapters was not called"
        assert captured[0]["metadata"] == meta

    def test_error_on_exception(self, qapp, tmp_path):
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00")
        dest = tmp_path / "out.m4b"
        chapters = self._chapters(tmp_path)
        errors = []

        with patch(
            "m4bmaker.m4b_editor.save_m4b_chapters", side_effect=RuntimeError("oops")
        ):
            worker = SaveChaptersWorker(source, chapters, 60.0, dest)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors == ["oops"]


# ── SplitWorker ───────────────────────────────────────────────────────────────


class TestSplitWorker:
    @staticmethod
    def _chapters(tmp_path: Path):
        f = tmp_path / "book.m4b"
        f.write_bytes(b"\x00")
        return [
            Chapter(index=1, start_time=0.0, title="Intro", source_file=f),
            Chapter(index=2, start_time=30.0, title="Part Two", source_file=f),
        ]

    def test_emits_finished_on_success(self, qapp, tmp_path):
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00")
        out_dir = tmp_path / "chapters"
        results = []

        import subprocess

        mock_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            worker = SplitWorker(source, self._chapters(tmp_path), 60.0, out_dir)
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(results) == 1
        assert Path(results[0]) == out_dir

    def test_emits_error_on_ffmpeg_failure(self, qapp, tmp_path):
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00")
        out_dir = tmp_path / "chapters"
        errors = []

        import subprocess

        mock_result = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="ffmpeg died"
        )
        with patch("subprocess.run", return_value=mock_result):
            worker = SplitWorker(source, self._chapters(tmp_path), 60.0, out_dir)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert len(errors) == 1
        assert "ffmpeg" in errors[0].lower() or "chapter" in errors[0].lower()

    def test_creates_output_dir(self, qapp, tmp_path):
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00")
        out_dir = tmp_path / "deep" / "chapters"

        import subprocess

        mock_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            worker = SplitWorker(source, self._chapters(tmp_path), 60.0, out_dir)
            worker.start()
            worker.wait(3000)

        assert out_dir.is_dir()

    def test_cancel_before_start_emits_cancelled_not_finished(self, qapp, tmp_path):
        """A cancel requested before the loop runs stops cleanly with cancelled."""
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00")
        out_dir = tmp_path / "chapters"
        cancelled: list = []
        results: list = []

        import subprocess

        mock_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            worker = SplitWorker(source, self._chapters(tmp_path), 60.0, out_dir)
            worker.request_cancel()  # cancel before starting
            worker.cancelled.connect(lambda: cancelled.append(True))
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert cancelled == [True]
        assert results == []
