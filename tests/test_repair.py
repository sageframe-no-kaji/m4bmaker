"""Tests for m4bmaker.repair — input repair/normalisation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from m4bmaker.repair import (
    RepairResult,
    apply_repair,
    format_repair_report,
    needs_repair,
    repair_file,
    run_repair,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _probe_result(streams: list[dict], stderr: str = "", returncode: int = 0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps({"streams": streams})
    r.stderr = stderr
    return r


def _ok_probe():
    """Audio-only, no corruption markers."""
    return _probe_result([{"codec_type": "audio"}])


def _video_probe():
    """File with embedded cover art (video stream)."""
    return _probe_result([{"codec_type": "audio"}, {"codec_type": "video"}])


def _corrupt_probe():
    """ffprobe reports a corruption error in stderr."""
    return _probe_result([{"codec_type": "audio"}], stderr="Header missing")


def _run_ok():
    r = MagicMock()
    r.returncode = 0
    r.stdout = ""
    r.stderr = ""
    return r


# ── RepairResult ─────────────────────────────────────────────────────────────


class TestRepairResult:
    def test_needed_repair_false_when_zero_repaired(self):
        r = RepairResult(total=5, repaired=0)
        assert r.needed_repair is False

    def test_needed_repair_true_when_nonzero_repaired(self):
        r = RepairResult(total=3, repaired=2)
        assert r.needed_repair is True

    def test_default_lists_are_empty(self):
        r = RepairResult(total=1, repaired=0)
        assert r.repaired_paths == []
        assert r.error_paths == []


# ── needs_repair ─────────────────────────────────────────────────────────────


class TestNeedsRepair:
    def test_no_repair_needed_for_clean_audio_file(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_ok_probe()):
            assert needs_repair(p, "ffprobe") is False

    def test_repair_needed_when_video_stream_present(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_video_probe()):
            assert needs_repair(p, "ffprobe") is True

    def test_repair_needed_when_corruption_in_stderr(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_corrupt_probe()):
            assert needs_repair(p, "ffprobe") is True

    def test_repair_needed_for_each_known_marker(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        markers = [
            "Header missing",
            "Invalid data",
            "corrupt",
            "moov atom",
            "error",
            "could not find codec",
        ]
        for marker in markers:
            with patch("subprocess.run", return_value=_probe_result(
                [{"codec_type": "audio"}], stderr=marker
            )):
                assert needs_repair(p, "ffprobe") is True, f"should detect: {marker}"

    def test_no_repair_for_data_stream(self, tmp_path):
        """Data and subtitle streams should not trigger repair."""
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        for codec_type in ("data", "subtitle"):
            with patch("subprocess.run", return_value=_probe_result(
                [{"codec_type": "audio"}, {"codec_type": codec_type}]
            )):
                assert needs_repair(p, "ffprobe") is False, f"should not repair: {codec_type}"

    def test_handles_malformed_json_gracefully(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        r = MagicMock()
        r.stdout = "not json"
        r.stderr = ""
        with patch("subprocess.run", return_value=r):
            # malformed JSON → no video-stream trigger; no stderr; should be False
            assert needs_repair(p, "ffprobe") is False

    def test_repair_needed_for_empty_streams_with_stderr_error(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_probe_result([], stderr="corrupt frame")):
            assert needs_repair(p, "ffprobe") is True


# ── repair_file ───────────────────────────────────────────────────────────────


class TestRepairFile:
    def test_returns_cleaned_path_in_dest_dir(self, tmp_path):
        src = tmp_path / "input.mp3"
        src.write_bytes(b"\x00")
        dest_dir = tmp_path / "out"
        dest_dir.mkdir()
        with patch("subprocess.run", return_value=_run_ok()) as mock_run:
            result = repair_file(src, dest_dir, "ffmpeg")
        assert result == dest_dir / "input.mp3"
        mock_run.assert_called_once()

    def test_ffmpeg_command_includes_required_flags(self, tmp_path):
        src = tmp_path / "input.mp3"
        src.write_bytes(b"\x00")
        dest_dir = tmp_path / "out"
        dest_dir.mkdir()
        with patch("subprocess.run", return_value=_run_ok()) as mock_run:
            repair_file(src, dest_dir, "ffmpeg")
        cmd = mock_run.call_args[0][0]
        assert "-fflags" in cmd
        assert "+discardcorrupt" in cmd
        assert "-err_detect" in cmd
        assert "ignore_err" in cmd
        assert "-map" in cmd
        assert "0:a" in cmd
        assert "-c:a" in cmd
        assert "copy" in cmd

    def test_unique_name_if_target_already_exists(self, tmp_path):
        src = tmp_path / "input.mp3"
        src.write_bytes(b"\x00")
        dest_dir = tmp_path / "out"
        dest_dir.mkdir()
        # Pre-create a file with the same name
        (dest_dir / "input.mp3").write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_run_ok()):
            result = repair_file(src, dest_dir, "ffmpeg")
        assert result.name == "input_repaired.mp3"

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        src = tmp_path / "input.mp3"
        src.write_bytes(b"\x00")
        dest_dir = tmp_path / "out"
        dest_dir.mkdir()
        err = subprocess.CalledProcessError(1, "ffmpeg", stderr="Fatal error")
        with patch("subprocess.run", side_effect=err):
            try:
                repair_file(src, dest_dir, "ffmpeg")
                assert False, "should have raised"
            except subprocess.CalledProcessError:
                pass


# ── run_repair ────────────────────────────────────────────────────────────────


class TestRunRepair:
    def test_returns_zero_repaired_when_no_files_need_it(self, tmp_path):
        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.write_bytes(b"\x00")
        with patch("m4bmaker.repair.needs_repair", return_value=False):
            result = run_repair(files, tmp_path, "ffmpeg", "ffprobe")
        assert result.repaired == 0
        assert result.total == 2
        assert result.needed_repair is False

    def test_repairs_files_that_need_it(self, tmp_path):
        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp3"
        a.write_bytes(b"\x00")
        b.write_bytes(b"\x00")
        cleaned_a = tmp_path / "repaired" / "a.mp3"

        def fake_needs_repair(path, ffprobe):
            return path == a

        with (
            patch("m4bmaker.repair.needs_repair", side_effect=fake_needs_repair),
            patch("m4bmaker.repair.repair_file", return_value=cleaned_a) as mock_repair,
        ):
            result = run_repair([a, b], tmp_path, "ffmpeg", "ffprobe")

        assert result.repaired == 1
        assert result.total == 2
        mock_repair.assert_called_once_with(a, tmp_path / "repaired", "ffmpeg")
        assert (a, cleaned_a) in result.repaired_paths

    def test_progress_callback_called_with_message(self, tmp_path):
        a = tmp_path / "a.mp3"
        a.write_bytes(b"\x00")
        messages: list[str] = []

        with (
            patch("m4bmaker.repair.needs_repair", return_value=True),
            patch("m4bmaker.repair.repair_file", return_value=tmp_path / "repaired" / "a.mp3"),
        ):
            run_repair([a], tmp_path, "ffmpeg", "ffprobe", progress_callback=messages.append)

        assert any("Repairing" in m for m in messages)

    def test_progress_callback_none_is_safe(self, tmp_path):
        a = tmp_path / "a.mp3"
        a.write_bytes(b"\x00")
        with (
            patch("m4bmaker.repair.needs_repair", return_value=False),
        ):
            result = run_repair([a], tmp_path, "ffmpeg", "ffprobe", progress_callback=None)
        assert result.total == 1

    def test_error_paths_populated_on_ffmpeg_failure(self, tmp_path):
        a = tmp_path / "a.mp3"
        a.write_bytes(b"\x00")
        err = subprocess.CalledProcessError(1, "ffmpeg", stderr="boom")
        with (
            patch("m4bmaker.repair.needs_repair", return_value=True),
            patch("m4bmaker.repair.repair_file", side_effect=err),
        ):
            result = run_repair([a], tmp_path, "ffmpeg", "ffprobe")

        assert len(result.error_paths) == 1
        assert result.error_paths[0][0] == a
        assert "boom" in result.error_paths[0][1]

    def test_creates_repair_subdir_in_tmp(self, tmp_path):
        a = tmp_path / "a.mp3"
        a.write_bytes(b"\x00")
        captured: list[Path] = []

        def fake_repair(source, dest_dir, ffmpeg):
            captured.append(dest_dir)
            return dest_dir / source.name

        with (
            patch("m4bmaker.repair.needs_repair", return_value=True),
            patch("m4bmaker.repair.repair_file", side_effect=fake_repair),
        ):
            run_repair([a], tmp_path, "ffmpeg", "ffprobe")

        assert captured[0] == tmp_path / "repaired"
        assert captured[0].is_dir()

    def test_empty_file_list(self, tmp_path):
        result = run_repair([], tmp_path, "ffmpeg", "ffprobe")
        assert result.total == 0
        assert result.repaired == 0


# ── apply_repair ──────────────────────────────────────────────────────────────


class TestApplyRepair:
    def test_substitutes_repaired_paths(self, tmp_path):
        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp3"
        a_clean = tmp_path / "repaired" / "a.mp3"
        result = RepairResult(
            total=2,
            repaired=1,
            repaired_paths=[(a, a_clean)],
        )
        out = apply_repair([a, b], result)
        assert out == [a_clean, b]

    def test_returns_original_list_when_no_repairs(self, tmp_path):
        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp3"
        result = RepairResult(total=2, repaired=0)
        out = apply_repair([a, b], result)
        assert out == [a, b]

    def test_preserves_order(self, tmp_path):
        files = [tmp_path / f"{i}.mp3" for i in range(5)]
        c2 = tmp_path / "repaired" / "2.mp3"
        c4 = tmp_path / "repaired" / "4.mp3"
        result = RepairResult(
            total=5,
            repaired=2,
            repaired_paths=[(files[2], c2), (files[4], c4)],
        )
        out = apply_repair(files, result)
        assert out[0] == files[0]
        assert out[1] == files[1]
        assert out[2] == c2
        assert out[3] == files[3]
        assert out[4] == c4

    def test_does_not_mutate_original_list(self, tmp_path):
        a = tmp_path / "a.mp3"
        a_clean = tmp_path / "repaired" / "a.mp3"
        original = [a]
        result = RepairResult(total=1, repaired=1, repaired_paths=[(a, a_clean)])
        apply_repair(original, result)
        assert original == [a]

    def test_handles_empty_file_list(self):
        result = RepairResult(total=0, repaired=0)
        assert apply_repair([], result) == []


# ── format_repair_report ──────────────────────────────────────────────────────


class TestFormatRepairReport:
    def test_returns_empty_string_when_no_repair_needed(self):
        result = RepairResult(total=3, repaired=0)
        assert format_repair_report(result) == ""

    def test_includes_count_and_summary(self):
        result = RepairResult(total=5, repaired=2)
        report = format_repair_report(result)
        assert "2 file(s)" in report
        assert "Repairing" in report
        assert "Cleaned copies" in report

    def test_includes_error_note_when_errors_present(self):
        a = Path("a.mp3")
        result = RepairResult(
            total=3,
            repaired=2,
            error_paths=[(a, "something went wrong")],
        )
        report = format_repair_report(result)
        assert "could not be repaired" in report

    def test_no_error_note_when_no_errors(self):
        result = RepairResult(total=2, repaired=2)
        report = format_repair_report(result)
        assert "could not be repaired" not in report
