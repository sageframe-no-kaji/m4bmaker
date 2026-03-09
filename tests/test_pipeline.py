"""Tests for m4bmaker.pipeline — load_audiobook and run_pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from m4bmaker.models import Book, BookMetadata, Chapter, PipelineResult
from m4bmaker.pipeline import load_audiobook, run_pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ffprobe_stdout(duration: float) -> str:
    return json.dumps({"format": {"duration": str(duration)}})


def _make_popen_mock() -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = iter([])
    proc.stderr = iter([])
    proc.wait.return_value = 0
    return proc


# ---------------------------------------------------------------------------
# load_audiobook
# ---------------------------------------------------------------------------


class TestLoadAudiobook:
    def test_returns_book(self, tmp_path: Path) -> None:
        stub = tmp_path / "01 - Prologue.mp3"
        stub.write_bytes(b"\x00")
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(60.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            book = load_audiobook(tmp_path, "ffprobe")
        assert isinstance(book, Book)
        assert len(book.files) == 1

    def test_chapters_indexed_from_one(self, tmp_path: Path) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(10.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            book = load_audiobook(tmp_path, "ffprobe")
        assert book.chapters[0].index == 1

    def test_chapter_source_file_set(self, tmp_path: Path) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(10.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            book = load_audiobook(tmp_path, "ffprobe")
        assert book.chapters[0].source_file == stub

    def test_start_time_in_seconds_cumulative(self, tmp_path: Path) -> None:
        for i in [1, 2]:
            (tmp_path / f"0{i}.mp3").write_bytes(b"\x00")
        durations = [10.0, 20.0]
        call_count = [0]

        def _side_effect(cmd: list[str], **kw: object) -> MagicMock:
            m = MagicMock()
            m.stdout = _ffprobe_stdout(durations[call_count[0]])
            call_count[0] += 1
            return m

        with patch("m4bmaker.chapters.subprocess.run", side_effect=_side_effect):
            book = load_audiobook(tmp_path, "ffprobe")

        assert book.chapters[0].start_time == 0.0
        assert book.chapters[1].start_time == 10.0

    def test_cover_detected_in_directory(self, tmp_path: Path) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\x00")
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(10.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            book = load_audiobook(tmp_path, "ffprobe")
        assert book.cover is not None

    def test_list_of_files_accepted(self, tmp_path: Path) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(5.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            book = load_audiobook([stub], "ffprobe")
        assert len(book.files) == 1
        assert book.files[0] == stub

    def test_progress_fn_called(self, tmp_path: Path) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        calls: list[tuple[int, int, str]] = []
        mock = MagicMock()
        mock.stdout = _ffprobe_stdout(10.0)
        with patch("m4bmaker.chapters.subprocess.run", return_value=mock):
            load_audiobook(
                tmp_path, "ffprobe", progress_fn=lambda i, t, n: calls.append((i, t, n))
            )
        assert len(calls) == 1
        assert calls[0] == (1, 1, stub.name)


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


class TestRunPipeline:
    def _make_book(self, tmp_path: Path) -> Book:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        return Book(
            files=[stub],
            chapters=[Chapter(index=1, start_time=0.0, title="Ch", source_file=stub)],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
        )

    def _mock_ffprobe(self, duration: float = 10.0) -> MagicMock:
        m = MagicMock()
        m.stdout = _ffprobe_stdout(duration)
        return m

    def test_returns_pipeline_result(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert isinstance(result, PipelineResult)

    def test_chapter_count_correct(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert result.chapter_count == 1

    def test_output_file_path_in_result(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert result.output_file == out

    def test_duration_seconds_in_result(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        with (
            patch(
                "m4bmaker.chapters.subprocess.run",
                return_value=self._mock_ffprobe(42.0),
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert abs(result.duration_seconds - 42.0) < 1e-6

    def test_progress_callback_called(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        calls: list[tuple[str, float]] = []
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            run_pipeline(
                book,
                out,
                progress_callback=lambda msg, frac: calls.append((msg, frac)),
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
            )
        assert len(calls) >= 1

    def test_cover_passed_through(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\x00")
        out = tmp_path / "out.m4b"
        ffmpeg_cmds: list[list[str]] = []

        def _fake_popen(cmd: list[str], **kw: object) -> MagicMock:
            ffmpeg_cmds.append(cmd)
            return _make_popen_mock()

        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen),
        ):
            run_pipeline(book, out, cover=cover, ffmpeg="ffmpeg", ffprobe="ffprobe")

        assert any(str(cover) in " ".join(cmd) for cmd in ffmpeg_cmds)

    def test_empty_chapters_zero_total_duration(self, tmp_path: Path) -> None:
        """book.chapters=[] → total_duration_s=0.0, no ffprobe call needed."""
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        book = Book(
            files=[stub],
            chapters=[],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
        )
        out = tmp_path / "out.m4b"
        with patch(
            "m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert result.duration_seconds == 0.0
        assert result.chapter_count == 0

    def test_no_source_file_multi_chapter_uses_gap(self, tmp_path: Path) -> None:
        """source_file=None with 2+ chapters → total derived from inter-chapter gap."""
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        book = Book(
            files=[stub],
            chapters=[
                Chapter(index=1, start_time=0.0, title="Ch1", source_file=None),
                Chapter(index=2, start_time=15.0, title="Ch2", source_file=None),
            ],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
        )
        out = tmp_path / "out.m4b"
        with patch(
            "m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        # total_duration_s = last_ch.start_time + gap = 15.0 + 15.0 = 30.0
        assert abs(result.duration_seconds - 30.0) < 1e-6

    def test_no_source_file_single_chapter_gap_is_zero(self, tmp_path: Path) -> None:
        """source_file=None with only 1 chapter → gap=0.0, duration=start_time."""
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        book = Book(
            files=[stub],
            chapters=[
                Chapter(index=1, start_time=0.0, title="Only", source_file=None),
            ],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
        )
        out = tmp_path / "out.m4b"
        with patch(
            "m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert result.duration_seconds == 0.0

    def test_explicit_tmp_dir_used_directly(self, tmp_path: Path) -> None:
        """Passing _tmp_dir skips TemporaryDirectory and writes files in-place."""
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        tmp_dir = tmp_path / "explicit_tmp"
        tmp_dir.mkdir()
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
        ):
            result = run_pipeline(
                book, out, ffmpeg="ffmpeg", ffprobe="ffprobe", _tmp_dir=tmp_dir
            )
        assert isinstance(result, PipelineResult)
        # ffmetadata and concat files written into the explicit tmp dir
        assert (tmp_dir / "ffmetadata.txt").exists()
        assert (tmp_dir / "concat.txt").exists()
