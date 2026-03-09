"""Tests for m4bmaker.preflight — audio preflight analysis."""

from __future__ import annotations

import json
from collections import Counter
from unittest.mock import MagicMock, patch

from m4bmaker.preflight import (
    AudioAnalysis,
    FileInfo,
    format_preflight_report,
    format_preflight_summary,
    probe_file,
    run_preflight,
)

# ── probe_file ──────────────────────────────────────────────────────────────


def _ffprobe_output(sample_rate=44100, channels=2, bit_rate=128000) -> str:
    return json.dumps(
        {
            "streams": [
                {
                    "sample_rate": str(sample_rate),
                    "channels": channels,
                    "bit_rate": str(bit_rate),
                }
            ]
        }
    )


def _run_result(stdout: str, returncode: int = 0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    return r


class TestProbeFile:
    def test_returns_file_info_with_all_fields(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_run_result(_ffprobe_output())) as m:
            info = probe_file(p, "ffprobe")
        m.assert_called_once()
        assert info.sample_rate == 44100
        assert info.channels == 2
        assert info.bit_rate == 128000
        assert info.path == p

    def test_returns_none_fields_on_nonzero_returncode(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_run_result("", returncode=1)):
            info = probe_file(p, "ffprobe")
        assert info.sample_rate is None
        assert info.channels is None
        assert info.bit_rate is None

    def test_returns_none_fields_on_empty_streams(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        out = json.dumps({"streams": []})
        with patch("subprocess.run", return_value=_run_result(out)):
            info = probe_file(p, "ffprobe")
        assert info.sample_rate is None

    def test_handles_missing_stream_keys(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        out = json.dumps({"streams": [{}]})
        with patch("subprocess.run", return_value=_run_result(out)):
            info = probe_file(p, "ffprobe")
        assert info.sample_rate is None
        assert info.channels is None
        assert info.bit_rate is None

    def test_handles_invalid_json(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_run_result("not-json")):
            info = probe_file(p, "ffprobe")
        assert info.sample_rate is None

    def test_ffprobe_command_includes_select_streams(self, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        with patch("subprocess.run", return_value=_run_result(_ffprobe_output())) as m:
            probe_file(p, "/custom/ffprobe")
        cmd = m.call_args[0][0]
        assert cmd[0] == "/custom/ffprobe"
        assert "-select_streams" in cmd
        assert "a:0" in cmd


# ── run_preflight ───────────────────────────────────────────────────────────


class TestRunPreflight:
    def test_aggregates_counters(self, tmp_path):
        files = [tmp_path / f"{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"\x00")

        infos = [
            FileInfo(path=files[0], sample_rate=44100, channels=1, bit_rate=64000),
            FileInfo(path=files[1], sample_rate=44100, channels=2, bit_rate=96000),
            FileInfo(path=files[2], sample_rate=48000, channels=2, bit_rate=128000),
        ]
        with patch("m4bmaker.preflight.probe_file", side_effect=infos):
            analysis = run_preflight(files, "ffprobe")

        assert analysis.file_count == 3
        assert analysis.sample_rates[44100] == 2
        assert analysis.sample_rates[48000] == 1
        assert analysis.channels[1] == 1
        assert analysis.channels[2] == 2
        assert 64000 in analysis.bit_rates

    def test_empty_file_list(self):
        analysis = run_preflight([], "ffprobe")
        assert analysis.file_count == 0
        assert len(analysis.sample_rates) == 0

    def test_skips_none_fields(self, tmp_path):
        f = tmp_path / "t.mp3"
        f.write_bytes(b"\x00")
        info = FileInfo(path=f, sample_rate=None, channels=None, bit_rate=None)
        with patch("m4bmaker.preflight.probe_file", return_value=info):
            analysis = run_preflight([f], "ffprobe")
        assert len(analysis.sample_rates) == 0
        assert len(analysis.channels) == 0
        assert len(analysis.bit_rates) == 0


# ── AudioAnalysis.has_mismatches ────────────────────────────────────────────


class TestHasMismatches:
    def test_no_mismatches_single_rate_and_channel(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({2: 2}),
        )
        assert a.has_mismatches is False

    def test_mismatch_on_mixed_sample_rates(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 1, 48000: 1}),
            channels=Counter({2: 2}),
        )
        assert a.has_mismatches is True

    def test_mismatch_on_mixed_channels(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({1: 1, 2: 1}),
        )
        assert a.has_mismatches is True

    def test_both_mismatches(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 1, 48000: 1}),
            channels=Counter({1: 1, 2: 1}),
        )
        assert a.has_mismatches is True

    def test_empty_counters_no_mismatch(self):
        a = AudioAnalysis(file_count=0)
        assert a.has_mismatches is False


# ── format_preflight_report ─────────────────────────────────────────────────


class TestFormatPreflightReport:
    def _uniform(self):
        return AudioAnalysis(
            file_count=4,
            sample_rates=Counter({44100: 4}),
            channels=Counter({2: 4}),
            bit_rates=Counter({96000: 4}),
        )

    def _mixed(self):
        return AudioAnalysis(
            file_count=3,
            sample_rates=Counter({44100: 2, 48000: 1}),
            channels=Counter({1: 1, 2: 2}),
        )

    def test_contains_file_count(self):
        report = format_preflight_report(self._uniform())
        assert "4 file(s)" in report

    def test_contains_sample_rate(self):
        report = format_preflight_report(self._uniform())
        assert "44100Hz" in report

    def test_contains_channels_label(self):
        report = format_preflight_report(self._uniform())
        assert "stereo" in report

    def test_no_warning_when_uniform(self):
        report = format_preflight_report(self._uniform())
        assert "⚠" not in report

    def test_warning_when_mismatched(self):
        report = format_preflight_report(self._mixed())
        assert "⚠" in report or "Mismatches" in report

    def test_returns_string(self):
        assert isinstance(format_preflight_report(self._uniform()), str)


# ── format_preflight_summary ────────────────────────────────────────────────


class TestFormatPreflightSummary:
    def test_single_rate_single_channel(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({2: 2}),
        )
        s = format_preflight_summary(a)
        assert "44100Hz" in s
        assert "stereo" in s

    def test_mono_label(self):
        a = AudioAnalysis(
            file_count=1,
            sample_rates=Counter({22050: 1}),
            channels=Counter({1: 1}),
        )
        assert "mono" in format_preflight_summary(a)

    def test_mixed_sample_rates_warning(self):
        a = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 1, 48000: 1}),
            channels=Counter({2: 2}),
        )
        s = format_preflight_summary(a)
        assert "⚠" in s or "mixed" in s

    def test_empty_analysis_returns_dash(self):
        a = AudioAnalysis(file_count=0)
        assert format_preflight_summary(a) == "—"

    def test_n_channel_label(self):
        a = AudioAnalysis(
            file_count=1,
            sample_rates=Counter({44100: 1}),
            channels=Counter({6: 1}),
        )
        s = format_preflight_summary(a)
        assert "6-ch" in s
