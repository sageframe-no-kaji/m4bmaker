"""Tests for m4bmaker.audnexus — API client and offset reconciliation (#4).

Every HTTP call is mocked; the suite makes no live network request. The
fixtures below are trimmed from real api.audnex.us responses captured while
building this, so field names and shapes match the service rather than a
guess at it.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.audnexus import (
    DEFAULT_TOLERANCE,
    AudnexusChapter,
    apply_names,
    apply_timings,
    fetch_chapters,
    fetch_metadata,
    reconcile_offsets,
    validate_asin,
)
from m4bmaker.errors import M4BError
from m4bmaker.models import Chapter

ASIN = "B017V4IM1G"

#: Trimmed from the live /books/{asin} response. Note authors and narrators
#: are lists of objects and the cover is `image`, not `cover`.
BOOK_JSON: dict = {
    "asin": ASIN,
    "title": "Harry Potter and the Sorcerer's Stone, Book 1",
    "authors": [{"asin": "B000AP9A6K", "name": "J.K. Rowling"}],
    "narrators": [{"name": "Jim Dale"}],
    "genres": [
        {"asin": "18572091011", "name": "Children's Audiobooks", "type": "genre"},
        {"asin": "18572586011", "name": "Some Tag", "type": "tag"},
    ],
    "image": "https://m.media-amazon.com/images/I/91eopoUCjLL.jpg",
    "runtimeLengthMin": 498,
}

#: Trimmed from the live /books/{asin}/chapters response. brandIntroDurationMs
#: is Audible's own branded intro — the usual cause of offset drift.
CHAPTERS_JSON: dict = {
    "asin": ASIN,
    "brandIntroDurationMs": 3970,
    "brandOutroDurationMs": 4945,
    "isAccurate": True,
    "region": "us",
    "runtimeLengthMs": 29908847,
    "chapters": [
        {"lengthMs": 30970, "startOffsetMs": 0, "title": "Opening Credits"},
        {
            "lengthMs": 1732654,
            "startOffsetMs": 30970,
            "title": "Chapter 1: The Boy Who Lived",
        },
        {
            "lengthMs": 1306377,
            "startOffsetMs": 1763624,
            "title": "Chapter 2: The Vanishing Glass",
        },
    ],
}


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: False
    return resp


def _http_error(code: int, payload: dict | None = None) -> urllib.error.HTTPError:
    body = json.dumps(payload).encode("utf-8") if payload else b""
    return urllib.error.HTTPError(
        url="https://api.audnex.us/x",
        code=code,
        msg="err",
        hdrs=None,  # type: ignore[arg-type]  # HTTPError accepts None at runtime
        fp=BytesIO(body),
    )


def _local(times: list[float]) -> list[Chapter]:
    return [
        Chapter(index=i + 1, start_time=t, title=f"Local {i + 1}", source_file=None)
        for i, t in enumerate(times)
    ]


def _remote(pairs: list[tuple[str, int]]) -> list[AudnexusChapter]:
    return [AudnexusChapter(title=t, start_ms=ms) for t, ms in pairs]


# ---------------------------------------------------------------------------
# ASIN validation — no request may be attempted for a malformed ASIN
# ---------------------------------------------------------------------------


class TestValidateAsin:
    def test_accepts_a_real_asin(self) -> None:
        assert validate_asin(ASIN) == ASIN

    def test_upper_cases_and_strips(self) -> None:
        assert validate_asin("  b017v4im1g  ") == ASIN

    @pytest.mark.parametrize(
        "bad", ["", "SHORT", "TOOLONGASIN12", "B017-4IM1G", "b017 4im1g"]
    )
    def test_rejects_malformed(self, bad: str) -> None:
        with pytest.raises(M4BError, match="not a valid Audible ASIN"):
            validate_asin(bad)

    def test_malformed_asin_makes_no_request(self) -> None:
        with patch("m4bmaker.audnexus.urllib.request.urlopen") as opener:
            with pytest.raises(M4BError, match="not a valid Audible ASIN"):
                fetch_metadata("NOT-AN-ASIN")
        opener.assert_not_called()

    def test_malformed_asin_makes_no_request_for_chapters(self) -> None:
        with patch("m4bmaker.audnexus.urllib.request.urlopen") as opener:
            with pytest.raises(M4BError):
                fetch_chapters("nope")
        opener.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_metadata
# ---------------------------------------------------------------------------


class TestFetchMetadata:
    def test_parses_the_live_shape(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(BOOK_JSON),
        ):
            book = fetch_metadata(ASIN)
        assert book.title == "Harry Potter and the Sorcerer's Stone, Book 1"
        assert book.author == "J.K. Rowling"
        assert book.narrator == "Jim Dale"
        assert book.cover_url == BOOK_JSON["image"]

    def test_takes_the_genre_not_the_tag(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(BOOK_JSON),
        ):
            book = fetch_metadata(ASIN)
        assert book.genre == "Children's Audiobooks"

    def test_absent_fields_are_none(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response({"asin": ASIN}),
        ):
            book = fetch_metadata(ASIN)
        assert (book.title, book.author, book.narrator, book.genre) == (
            None,
            None,
            None,
            None,
        )

    def test_non_https_cover_is_dropped(self) -> None:
        payload = {**BOOK_JSON, "image": "not-a-url"}
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(payload),
        ):
            assert fetch_metadata(ASIN).cover_url is None

    def test_region_reaches_the_url(self) -> None:
        seen: list[str] = []

        def _capture(req, **_):  # type: ignore[no-untyped-def]
            seen.append(req.full_url)
            return _response(BOOK_JSON)

        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=_capture):
            fetch_metadata(ASIN, region="uk")
        assert "region=uk" in seen[0]

    def test_sends_a_m4bmaker_user_agent(self) -> None:
        seen: list[object] = []

        def _capture(req, **_):  # type: ignore[no-untyped-def]
            seen.append(req.get_header("User-agent"))
            return _response(BOOK_JSON)

        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=_capture):
            fetch_metadata(ASIN)
        assert str(seen[0]).startswith("m4bmaker/")

    def test_only_the_asin_appears_in_the_request(self) -> None:
        # Nothing about the user's library may leave the machine.
        seen: list[object] = []

        def _capture(req, **_):  # type: ignore[no-untyped-def]
            seen.append((req.full_url, req.data, dict(req.headers)))
            return _response(BOOK_JSON)

        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=_capture):
            fetch_metadata(ASIN)
        url, data, headers = seen[0]  # type: ignore[misc]
        assert data is None  # a GET with no body
        assert url == f"https://api.audnex.us/books/{ASIN}?region=us"
        assert set(headers) == {"User-agent"}


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_404_names_the_region(self) -> None:
        body = {
            "error": {
                "code": "REGION_UNAVAILABLE",
                "message": "Item not available in region 'us' for ASIN: X",
            }
        }
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            side_effect=_http_error(404, body),
        ):
            with pytest.raises(M4BError) as excinfo:
                fetch_metadata(ASIN, region="us")
        message = str(excinfo.value)
        assert "region" in message.lower()
        assert "us" in message
        # A 404 must never read as a generic failure.
        assert "wrong region" in message.lower() or "storefront" in message.lower()

    def test_404_surfaces_the_api_message(self) -> None:
        body = {"error": {"code": "REGION_UNAVAILABLE", "message": "Item not here"}}
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            side_effect=_http_error(404, body),
        ):
            with pytest.raises(M4BError, match="Item not here"):
                fetch_metadata(ASIN)

    def test_400_is_distinguished_from_404(self) -> None:
        body = {
            "error": {
                "code": "CONTENT_TYPE_MISMATCH",
                "message": "Item is a BookSeries, not a book.",
            }
        }
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            side_effect=_http_error(400, body),
        ):
            with pytest.raises(M4BError, match="series"):
                fetch_metadata(ASIN)

    def test_other_http_error_reports_the_code(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            side_effect=_http_error(503),
        ):
            with pytest.raises(M4BError, match="503"):
                fetch_metadata(ASIN)

    def test_timeout_is_named_as_a_timeout(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen", side_effect=TimeoutError()
        ):
            with pytest.raises(M4BError, match="did not respond within"):
                fetch_metadata(ASIN, timeout=3.0)

    def test_wrapped_timeout_is_also_named(self) -> None:
        err = urllib.error.URLError(TimeoutError())
        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=err):
            with pytest.raises(M4BError, match="did not respond within"):
                fetch_metadata(ASIN)

    def test_unreachable_network(self) -> None:
        err = urllib.error.URLError("Name or service not known")
        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=err):
            with pytest.raises(M4BError, match="Could not reach Audnexus"):
                fetch_metadata(ASIN)

    def test_certificate_failure_is_not_blamed_on_the_connection(self) -> None:
        # Telling the user to check their internet sends them to the wrong place.
        import ssl

        err = urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))
        with patch("m4bmaker.audnexus.urllib.request.urlopen", side_effect=err):
            with pytest.raises(M4BError, match="certificate store"):
                fetch_metadata(ASIN)

    def test_malformed_json(self) -> None:
        resp = MagicMock()
        resp.read.return_value = b"{not json"
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: False
        with patch("m4bmaker.audnexus.urllib.request.urlopen", return_value=resp):
            with pytest.raises(M4BError, match="could not be read as JSON"):
                fetch_metadata(ASIN)

    def test_non_object_json(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response([1, 2, 3]),  # type: ignore[arg-type]
        ):
            with pytest.raises(M4BError, match="unexpected response shape"):
                fetch_metadata(ASIN)


# ---------------------------------------------------------------------------
# fetch_chapters
# ---------------------------------------------------------------------------


class TestFetchChapters:
    def test_parses_chapters_and_envelope(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(CHAPTERS_JSON),
        ):
            result = fetch_chapters(ASIN)
        assert len(result.chapters) == 3
        assert result.chapters[0].title == "Opening Credits"
        assert result.chapters[1].start_ms == 30970
        assert result.brand_intro_ms == 3970
        assert result.brand_outro_ms == 4945
        assert result.is_accurate is True

    def test_offsets_are_milliseconds(self) -> None:
        # Guard against the service switching to seconds: chapter 2 is ~31s in.
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(CHAPTERS_JSON),
        ):
            result = fetch_chapters(ASIN)
        assert result.chapters[1].start_ms == 30970
        assert 30 < result.chapters[1].start_ms / 1000.0 < 32

    def test_entries_missing_fields_are_skipped(self) -> None:
        payload = {
            **CHAPTERS_JSON,
            "chapters": [
                {"startOffsetMs": 0, "title": "Good"},
                {"startOffsetMs": "nope", "title": "Bad type"},
                {"title": "No offset"},
                "not a dict",
            ],
        }
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response(payload),
        ):
            assert len(fetch_chapters(ASIN).chapters) == 1

    def test_missing_chapter_list_raises(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response({"asin": ASIN}),
        ):
            with pytest.raises(M4BError, match="no chapter list"):
                fetch_chapters(ASIN)

    def test_empty_chapter_list_raises(self) -> None:
        with patch(
            "m4bmaker.audnexus.urllib.request.urlopen",
            return_value=_response({**CHAPTERS_JSON, "chapters": []}),
        ):
            with pytest.raises(M4BError, match="empty chapter list"):
                fetch_chapters(ASIN)


# ---------------------------------------------------------------------------
# reconcile_offsets
# ---------------------------------------------------------------------------


class TestReconcileOffsets:
    def test_clean_constant_offset(self) -> None:
        remote = _remote([("a", 10_000), ("b", 20_000), ("c", 30_000)])
        local = _local([7.0, 17.0, 27.0])
        result = reconcile_offsets(remote, local)
        assert result.shift == pytest.approx(-3.0)
        assert result.consistent is True
        assert result.matched == 3

    def test_median_ignores_one_bad_match(self) -> None:
        # Median, not mean: a single badly-matched chapter must not drag it.
        remote = _remote([("a", 10_000), ("b", 20_000), ("c", 30_000)])
        local = _local([7.0, 17.0, 27.5])
        assert reconcile_offsets(remote, local).shift == pytest.approx(-3.0)

    def test_brand_intro_outlier_stays_consistent(self) -> None:
        # The real case: Audible's branded intro sits INSIDE chapter 1, so a
        # file with it stripped has chapter 1 still at 0 and every later
        # chapter 3.97s earlier. That is one structurally explainable outlier
        # among identical values, and it must not fail the consistency check.
        remote = _remote([("a", 0), ("b", 30_970), ("c", 1_763_624), ("d", 3_070_001)])
        local = _local([0.0, 27.0, 1759.654, 3066.031])
        result = reconcile_offsets(remote, local, brand_intro_ms=3970)
        assert result.shift == pytest.approx(-3.97, abs=0.01)
        assert result.spread == pytest.approx(0.0, abs=0.01)
        assert result.consistent is True

    def test_derived_shift_is_corroborated_by_the_brand_intro(self) -> None:
        remote = _remote([("a", 0), ("b", 30_970), ("c", 1_763_624)])
        local = _local([0.0, 27.0, 1759.654])
        assert reconcile_offsets(remote, local, brand_intro_ms=3970).corroborated

    def test_no_corroboration_without_a_brand_intro(self) -> None:
        remote = _remote([("a", 10_000), ("b", 20_000)])
        local = _local([7.0, 17.0])
        result = reconcile_offsets(remote, local)
        assert result.brand_intro is None
        assert result.corroborated is False

    def test_scatter_reports_inconsistent(self) -> None:
        # A book that genuinely diverges mid-way: no single shift can be right.
        remote = _remote([("a", 10_000), ("b", 20_000), ("c", 30_000), ("d", 40_000)])
        local = _local([7.0, 17.0, 45.0, 85.0])
        result = reconcile_offsets(remote, local)
        assert result.consistent is False
        assert result.spread > DEFAULT_TOLERANCE

    def test_empty_inputs_are_not_consistent(self) -> None:
        assert reconcile_offsets([], _local([1.0])).consistent is False
        assert reconcile_offsets(_remote([("a", 0)]), []).consistent is False

    def test_no_io(self) -> None:
        # Pure arithmetic — it must not touch the network.
        with patch("m4bmaker.audnexus.urllib.request.urlopen") as opener:
            reconcile_offsets(_remote([("a", 1000)]), _local([1.0]))
        opener.assert_not_called()


# ---------------------------------------------------------------------------
# Apply modes
# ---------------------------------------------------------------------------


class TestApplyNames:
    def test_preserves_every_local_start_time(self) -> None:
        local = _local([0.0, 100.25, 250.5])
        remote = _remote([("One", 5000), ("Two", 99_000), ("Three", 260_000)])
        result = apply_names(remote, local)
        assert [c.start_time for c in result.chapters] == [0.0, 100.25, 250.5]

    def test_applies_the_titles(self) -> None:
        local = _local([0.0, 100.0])
        result = apply_names(_remote([("One", 0), ("Two", 9)]), local)
        assert [c.title for c in result.chapters] == ["One", "Two"]

    def test_more_remote_than_local_names_positionally(self) -> None:
        local = _local([0.0, 100.0])
        remote = _remote([("One", 0), ("Two", 1), ("Three", 2)])
        result = apply_names(remote, local)
        assert [c.title for c in result.chapters] == ["One", "Two"]
        assert "3 chapter(s)" in result.message and "2" in result.message

    def test_fewer_remote_than_local_keeps_the_rest(self) -> None:
        local = _local([0.0, 100.0, 200.0])
        result = apply_names(_remote([("One", 0)]), local)
        assert [c.title for c in result.chapters] == ["One", "Local 2", "Local 3"]
        assert "1 chapter(s)" in result.message

    def test_no_local_chapters(self) -> None:
        assert apply_names(_remote([("One", 0)]), []).chapters == []

    def test_never_reports_using_timings(self) -> None:
        result = apply_names(_remote([("One", 5000)]), _local([0.0]))
        assert result.used_timings is False
        assert result.shift == 0.0


class TestApplyTimings:
    def test_applies_the_derived_shift(self) -> None:
        remote = _remote([("a", 10_000), ("b", 20_000), ("c", 30_000)])
        local = _local([7.0, 17.0, 27.0])
        result = apply_timings(remote, local)
        assert result.used_timings is True
        assert result.shift == pytest.approx(-3.0)
        assert [c.start_time for c in result.chapters] == pytest.approx(
            [7.0, 17.0, 27.0]
        )

    def test_start_times_clamp_at_zero(self) -> None:
        remote = _remote([("a", 1000), ("b", 20_000)])
        local = _local([0.0, 15.0])
        assert apply_timings(remote, local).chapters[0].start_time >= 0.0

    def test_inconsistent_book_applies_no_shift(self) -> None:
        remote = _remote([("a", 10_000), ("b", 20_000), ("c", 30_000), ("d", 40_000)])
        local = _local([7.0, 17.0, 45.0, 85.0])
        result = apply_timings(remote, local)
        assert result.used_timings is False
        assert result.shift == 0.0
        # Falls back to names on the local boundaries, untouched.
        assert [c.start_time for c in result.chapters] == [7.0, 17.0, 45.0, 85.0]
        assert "do not line up" in result.message

    def test_corroborated_shift_says_so(self) -> None:
        remote = _remote([("a", 0), ("b", 30_970), ("c", 1_763_624)])
        local = _local([0.0, 27.0, 1759.654])
        message = apply_timings(remote, local, brand_intro_ms=3970).message
        assert "branded intro" in message

    def test_no_local_uses_the_brand_intro_as_the_shift(self) -> None:
        remote = _remote([("a", 0), ("b", 30_970)])
        result = apply_timings(remote, [], brand_intro_ms=3970)
        assert result.used_timings is True
        assert result.shift == pytest.approx(-3.97)
        assert "review" in result.message.lower()

    def test_no_local_and_no_brand_intro_is_unshifted_and_flagged(self) -> None:
        remote = _remote([("a", 0), ("b", 30_970)])
        result = apply_timings(remote, [])
        assert result.shift == 0.0
        assert "unverified" in result.message

    def test_no_remote_chapters_leaves_local_alone(self) -> None:
        local = _local([0.0, 50.0])
        result = apply_timings([], local)
        assert [c.start_time for c in result.chapters] == [0.0, 50.0]
        assert result.used_timings is False


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------


class TestAsinFlags:
    def test_flags_appear_in_help(self) -> None:
        from m4bmaker.cli import build_parser

        help_text = build_parser().format_help()
        assert "--asin" in help_text
        assert "--asin-region" in help_text
        assert "--asin-use-timings" in help_text

    def test_defaults(self, tmp_path) -> None:
        from m4bmaker.cli import parse_args

        args = parse_args([str(tmp_path)])
        assert args.asin is None
        assert args.asin_region == "us"
        assert args.asin_use_timings is False

    def test_values_parse(self, tmp_path) -> None:
        from m4bmaker.cli import parse_args

        args = parse_args(
            [str(tmp_path), "--asin", ASIN, "--asin-region", "uk", "--asin-use-timings"]
        )
        assert args.asin == ASIN
        assert args.asin_region == "uk"
        assert args.asin_use_timings is True

    def test_names_mode_is_the_default(self, tmp_path) -> None:
        # The safer mode must be what you get without asking for it.
        from m4bmaker.cli import parse_args

        assert parse_args([str(tmp_path), "--asin", ASIN]).asin_use_timings is False


# ---------------------------------------------------------------------------
# No third-party HTTP dependency
# ---------------------------------------------------------------------------


def test_client_uses_only_urllib() -> None:
    """The bundle must not grow an HTTP dependency."""
    import m4bmaker.audnexus as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "import aiohttp"):
        assert forbidden not in source
    assert "urllib.request" in source
