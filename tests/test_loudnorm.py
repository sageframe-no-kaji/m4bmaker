"""Tests for EBU R128 loudness normalization (issue #14).

Covers the ``loudnorm`` measurement pass, the filter's presence and shape in
the encode command, and the pipeline's ordering of the two passes.  No test
here runs a real ffmpeg — the command is asserted as a built argument list.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.cli import build_parser, parse_args
from m4bmaker.encoder import _parse_loudnorm_json, encode, measure_loudness
from m4bmaker.errors import EncodeCancelled, M4BError
from m4bmaker.models import Book, BookMetadata, Chapter
from m4bmaker.pipeline import run_pipeline
from m4bmaker.preflight import AudioAnalysis

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

#: Verbatim shape of ffmpeg 8.1's stderr for a loudnorm print_format=json run.
#: Note the log lines *after* the JSON object — the block is not trailing, so
#: the parser must locate it rather than read the tail of the stream.
REAL_STDERR = """\
  Stream #0:0: Audio: mp3 (mp3float), 44100 Hz, mono, fltp, 64 kb/s
Stream mapping:
  Stream #0:0 -> #0:0 (mp3 (mp3float) -> pcm_s16le (native))
Press [q] to stop, [?] for help
Output #0, null, to 'pipe:':
  Metadata:
    encoder         : Lavf62.12.100
