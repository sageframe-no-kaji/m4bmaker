"""Tests for m4bmaker.pipeline — load_audiobook and run_pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from m4bmaker.errors import M4BError
from m4bmaker.models import Book, BookMetadata, Chapter, PipelineResult
from m4bmaker.pipeline import load_audiobook, run_pipeline
from m4bmaker.preflight import AudioAnalysis

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


def _fake_encode_popen(cmd: list[str], **_: object) -> MagicMock:
    """Popen side_effect that writes the .partial output file on success.

    encode() now stages output at a sibling ".partial" path and
    os.replace()s it onto the real output only on success — the mock must
    create that file or os.replace() raises FileNotFoundError.
    """
    Path(cmd[-1]).write_bytes(b"FAKE-M4B")
    return _make_popen_mock()


def _uniform_codec_analysis() -> AudioAnalysis:
    """A single-codec AudioAnalysis so _check_codec_uniformity is a no-op."""
    return AudioAnalysis(file_count=1)


# ---------------------------------------------------------------------------
# load_audiobook
# ---------------------------------------------------------------------------


class TestLoadAudiobook:
    @pytest.fixture(autouse=True)
    def _mock_ffmpeg(self) -> None:  # noqa: ANN001
        """load_audiobook may call find_ffmpeg() for cover extraction."""
        with patch("m4bmaker.pipeline.find_ffmpeg", return_value="/usr/bin/ffmpeg"):
            yield

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
        # build_chapters calls get_duration for each file (10, 20),
        # then load_audiobook calls get_duration once more for files[-1] (20).
        durations = [10.0, 20.0, 20.0]
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
    @pytest.fixture(autouse=True)
    def _no_repair(self):
        """Bypass the repair subprocess calls for all pipeline encoding tests."""
        with patch("m4bmaker.repair.needs_repair", return_value=False):
            yield

    @pytest.fixture(autouse=True)
    def _uniform_codecs(self):
        """Bypass the codec-uniformity preflight check by default."""
        with patch(
            "m4bmaker.pipeline.run_preflight", return_value=_uniform_codec_analysis()
        ):
            yield

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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
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
            Path(cmd[-1]).write_bytes(b"FAKE-M4B")
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
        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert result.duration_seconds == 0.0
        assert result.chapter_count == 0

    def test_no_source_file_uses_book_total_duration(self, tmp_path: Path) -> None:
        """source_file=None (chapters-file case) → total_duration_s comes
        from book.total_duration (set by load_audiobook), not a heuristic
        derived from inter-chapter gaps."""
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
            total_duration=99.0,
        )
        out = tmp_path / "out.m4b"
        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert abs(result.duration_seconds - 99.0) < 1e-6

    def test_no_source_file_single_chapter_uses_book_total_duration(
        self, tmp_path: Path
    ) -> None:
        stub = tmp_path / "01.mp3"
        stub.write_bytes(b"\x00")
        book = Book(
            files=[stub],
            chapters=[
                Chapter(index=1, start_time=0.0, title="Only", source_file=None),
            ],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
            total_duration=42.0,
        )
        out = tmp_path / "out.m4b"
        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert abs(result.duration_seconds - 42.0) < 1e-6

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
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
        ):
            result = run_pipeline(
                book, out, ffmpeg="ffmpeg", ffprobe="ffprobe", _tmp_dir=tmp_dir
            )
        assert isinstance(result, PipelineResult)
        # ffmetadata and concat files written into the explicit tmp dir
        assert (tmp_dir / "ffmetadata.txt").exists()
        assert (tmp_dir / "concat.txt").exists()

    def test_codec_mismatch_raises_m4berror(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        mismatched = AudioAnalysis(file_count=2)
        mismatched.codecs["mp3"] = 1
        mismatched.codecs["flac"] = 1
        with (
            patch("m4bmaker.pipeline.run_preflight", return_value=mismatched),
            patch(
                "m4bmaker.pipeline.probe_file",
                return_value=MagicMock(codec_name="mp3"),
            ),
        ):
            with pytest.raises(M4BError, match="codec"):
                run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")

    def test_repair_result_injection_skips_internal_repair(
        self, tmp_path: Path
    ) -> None:
        """Passing repair_result= must skip the internal run_repair call."""
        from m4bmaker.repair import RepairResult

        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        injected = RepairResult(total=1, repaired=0)

        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe()
            ),
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
            patch("m4bmaker.repair.run_repair") as mock_run_repair,
        ):
            run_pipeline(
                book,
                out,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                repair_result=injected,
            )

        mock_run_repair.assert_not_called()

    def test_chapters_retimed_after_repair_shortens_file(self, tmp_path: Path) -> None:
        """When repair actually shortens a file, chapter start_times for
        every subsequent chapter must be rebuilt from the repaired
        (post-repair) durations, not the stale pre-repair durations."""
        from m4bmaker.repair import RepairResult

        file_a = tmp_path / "01.mp3"
        file_b = tmp_path / "02.mp3"
        file_a.write_bytes(b"\x00")
        file_b.write_bytes(b"\x00")
        cleaned_a = tmp_path / "repaired" / "000_01.mp3"

        book = Book(
            files=[file_a, file_b],
            # Pre-repair chapter 2 start_time (20.0) assumed file_a was 20s;
            # after repair it's actually only 8s.
            chapters=[
                Chapter(index=1, start_time=0.0, title="Ch1", source_file=file_a),
                Chapter(index=2, start_time=20.0, title="Ch2", source_file=file_b),
            ],
            metadata=BookMetadata(title="T", author="A", narrator="N"),
            cover=None,
        )
        out = tmp_path / "out.m4b"
        injected_repair = RepairResult(
            total=2, repaired=1, repaired_paths=[(file_a, cleaned_a)]
        )

        # get_duration returns 8.0 for the repaired file_a, 12.0 for file_b —
        # both probed post-repair during retiming.
        def _fake_duration(path: Path, ffprobe: str) -> float:
            if path == cleaned_a:
                return 8.0
            if path == file_b:
                return 12.0
            raise AssertionError(f"unexpected probe target: {path}")

        with (
            patch("m4bmaker.pipeline.get_duration", side_effect=_fake_duration),
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
        ):
            result = run_pipeline(
                book,
                out,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                repair_result=injected_repair,
            )

        # Chapter 2 now starts at 8.0 (repaired file_a's real duration),
        # not the stale 20.0. Total duration = 8.0 + 12.0 = 20.0.
        assert abs(result.duration_seconds - 20.0) < 1e-6

    def test_chapters_not_retimed_when_repair_did_not_run(self, tmp_path: Path) -> None:
        """No repair needed → chapter start_times are used as-is."""
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        with (
            patch(
                "m4bmaker.chapters.subprocess.run", return_value=self._mock_ffprobe(5.0)
            ),
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_encode_popen),
        ):
            result = run_pipeline(book, out, ffmpeg="ffmpeg", ffprobe="ffprobe")
        assert abs(result.duration_seconds - 5.0) < 1e-6
