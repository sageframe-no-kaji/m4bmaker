"""Tests for m4bmaker.metadata — extraction and interactive prompts."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.metadata import extract_metadata, prompt_missing

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(**kwargs: object) -> Namespace:
    """Build a Namespace with sensible defaults for all CLI fields."""
    defaults: dict[str, object] = dict(
        title=None, author=None, narrator=None, genre=None, no_prompt=False
    )
    defaults.update(kwargs)
    return Namespace(**defaults)


def _mock_audio(tags: dict[str, list[str]] | None) -> MagicMock:
    """Return a mock mutagen.File return value."""
    audio = MagicMock()
    if tags is None:
        audio.tags = None
    else:
        # mutagen tags behave like a dict with list values
        audio.tags = tags
    return audio


# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------


class TestExtractMetadata:
    def test_reads_title_author_narrator(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        audio = _mock_audio(
            {
                "title": ["My Book"],
                "artist": ["Jane Smith"],
                "composer": ["Bob Reader"],
            }
        )

        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)

        assert meta["title"] == "My Book"
        assert meta["author"] == "Jane Smith"
        assert meta["narrator"] == "Bob Reader"

    def test_prefers_artist_over_albumartist(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio(
            {
                "artist": ["Primary Artist"],
                "albumartist": ["Album Artist"],
            }
        )
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["author"] == "Primary Artist"

    def test_falls_back_to_albumartist(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio({"albumartist": ["Fallback Author"]})
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["author"] == "Fallback Author"

    def test_mutagen_returns_none_file(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=None):
            meta = extract_metadata(stub)
        assert meta == {"title": "", "author": "", "narrator": "", "genre": ""}

    def test_mutagen_none_tags(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio(None)
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta == {"title": "", "author": "", "narrator": "", "genre": ""}

    def test_mutagen_exception_returns_empty(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        with patch("mutagen.File", side_effect=Exception("read error")):
            meta = extract_metadata(stub)
        assert meta == {"title": "", "author": "", "narrator": "", "genre": ""}

    def test_reads_genre_from_tags(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio(
            {
                "title": ["My Book"],
                "artist": ["Author"],
                "composer": ["Narrator"],
                "genre": ["Science Fiction"],
            }
        )
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["genre"] == "Science Fiction"

    def test_missing_fields_are_empty_strings(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio({"title": ["Only Title"]})
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["author"] == ""
        assert meta["narrator"] == ""

    def test_list_tag_value_takes_first_element(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        audio = _mock_audio({"title": ["First", "Second"]})
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["title"] == "First"

    def test_string_tag_value_accepted(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")
        # Some mutagen backends expose a plain string instead of a list.
        audio = _mock_audio({"title": "Plain String"})  # type: ignore[arg-type]
        with patch("mutagen.File", return_value=audio):
            meta = extract_metadata(stub)
        assert meta["title"] == "Plain String"


# ---------------------------------------------------------------------------
# prompt_missing — CLI override path
# ---------------------------------------------------------------------------


class TestPromptMissingCliOverrides:
    def test_cli_title_applied(self) -> None:
        meta = {"title": "", "author": "Author", "narrator": "Narrator", "genre": ""}
        result = prompt_missing(meta, _args(title="CLI Title", no_prompt=True))
        assert result["title"] == "CLI Title"

    def test_cli_author_applied(self) -> None:
        meta = {"title": "T", "author": "", "narrator": "N", "genre": ""}
        result = prompt_missing(meta, _args(author="CLI Author", no_prompt=True))
        assert result["author"] == "CLI Author"

    def test_cli_narrator_applied(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "", "genre": ""}
        result = prompt_missing(meta, _args(narrator="CLI Narrator", no_prompt=True))
        assert result["narrator"] == "CLI Narrator"

    def test_all_cli_flags_no_prompt_skips_input(self) -> None:
        meta = {"title": "", "author": "", "narrator": "", "genre": ""}
        args = _args(title="T", author="A", narrator="N", no_prompt=True)
        with patch("builtins.input") as mock_input:
            result = prompt_missing(meta, args)
        mock_input.assert_not_called()
        assert result == {"title": "T", "author": "A", "narrator": "N", "genre": ""}

    def test_existing_tags_confirmed_with_enter(self) -> None:
        """Pressing Enter on every prompt with tag prefills preserves tag values."""
        meta = {
            "title": "Tag Title",
            "author": "Tag Author",
            "narrator": "Tag Narrator",
            "genre": "",
        }
        with patch("builtins.input", return_value=""):
            result = prompt_missing(meta, _args())
        assert result["title"] == "Tag Title"
        assert result["author"] == "Tag Author"
        assert result["narrator"] == "Tag Narrator"


# ---------------------------------------------------------------------------
# prompt_missing — interactive prompt path
# ---------------------------------------------------------------------------


class TestPromptMissingInteractive:
    def test_prompts_for_missing_title(self) -> None:
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        # title: no prefill → user types "Prompted Title"
        # author, narrator: prefill from meta → user presses Enter → kept
        # genre: no prefill, optional → user presses Enter → ""
        with patch("builtins.input", side_effect=["Prompted Title", "", "", ""]):
            result = prompt_missing(meta, _args())
        assert result["title"] == "Prompted Title"
        assert result["author"] == "A"
        assert result["narrator"] == "N"

    def test_prompts_for_missing_author(self) -> None:
        meta = {"title": "T", "author": "", "narrator": "N", "genre": ""}
        with patch("builtins.input", side_effect=["", "Prompted Author", "", ""]):
            result = prompt_missing(meta, _args())
        assert result["author"] == "Prompted Author"

    def test_narrator_always_prompted_when_empty(self) -> None:
        """Narrator is always prompted if not set, even if other fields are present."""
        meta = {"title": "T", "author": "A", "narrator": "", "genre": ""}
        with patch("builtins.input", side_effect=["", "", "Prompted Narrator", ""]):
            result = prompt_missing(meta, _args())
        assert result["narrator"] == "Prompted Narrator"

    def test_empty_input_exits(self) -> None:
        """Empty input on a required field with no prefill triggers sys.exit."""
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        with patch("builtins.input", return_value=""):
            with pytest.raises(SystemExit):
                prompt_missing(meta, _args())


# ---------------------------------------------------------------------------
# prompt_missing — --no-prompt path
# ---------------------------------------------------------------------------


class TestPromptMissingNoPrompt:
    def test_no_prompt_missing_title_exits(self) -> None:
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        with pytest.raises(SystemExit, match="--title"):
            prompt_missing(meta, _args(no_prompt=True))

    def test_no_prompt_missing_author_exits(self) -> None:
        meta = {"title": "T", "author": "", "narrator": "N", "genre": ""}
        with pytest.raises(SystemExit, match="--author"):
            prompt_missing(meta, _args(no_prompt=True))

    def test_no_prompt_missing_narrator_exits(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "", "genre": ""}
        with pytest.raises(SystemExit, match="--narrator"):
            prompt_missing(meta, _args(no_prompt=True))

    def test_no_prompt_all_supplied_via_cli_succeeds(self) -> None:
        meta = {"title": "", "author": "", "narrator": "", "genre": ""}
        args = _args(title="T", author="A", narrator="N", no_prompt=True)
        result = prompt_missing(meta, args)
        assert result == {"title": "T", "author": "A", "narrator": "N", "genre": ""}


# ---------------------------------------------------------------------------
# prompt_missing — hints
# ---------------------------------------------------------------------------


class TestPromptMissingHints:
    def test_no_prompt_uses_hint_silently(self) -> None:
        """--no-prompt with a hint uses the hint without exiting."""
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        result = prompt_missing(
            meta, _args(no_prompt=True), hints={"title": "Hinted Title"}
        )
        assert result["title"] == "Hinted Title"

    def test_empty_input_accepts_hint(self) -> None:
        """Pressing Enter with a hint available accepts the hint."""
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        with patch("builtins.input", return_value=""):
            result = prompt_missing(meta, _args(), hints={"title": "Hinted Title"})
        assert result["title"] == "Hinted Title"

    def test_hint_shown_in_prompt_text(self) -> None:
        """Prompt string should contain the hint in brackets."""
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        prompts: list[str] = []

        def _capture(p: str) -> str:
            prompts.append(p)
            return "custom value"

        with patch("builtins.input", side_effect=_capture):
            prompt_missing(meta, _args(), hints={"title": "My Book"})

        assert any("[My Book]" in p for p in prompts)

    def test_explicit_value_overrides_hint(self) -> None:
        """Typing a value takes priority over the hint."""
        meta = {"title": "", "author": "A", "narrator": "N", "genre": ""}
        with patch("builtins.input", side_effect=["Typed Title", "", "", ""]):
            result = prompt_missing(meta, _args(), hints={"title": "Ignored Hint"})
        assert result["title"] == "Typed Title"


# ---------------------------------------------------------------------------
# prompt_missing — genre field
# ---------------------------------------------------------------------------


class TestPromptMissingGenre:
    def test_genre_optional_no_prompt_empty(self) -> None:
        """Genre is optional: missing genre with --no-prompt does not exit."""
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": ""}
        result = prompt_missing(meta, _args(no_prompt=True))
        assert result["genre"] == ""

    def test_cli_genre_applied(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": ""}
        result = prompt_missing(meta, _args(genre="Fantasy", no_prompt=True))
        assert result["genre"] == "Fantasy"

    def test_cli_genre_overrides_tag_genre(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": "Fiction"}
        result = prompt_missing(meta, _args(genre="Science Fiction", no_prompt=True))
        assert result["genre"] == "Science Fiction"

    def test_tag_genre_used_when_no_cli(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": "Mystery"}
        result = prompt_missing(meta, _args(no_prompt=True))
        assert result["genre"] == "Mystery"

    def test_genre_prompted_interactively(self) -> None:
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": ""}
        with patch("builtins.input", side_effect=["", "", "", "Thriller"]):
            result = prompt_missing(meta, _args())
        assert result["genre"] == "Thriller"

    def test_genre_empty_input_accepted(self) -> None:
        """Pressing Enter on genre (no prefill) is allowed since it is optional."""
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": ""}
        with patch("builtins.input", return_value=""):
            result = prompt_missing(meta, _args())
        assert result["genre"] == ""
