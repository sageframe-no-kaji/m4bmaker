"""Tests for m4bmaker.m4b_editor — chapter load and save."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.errors import M4BError
from m4bmaker.m4b_editor import load_m4b_chapters, save_m4b_chapters
from m4bmaker.models import BookMetadata, Chapter

# ── helpers ──────────────────────────────────────────────────────────────────


def _ffprobe_stdout(chapters: list[dict], duration: float = 120.0) -> str:
    return json.dumps(
        {
            "chapters": chapters,
            "format": {"duration": str(duration)},
        }
    )


def _ok_run(stdout: str):
    r = MagicMock()
    r.returncode = 0
    r.stdout = stdout
    return r


def _fail_run(stderr: str = "bad"):
    exc = MagicMock()
    exc.stderr = stderr
    from subprocess import CalledProcessError

    return CalledProcessError(1, [], stderr=stderr)


# ── load_m4b_chapters ────────────────────────────────────────────────────────


class TestLoadM4bChapters:
    def test_returns_chapters_and_duration(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        raw = [
            {"start_time": "0.0", "tags": {"title": "Intro"}},
            {"start_time": "60.0", "tags": {"title": "Ch 2"}},
        ]
        with patch("subprocess.run", return_value=_ok_run(_ffprobe_stdout(raw, 120.0))):
            chapters, duration = load_m4b_chapters(p, "ffprobe")

        assert len(chapters) == 2
        assert chapters[0].title == "Intro"
        assert chapters[1].start_time == pytest.approx(60.0)
        assert duration == pytest.approx(120.0)

    def test_chapter_indices_are_1_based(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        raw = [{"start_time": "0.0"}, {"start_time": "30.0"}]
        with patch("subprocess.run", return_value=_ok_run(_ffprobe_stdout(raw))):
            chapters, _ = load_m4b_chapters(p, "ffprobe")

        assert chapters[0].index == 1
        assert chapters[1].index == 2

    def test_fallback_title_when_tags_absent(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        raw = [{"start_time": "0.0"}]
        with patch("subprocess.run", return_value=_ok_run(_ffprobe_stdout(raw))):
            chapters, _ = load_m4b_chapters(p, "ffprobe")
        assert chapters[0].title == "Chapter 1"

    def test_empty_chapters_returns_empty_list(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        with patch(
            "subprocess.run",
            return_value=_ok_run(_ffprobe_stdout([], duration=90.0)),
        ):
            chapters, duration = load_m4b_chapters(p, "ffprobe")
        assert chapters == []
        assert duration == pytest.approx(90.0)

    def test_raises_m4berror_on_ffprobe_error(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        from subprocess import CalledProcessError

        with patch(
            "subprocess.run",
            side_effect=CalledProcessError(1, [], stderr="no such file"),
        ):
            with pytest.raises(M4BError):
                load_m4b_chapters(p, "ffprobe")

    def test_raises_m4berror_on_invalid_json(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        r = MagicMock()
        r.returncode = 0
        r.stdout = "not-json"
        with patch("subprocess.run", return_value=r):
            with pytest.raises(M4BError):
                load_m4b_chapters(p, "ffprobe")

    def test_source_file_set_to_path(self, tmp_path):
        p = tmp_path / "book.m4b"
        p.write_bytes(b"\x00")
        raw = [{"start_time": "0.0", "tags": {"title": "Ch 1"}}]
        with patch("subprocess.run", return_value=_ok_run(_ffprobe_stdout(raw))):
            chapters, _ = load_m4b_chapters(p, "ffprobe")
        assert chapters[0].source_file == p


# ── save_m4b_chapters ────────────────────────────────────────────────────────


class TestSaveM4bChapters:
    def _chapters(self, tmp_path: Path) -> list[Chapter]:
        f = tmp_path / "book.m4b"
        f.write_bytes(b"\x00" * 32)
        return [
            Chapter(index=1, start_time=0.0, title="Intro", source_file=f),
            Chapter(index=2, start_time=30.0, title="Part 2", source_file=f),
        ]

    def test_calls_ffmpeg(self, tmp_path):
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg")

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-map_chapters" in cmd
        # Source metadata should be preserved, not replaced.
        meta_idx = cmd.index("-map_metadata") + 1
        assert cmd[meta_idx] == "0"

    def test_output_file_created(self, tmp_path):
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"

        def fake_run(cmd, **_kw):
            # Simulate ffmpeg writing to the output arg (last positional arg in cmd)
            out = Path(cmd[-1])
            out.write_bytes(b"FAKE-M4B")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg")

        assert dest.exists()

    def test_raises_m4berror_on_ffmpeg_error(self, tmp_path):
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        from subprocess import CalledProcessError

        with patch(
            "subprocess.run",
            side_effect=CalledProcessError(1, [], stderr="encode error"),
        ):
            with pytest.raises(M4BError):
                save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg")

    def test_in_place_edit_replaces_source(self, tmp_path):
        """When source == dest, the in-place code path must not lose data."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00" * 32)

        def fake_run(cmd, **_kw):
            out = Path(cmd[-1])
            out.write_bytes(b"UPDATED-M4B")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, source, "ffmpeg")

        assert source.read_bytes() == b"UPDATED-M4B"

    def test_metadata_passed_as_explicit_cmd_flags(self, tmp_path):
        """Metadata must be passed as explicit -metadata flags in the ffmpeg command."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(
            title="My Book",
            author="Jane Doe",
            narrator="John Smith",
            genre="Fiction",
        )
        captured_cmd: list[list[str]] = []

        def fake_run(cmd, **_kw):
            captured_cmd.append(list(cmd))
            out = Path(cmd[-1])
            out.write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        assert captured_cmd, "ffmpeg was never called"
        cmd = captured_cmd[0]
        # Explicit -metadata flags must carry the updated values.
        paired = dict(zip(cmd, cmd[1:]))
        assert paired.get("-metadata") is not None, "-metadata flag not found in cmd"
        # Collect all -metadata values (there can be multiple).
        meta_values = [
            cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "-metadata"
        ]
        assert "title=My Book" in meta_values
        assert "artist=Jane Doe" in meta_values
        assert "composer=John Smith" in meta_values
        assert "genre=Fiction" in meta_values
        # source metadata must be preserved (-map_metadata 0)
        assert "-map_metadata" in cmd
        assert cmd[cmd.index("-map_metadata") + 1] == "0"

    def test_metadata_none_writes_empty_global_tags(self, tmp_path):
        """Passing metadata=None must not crash — writes no global tag lines."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        captured: list[str] = []

        def fake_run(cmd, **_kw):
            meta_idx = cmd.index("-i", cmd.index("-i") + 1) + 1
            meta_path = Path(cmd[meta_idx])
            if meta_path.exists():
                captured.append(meta_path.read_text(encoding="utf-8"))
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=None)

        assert captured
        content = captured[0]
        assert ";FFMETADATA1" in content
        # Global section is before the first [CHAPTER] marker.
        global_section = content.split("[CHAPTER]")[0]
        assert "artist=" not in global_section
        assert "composer=" not in global_section
        assert "genre=" not in global_section
        # title= is NOT expected in global section (no title supplied)
        assert "title=" not in global_section

    def test_partial_metadata_writes_only_present_fields(self, tmp_path):
        """Only non-empty metadata fields should appear in the global section."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="Only Title", author="", narrator="", genre="")
        captured: list[str] = []

        def fake_run(cmd, **_kw):
            meta_idx = cmd.index("-i", cmd.index("-i") + 1) + 1
            meta_path = Path(cmd[meta_idx])
            if meta_path.exists():
                captured.append(meta_path.read_text(encoding="utf-8"))
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        global_section = captured[0].split("[CHAPTER]")[0]
        assert "title=Only Title" in global_section
        assert "artist=" not in global_section
        assert "composer=" not in global_section

    def test_empty_field_passes_empty_metadata_flag_to_clear_it(self, tmp_path):
        """When metadata is supplied with a field the user cleared (empty
        string), the explicit -metadata flag must still be passed (with an
        empty value) so ffmpeg clears the tag — previously `if value:`
        silently kept the old tag."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="Kept Title", author="", narrator="", genre="")
        captured_cmd: list[list[str]] = []

        def fake_run(cmd, **_kw):
            captured_cmd.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        cmd = captured_cmd[0]
        meta_values = [
            cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "-metadata"
        ]
        assert "title=Kept Title" in meta_values
        # Cleared fields are passed as empty-valued flags, not omitted.
        assert "artist=" in meta_values
        assert "composer=" in meta_values
        assert "genre=" in meta_values

    def test_metadata_none_omits_all_metadata_flags(self, tmp_path):
        """metadata=None must not pass any -metadata flags for the four
        fields (behaviour unchanged from before item 22)."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        captured_cmd: list[list[str]] = []

        def fake_run(cmd, **_kw):
            captured_cmd.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=None)

        cmd = captured_cmd[0]
        meta_values = [
            cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "-metadata"
        ]
        # Only stik=2 remains — no title/artist/composer/genre flags.
        assert "stik=2" in meta_values
        assert not any(v.startswith("title=") for v in meta_values)
        assert not any(v.startswith("artist=") for v in meta_values)
        assert not any(v.startswith("composer=") for v in meta_values)
        assert not any(v.startswith("genre=") for v in meta_values)

    def test_in_place_save_streams_via_sibling_tmp_and_replace(self, tmp_path):
        """The in-place path must not read the whole file into memory via
        write_bytes(read_bytes()) — it copies to a sibling tmp file and
        os.replace()s onto dest."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "book.m4b"
        source.write_bytes(b"\x00" * 32)

        def fake_run(cmd, **_kw):
            Path(cmd[-1]).write_bytes(b"UPDATED-M4B")
            return MagicMock(returncode=0)

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch(
                "m4bmaker.m4b_editor.shutil.copyfile",
                side_effect=lambda s, d: Path(d).write_bytes(Path(s).read_bytes()),
            ) as mock_copyfile,
        ):
            save_m4b_chapters(source, chapters, 60.0, source, "ffmpeg")

        mock_copyfile.assert_called_once()
        assert source.read_bytes() == b"UPDATED-M4B"
        # No leftover .tmp_replace file after os.replace.
        leftovers = list(tmp_path.glob("*.tmp_replace"))
        assert leftovers == []

    def test_narrator_atom_written_after_success(self, tmp_path):
        """When metadata.narrator is non-empty, the ©nrt atom is written via
        mutagen after a successful ffmpeg run."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="T", author="A", narrator="Jane Narrator", genre="")

        def fake_run(cmd, **_kw):
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        mock_audio = MagicMock()
        mock_audio.tags = {}

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("mutagen.mp4.MP4", return_value=mock_audio) as mock_mp4,
        ):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        mock_mp4.assert_called_once_with(str(dest))
        assert mock_audio.tags["\xa9nrt"] == ["Jane Narrator"]
        mock_audio.save.assert_called_once()

    def test_narrator_atom_creates_tags_when_absent(self, tmp_path):
        """When the file has no tags container yet (audio.tags is None),
        add_tags() must be called before writing ©nrt."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="T", author="A", narrator="New Narrator", genre="")

        def fake_run(cmd, **_kw):
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        mock_audio = MagicMock()
        mock_audio.tags = None

        def _add_tags():
            mock_audio.tags = {}

        mock_audio.add_tags.side_effect = _add_tags

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("mutagen.mp4.MP4", return_value=mock_audio),
        ):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        mock_audio.add_tags.assert_called_once()
        assert mock_audio.tags["\xa9nrt"] == ["New Narrator"]

    def test_narrator_atom_skipped_when_narrator_empty(self, tmp_path):
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="T", author="A", narrator="", genre="")

        def fake_run(cmd, **_kw):
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("mutagen.mp4.MP4") as mock_mp4,
        ):
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        mock_mp4.assert_not_called()

    def test_narrator_atom_failure_does_not_fail_save(self, tmp_path):
        """A mutagen failure while writing ©nrt must not raise — the chapter
        save already succeeded and must not be rolled back."""
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        meta = BookMetadata(title="T", author="A", narrator="Narrator", genre="")

        def fake_run(cmd, **_kw):
            Path(cmd[-1]).write_bytes(b"FAKE")
            return MagicMock(returncode=0)

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("mutagen.mp4.MP4", side_effect=Exception("mutagen exploded")),
        ):
            # Must not raise despite the mutagen failure.
            save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg", metadata=meta)

        assert dest.exists()

    def test_ffmpeg_timeout_raises_m4berror(self, tmp_path):
        chapters = self._chapters(tmp_path)
        source = tmp_path / "in.m4b"
        source.write_bytes(b"\x00" * 32)
        dest = tmp_path / "out.m4b"
        from subprocess import TimeoutExpired

        with patch("subprocess.run", side_effect=TimeoutExpired("ffmpeg", 600)):
            with pytest.raises(M4BError, match="timed out"):
                save_m4b_chapters(source, chapters, 60.0, dest, "ffmpeg")