[Parsed_loudnorm_0 @ 0xbf0c48900]\x20
{
\t"input_i" : "-22.25",
\t"input_tp" : "-18.49",
\t"input_lra" : "0.00",
\t"input_thresh" : "-32.25",
\t"output_i" : "-17.95",
\t"output_tp" : "-14.24",
\t"output_lra" : "0.00",
\t"output_thresh" : "-27.95",
\t"normalization_type" : "linear",
\t"target_offset" : "-0.05"
}
[out#0/null @ 0xbf0c48180] video:0KiB audio:750KiB subtitle:0KiB other streams:0KiB
size=N/A time=00:00:02.00 bitrate=N/A speed= 135x elapsed=0:00:00.01
"""

MEASURED = {
    "input_i": "-22.25",
    "input_tp": "-18.49",
    "input_lra": "0.00",
    "input_thresh": "-32.25",
    "target_offset": "-0.05",
}


def _popen_mock(returncode: int = 0, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = iter([])
    proc.stderr = iter(stderr.splitlines(keepends=True))
    proc.wait.return_value = returncode
    return proc


def _make_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    concat = tmp_path / "concat.txt"
    meta = tmp_path / "meta.txt"
    output = tmp_path / "out.m4b"
    for p in (concat, meta):
        p.write_bytes(b"\x00")
    return concat, meta, output


def _run_encode(
    tmp_path: Path,
    normalize: bool = False,
    loudnorm_measured: dict[str, str] | None = None,
) -> list[str]:
    """Run encode() against a mocked Popen and return the captured command."""
    concat, meta, output = _make_paths(tmp_path)
    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
        captured.append(list(cmd))
        Path(cmd[-1]).write_bytes(b"FAKE-M4B")
        return _popen_mock()

    with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
        encode(
            concat,
            meta,
            None,
            output,
            "96k",
            1,
            "ffmpeg",
            normalize=normalize,
            loudnorm_measured=loudnorm_measured,
        )

    return captured[0]


def _af_value(cmd: list[str]) -> str:
    """Return the value of the ``-af`` argument in *cmd*."""
    return cmd[cmd.index("-af") + 1]


# ---------------------------------------------------------------------------
# measure_loudness
# ---------------------------------------------------------------------------


class TestMeasureLoudness:
    def test_parses_realistic_ffmpeg_stderr(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(stderr=REAL_STDERR),
        ):
            result = measure_loudness(concat, "ffmpeg")
        assert result["input_i"] == "-22.25"
        assert result["input_tp"] == "-18.49"
        assert result["input_lra"] == "0.00"
        assert result["input_thresh"] == "-32.25"
        assert result["target_offset"] == "-0.05"

    def test_json_block_is_not_the_tail_of_stderr(self, tmp_path: Path) -> None:
        # Regression guard: ffmpeg 8.x writes [out#0/null] and a size= summary
        # after the JSON, so a parser that reads the last lines finds nothing.
        assert not REAL_STDERR.strip().endswith("}")
        concat, _, _ = _make_paths(tmp_path)
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(stderr=REAL_STDERR),
        ):
            assert measure_loudness(concat, "ffmpeg")["input_i"] == "-22.25"

    def test_command_requests_json_and_null_output(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock(stderr=REAL_STDERR)

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            measure_loudness(concat, "ffmpeg")

        cmd = captured[0]
        assert "print_format=json" in _af_value(cmd)
        assert "loudnorm=" in _af_value(cmd)
        assert cmd[cmd.index("-f", cmd.index("-af")) + 1] == "null"

    def test_raises_when_json_block_absent(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        stderr = "ffmpeg version 8.1\nStream mapping:\nno json here at all\n"
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(stderr=stderr),
        ):
            with pytest.raises(M4BError, match="loudness measurements"):
                measure_loudness(concat, "ffmpeg")

    def test_raises_when_json_malformed(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        stderr = '[Parsed_loudnorm_0 @ 0x0]\n{\n"input_i" : "-22.25",,,\n}\n'
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(stderr=stderr),
        ):
            with pytest.raises(M4BError, match="loudness measurements"):
                measure_loudness(concat, "ffmpeg")

    def test_raises_when_fields_missing(self, tmp_path: Path) -> None:
        # Valid JSON, but not loudnorm's object — must not return partial data.
        concat, _, _ = _make_paths(tmp_path)
        stderr = "[something @ 0x0]\n" + json.dumps({"input_i": "-22.25"}) + "\n"
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(stderr=stderr),
        ):
            with pytest.raises(M4BError, match="loudness measurements"):
                measure_loudness(concat, "ffmpeg")

    def test_scans_past_unrelated_json_blocks(self) -> None:
        # Other filters can print JSON too; the block carrying loudnorm's
        # fields is the one that must be chosen, wherever it sits.
        stderr = (
            '[other @ 0x0]\n{"unrelated": 1}\n'
            + "[Parsed_loudnorm_0 @ 0x0]\n"
            + json.dumps(MEASURED)
            + '\n[out#0/null @ 0x0] done\n{"trailing": 2}\n'
        )
        assert _parse_loudnorm_json(stderr)["input_i"] == "-22.25"

    def test_interrupt_kills_ffmpeg_and_propagates(self, tmp_path: Path) -> None:
        # KeyboardInterrupt during the poll loop must not leave ffmpeg running.
        concat, _, _ = _make_paths(tmp_path)
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.poll.return_value = None
        with (
            patch("m4bmaker.encoder.subprocess.Popen", return_value=proc),
            patch("m4bmaker.encoder.time.sleep", side_effect=KeyboardInterrupt),
        ):
            with pytest.raises(KeyboardInterrupt):
                measure_loudness(concat, "ffmpeg")
        proc.kill.assert_called_once()
        proc.wait.assert_called_once()

    def test_raises_on_nonzero_returncode(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="boom"),
        ):
            with pytest.raises(M4BError, match="loudness measurement pass"):
                measure_loudness(concat, "ffmpeg")

    def test_raises_when_ffmpeg_missing(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        with patch(
            "m4bmaker.encoder.subprocess.Popen", side_effect=FileNotFoundError()
        ):
            with pytest.raises(M4BError, match="ffmpeg executable not found"):
                measure_loudness(concat, "nope")

    def test_cancellation_raises_encode_cancelled(self, tmp_path: Path) -> None:
        concat, _, _ = _make_paths(tmp_path)
        cancel = threading.Event()
        cancel.set()
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.poll.return_value = None  # still running, so cancel is observed
        with patch("m4bmaker.encoder.subprocess.Popen", return_value=proc):
            with pytest.raises(EncodeCancelled):
                measure_loudness(concat, "ffmpeg", cancel_event=cancel)
        proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# encode() command construction
# ---------------------------------------------------------------------------


class TestEncodeLoudnormCommand:
    def test_normalize_false_adds_no_filter(self, tmp_path: Path) -> None:
        cmd = _run_encode(tmp_path, normalize=False)
        assert "loudnorm" not in " ".join(cmd)
        assert "-af" not in cmd

    def test_default_is_normalize_off(self, tmp_path: Path) -> None:
        # Existing callers pass nothing and must get the old command.
        assert "-af" not in _run_encode(tmp_path)

    def test_normalize_false_command_matches_default(self, tmp_path: Path) -> None:
        assert _run_encode(tmp_path, normalize=False) == _run_encode(tmp_path)

    def test_normalize_true_applies_spoken_word_targets(self, tmp_path: Path) -> None:
        cmd = _run_encode(tmp_path, normalize=True)
        af = _af_value(cmd)
        assert af.startswith("loudnorm=")
        assert "I=-18" in af
        assert "TP=-2" in af
        assert "LRA=11" in af

    def test_normalize_true_is_not_broadcast_target(self, tmp_path: Path) -> None:
        af = _af_value(_run_encode(tmp_path, normalize=True))
        assert "I=-23" not in af
        assert "I=-16" not in af

    def test_one_pass_does_not_request_json(self, tmp_path: Path) -> None:
        # print_format=json belongs to the measurement pass only.
        assert "print_format" not in _af_value(_run_encode(tmp_path, normalize=True))

    def test_measured_values_applied_linearly(self, tmp_path: Path) -> None:
        cmd = _run_encode(tmp_path, normalize=True, loudnorm_measured=MEASURED)
        af = _af_value(cmd)
        assert "measured_I=-22.25" in af
        assert "measured_TP=-18.49" in af
        assert "measured_LRA=0.00" in af
        assert "measured_thresh=-32.25" in af
        assert "offset=-0.05" in af
        assert "linear=true" in af

    def test_measured_values_keep_the_targets(self, tmp_path: Path) -> None:
        af = _af_value(
            _run_encode(tmp_path, normalize=True, loudnorm_measured=MEASURED)
        )
        assert "I=-18" in af

    def test_measurements_ignored_when_normalize_off(self, tmp_path: Path) -> None:
        cmd = _run_encode(tmp_path, normalize=False, loudnorm_measured=MEASURED)
        assert "-af" not in cmd


# ---------------------------------------------------------------------------
# run_pipeline ordering
# ---------------------------------------------------------------------------


class TestPipelineNormalization:
    @pytest.fixture(autouse=True)
    def _no_repair(self):  # noqa: ANN202
        with patch("m4bmaker.repair.needs_repair", return_value=False):
            yield

    @pytest.fixture(autouse=True)
    def _uniform_codecs(self):  # noqa: ANN202
        with patch(
            "m4bmaker.pipeline.run_preflight", return_value=AudioAnalysis(file_count=1)
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

    def _run(
        self,
        tmp_path: Path,
        normalize: bool = False,
        normalize_two_pass: bool = False,
    ) -> tuple[list[str], MagicMock]:
        """Run run_pipeline with measure/encode mocked; return call order + encode."""
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        order: list[str] = []

        ffprobe = MagicMock()
        ffprobe.stdout = json.dumps({"format": {"duration": "10.0"}})

        measure = MagicMock(
            side_effect=lambda **_: (order.append("measure"), MEASURED)[1]
        )
        enc = MagicMock(side_effect=lambda **_: order.append("encode"))

        with (
            patch("m4bmaker.chapters.subprocess.run", return_value=ffprobe),
            patch("m4bmaker.pipeline.measure_loudness", measure),
            patch("m4bmaker.pipeline.encode", enc),
        ):
            run_pipeline(
                book,
                out,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                normalize=normalize,
                normalize_two_pass=normalize_two_pass,
            )

        return order, enc

    def test_two_pass_measures_before_encoding(self, tmp_path: Path) -> None:
        order, _ = self._run(tmp_path, normalize_two_pass=True)
        assert order == ["measure", "encode"]

    def test_two_pass_passes_measurements_to_encode(self, tmp_path: Path) -> None:
        _, enc = self._run(tmp_path, normalize_two_pass=True)
        assert enc.call_args.kwargs["loudnorm_measured"] == MEASURED
        assert enc.call_args.kwargs["normalize"] is True

    def test_two_pass_implies_normalize(self, tmp_path: Path) -> None:
        # --normalize-two-pass implies --normalize; measuring without applying
        # would be slow work with no effect on the output.
        _, enc = self._run(tmp_path, normalize_two_pass=True)
        assert enc.call_args.kwargs["normalize"] is True

    def test_one_pass_skips_the_measurement(self, tmp_path: Path) -> None:
        order, enc = self._run(tmp_path, normalize=True)
        assert order == ["encode"]
        assert enc.call_args.kwargs["normalize"] is True
        assert enc.call_args.kwargs["loudnorm_measured"] is None

    def test_default_neither_measures_nor_normalizes(self, tmp_path: Path) -> None:
        order, enc = self._run(tmp_path)
        assert order == ["encode"]
        assert enc.call_args.kwargs["normalize"] is False
        assert enc.call_args.kwargs["loudnorm_measured"] is None

    def _run_with_rates(
        self,
        tmp_path: Path,
        rates: dict[int, int],
        normalize: bool = False,
        sample_rate: int | None = None,
    ) -> MagicMock:
        """Run run_pipeline against a preflight reporting *rates*; return encode."""
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"

        ffprobe = MagicMock()
        ffprobe.stdout = json.dumps({"format": {"duration": "10.0"}})
        analysis = AudioAnalysis(file_count=1, sample_rates=Counter(rates))
        enc = MagicMock()

        with (
            patch("m4bmaker.chapters.subprocess.run", return_value=ffprobe),
            patch("m4bmaker.pipeline.run_preflight", return_value=analysis),
            patch("m4bmaker.pipeline.encode", enc),
        ):
            run_pipeline(
                book,
                out,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                normalize=normalize,
                sample_rate=sample_rate,
            )
        return enc

    def test_normalize_pins_output_to_source_sample_rate(self, tmp_path: Path) -> None:
        # loudnorm resamples to 192 kHz internally; left alone, AAC falls back
        # to 96 kHz and silently doubles the source rate.
        enc = self._run_with_rates(tmp_path, {44100: 1}, normalize=True)
        assert enc.call_args.kwargs["sample_rate"] == 44100

    def test_no_normalize_leaves_sample_rate_unset(self, tmp_path: Path) -> None:
        enc = self._run_with_rates(tmp_path, {44100: 1}, normalize=False)
        assert enc.call_args.kwargs["sample_rate"] is None

    def test_explicit_sample_rate_wins_over_source(self, tmp_path: Path) -> None:
        enc = self._run_with_rates(
            tmp_path, {44100: 1}, normalize=True, sample_rate=22050
        )
        assert enc.call_args.kwargs["sample_rate"] == 22050

    def test_mixed_rates_pin_to_the_dominant_one(self, tmp_path: Path) -> None:
        enc = self._run_with_rates(tmp_path, {44100: 3, 22050: 1}, normalize=True)
        assert enc.call_args.kwargs["sample_rate"] == 44100

    def test_unreadable_rate_leaves_sample_rate_unset(self, tmp_path: Path) -> None:
        # Preflight could not read a rate — fall through rather than guess.
        enc = self._run_with_rates(tmp_path, {}, normalize=True)
        assert enc.call_args.kwargs["sample_rate"] is None

    def test_measurement_pass_is_reported_to_the_callback(self, tmp_path: Path) -> None:
        book = self._make_book(tmp_path)
        out = tmp_path / "out.m4b"
        messages: list[str] = []

        ffprobe = MagicMock()
        ffprobe.stdout = json.dumps({"format": {"duration": "10.0"}})

        with (
            patch("m4bmaker.chapters.subprocess.run", return_value=ffprobe),
            patch("m4bmaker.pipeline.measure_loudness", return_value=MEASURED),
            patch("m4bmaker.pipeline.encode"),
        ):
            run_pipeline(
                book,
                out,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                normalize_two_pass=True,
                progress_callback=lambda msg, _frac: messages.append(msg),
            )

        assert any("Measuring loudness" in m for m in messages)


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------


class TestNormalizeFlags:
    def test_flags_appear_in_help(self) -> None:
        help_text = build_parser().format_help()
        assert "--normalize" in help_text
        assert "--normalize-two-pass" in help_text

    def test_normalize_defaults_off(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path)])
        assert args.normalize is False
        assert args.normalize_two_pass is False

    def test_normalize_flag_sets_true(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path), "--normalize"])
        assert args.normalize is True
        assert args.normalize_two_pass is False

    def test_two_pass_flag_sets_true(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path), "--normalize-two-pass"])
        assert args.normalize_two_pass is True

    def test_two_pass_dest_is_underscored(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path), "--normalize-two-pass"])
        assert hasattr(args, "normalize_two_pass")
