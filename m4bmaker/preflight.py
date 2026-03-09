"""Audio preflight analysis — probe files for format inconsistencies.

Runs ``ffprobe -show_streams`` on every source file and reports sample
rate, channel count, and bit-rate mismatches so the user knows what
normalisation will occur during encoding.  Audio is *never* modified.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ── data models ──────────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    """Per-file audio stream properties extracted via ffprobe."""

    path: Path
    sample_rate: int | None  # Hz; None if unavailable
    channels: int | None  # 1 = mono, 2 = stereo, …
    bit_rate: int | None  # bits/sec; None if unavailable
    codec_name: str | None = None  # e.g. "mp3", "aac", "flac"
    duration_seconds: float | None = None


@dataclass
class AudioAnalysis:
    """Aggregated preflight results across all source files."""

    file_count: int
    sample_rates: Counter = field(default_factory=Counter)  # {rate_hz: count}
    channels: Counter = field(default_factory=Counter)  # {n_channels: count}
    bit_rates: Counter = field(default_factory=Counter)  # {bps: count}
    codecs: Counter = field(default_factory=Counter)  # {codec_name: count}
    total_duration_seconds: float = 0.0

    @property
    def has_mismatches(self) -> bool:
        """True if files differ in sample rate or channel count."""
        return len(self.sample_rates) > 1 or len(self.channels) > 1


# ── probing ──────────────────────────────────────────────────────────────────


def probe_file(path: Path, ffprobe: str) -> FileInfo:
    """Probe a single file's first audio stream with ffprobe.

    Returns a :class:`FileInfo` with ``None`` fields for any property that
    could not be read (e.g. the tool fails or the stream tag is absent).
    """
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "-select_streams",
        "a:0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    sample_rate: int | None = None
    channels: int | None = None
    bit_rate: int | None = None
    codec_name: str | None = None
    duration_seconds: float | None = None

    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                s = streams[0]
                if "sample_rate" in s:
                    sample_rate = int(s["sample_rate"])
                if "channels" in s:
                    channels = int(s["channels"])
                if "bit_rate" in s:
                    bit_rate = int(s["bit_rate"])
                if "codec_name" in s:
                    codec_name = s["codec_name"]
                if "duration" in s:
                    duration_seconds = float(s["duration"])
            # Fall back to format-level duration (more reliable for MP3 etc.)
            if duration_seconds is None:
                fmt = data.get("format", {})
                if "duration" in fmt:
                    duration_seconds = float(fmt["duration"])
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    return FileInfo(
        path=path,
        sample_rate=sample_rate,
        channels=channels,
        bit_rate=bit_rate,
        codec_name=codec_name,
        duration_seconds=duration_seconds,
    )


def run_preflight(files: list[Path], ffprobe: str) -> AudioAnalysis:
    """Probe all *files* and return a consolidated :class:`AudioAnalysis`."""
    sample_rates: Counter = Counter()
    channels: Counter = Counter()
    bit_rates: Counter = Counter()
    codecs: Counter = Counter()
    total_duration: float = 0.0

    for path in files:
        info = probe_file(path, ffprobe)
        if info.sample_rate is not None:
            sample_rates[info.sample_rate] += 1
        if info.channels is not None:
            channels[info.channels] += 1
        if info.bit_rate is not None:
            bit_rates[info.bit_rate] += 1
        if info.codec_name is not None:
            codecs[info.codec_name] += 1
        if info.duration_seconds is not None:
            total_duration += info.duration_seconds

    return AudioAnalysis(
        file_count=len(files),
        sample_rates=sample_rates,
        channels=channels,
        bit_rates=bit_rates,
        codecs=codecs,
        total_duration_seconds=total_duration,
    )


# ── reporting ─────────────────────────────────────────────────────────────────


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS or M:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def format_preflight_report(analysis: AudioAnalysis) -> str:
    """Return a human-readable multi-line preflight summary."""

    def _fmt_sr(counter: Counter) -> str:
        return ", ".join(f"{r}Hz ({v})" for r, v in sorted(counter.items()))

    def _fmt_ch(counter: Counter) -> str:
        labels = {1: "mono", 2: "stereo"}
        return ", ".join(
            f"{labels.get(k, f'{k}-ch')} ({v})" for k, v in sorted(counter.items())
        )

    lines = [
        "Audio analysis:",
        f"  {analysis.file_count} file(s) detected",
    ]
    if analysis.total_duration_seconds > 0:
        lines.append(f"  Total duration: {_fmt_duration(analysis.total_duration_seconds)}")
    if analysis.sample_rates:
        lines.append(f"  Sample rates: {_fmt_sr(analysis.sample_rates)}")
    if analysis.channels:
        lines.append(f"  Channels: {_fmt_ch(analysis.channels)}")

    if analysis.has_mismatches:
        lines.append("")
        lines.append(
            "  \u26a0 Mismatches detected — audio will be normalised during encoding."
        )
        if analysis.channels and len(analysis.channels) > 1:
            lines.append("  Use --stereo to force stereo output.")
        if analysis.sample_rates and len(analysis.sample_rates) > 1:
            top_sr = max(analysis.sample_rates, key=lambda r: analysis.sample_rates[r])
            lines.append(f"  Most common sample rate: {top_sr}Hz.")

    return "\n".join(lines)


def format_preflight_summary(analysis: AudioAnalysis) -> str:
    """Return a compact single-line summary suitable for a GUI label."""
    parts: list[str] = []

    # File count + total duration (always shown if available)
    if analysis.total_duration_seconds > 0:
        parts.append(
            f"{analysis.file_count} file(s)  ·  {_fmt_duration(analysis.total_duration_seconds)}"
        )
    else:
        parts.append(f"{analysis.file_count} file(s)")

    if analysis.codecs:
        if len(analysis.codecs) == 1:
            parts.append(next(iter(analysis.codecs)).upper())
        else:
            parts.append("\u26a0 mixed codecs")

    if analysis.sample_rates:
        if len(analysis.sample_rates) == 1:
            sr = next(iter(analysis.sample_rates))
            parts.append(f"{sr}Hz")
        else:
            rates = ", ".join(f"{r}Hz" for r in sorted(analysis.sample_rates))
            parts.append(f"\u26a0 mixed sample rates ({rates})")

    if analysis.channels:
        if len(analysis.channels) == 1:
            n = next(iter(analysis.channels))
            parts.append("mono" if n == 1 else "stereo" if n == 2 else f"{n}-ch")
        else:
            parts.append("\u26a0 mixed channels")

    if analysis.bit_rates:
        if len(analysis.bit_rates) == 1:
            bps = next(iter(analysis.bit_rates))
            parts.append(f"{bps // 1000}kbps")
        else:
            lo = min(analysis.bit_rates) // 1000
            hi = max(analysis.bit_rates) // 1000
            parts.append(f"\u26a0 {lo}\u2013{hi}kbps")

    return "  ·  ".join(parts)
