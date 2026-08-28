"""Audnexus API client — Audible metadata and chapter names by ASIN.

Audnexus (``api.audnex.us``) aggregates Audible data. No key, no account.

    GET https://api.audnex.us/books/{ASIN}?region={region}          -> metadata
    GET https://api.audnex.us/books/{ASIN}/chapters?region={region} -> chapters

The problem this module handles carefully: **Audible's chapter offsets
frequently do not match the user's file.** Audible's own master opens with a
branded intro — the API reports its length as ``brandIntroDurationMs``, around
four seconds — and most people's files do not have it, so every chapter after
the first sits that far out. A publisher intro or a different master shifts
things further. Audiobookshelf's answer is a "shift everything by N seconds"
box the user types into, and its users report needing it routinely.

m4Bookmaker does better because it can detect chapter boundaries in the user's
*actual* audio (:mod:`m4bmaker.silence`). So the default is to take Audible's
**names** and keep the **local boundaries** — remote offsets are never used and
the drift cannot arise. Using Audible's timings is the option, not the default,
and the shift is then *derived* by :func:`reconcile_offsets` rather than typed.

Nothing here runs implicitly. Every call in this module happens because the
user asked for it, and the only thing that leaves the machine is the ASIN.
"""

from __future__ import annotations

import json
import re
import ssl
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from m4bmaker import __version__
from m4bmaker.errors import M4BError
from m4bmaker.models import Chapter

_BASE_URL = "https://api.audnex.us"
_USER_AGENT = f"m4bmaker/{__version__}"

#: An Audible ASIN is ten alphanumeric characters, in practice ``B0`` + eight.
#: Checked locally so a typo costs nothing instead of a round trip.
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

DEFAULT_REGION = "us"
DEFAULT_TIMEOUT = 10.0

#: Spread, in seconds, within which per-chapter differences count as one
#: constant offset rather than a book that genuinely diverges.
DEFAULT_TOLERANCE = 2.0


@dataclass
class AudnexusChapter:
    """One chapter as Audnexus reports it."""

    title: str
    start_ms: int


@dataclass
class AudnexusBook:
    """Book metadata as Audnexus reports it. Absent fields are ``None``."""

    asin: str
    title: str | None = None
    author: str | None = None
    narrator: str | None = None
    genre: str | None = None
    cover_url: str | None = None


@dataclass
class AudnexusChapters:
    """The chapter envelope, including what Audible knows about its own master.

    *brand_intro_ms* is the length of Audible's branded intro. It is the single
    most common reason remote offsets do not line up with a user's file, and it
    is carried here so a derived shift can be checked against it.
    """

    chapters: list[AudnexusChapter] = field(default_factory=list)
    brand_intro_ms: int = 0
    brand_outro_ms: int = 0
    is_accurate: bool = True
    runtime_ms: int = 0


@dataclass
class OffsetAnalysis:
    """How well remote offsets line up with locally detected boundaries.

    *consistent* is the gate: one constant offset explains the whole book only
    when the per-chapter differences cluster tightly. A wide spread means the
    user's copy genuinely differs mid-book — an extra disc-break announcement,
    an omitted intro — and no single shift can be right.
    """

    shift: float = 0.0
    #: Median absolute deviation of the per-chapter differences from *shift*,
    #: not their full range — see :func:`reconcile_offsets` for why.
    spread: float = 0.0
    consistent: bool = False
    matched: int = 0
    #: The brand intro Audnexus reported, in seconds, when one is known. A
    #: derived shift landing near it is independent evidence it is correct.
    brand_intro: float | None = None

    @property
    def corroborated(self) -> bool:
        """True when the derived shift matches Audible's own brand-intro length."""
        if self.brand_intro is None or not self.consistent:
            return False
        return abs(abs(self.shift) - self.brand_intro) <= DEFAULT_TOLERANCE


# ── validation ───────────────────────────────────────────────────────────────


def validate_asin(asin: str) -> str:
    """Return *asin* normalised to upper case, or raise :class:`M4BError`.

    Checked before any request is made: a malformed ASIN is a typo, and a typo
    should not cost a round trip or read as "the database doesn't have it".
    """
    candidate = asin.strip().upper()
    if not _ASIN_RE.match(candidate):
        raise M4BError(
            f"'{asin.strip()}' is not a valid Audible ASIN.\n"
            "An ASIN is 10 letters and digits, usually starting with 'B0' — "
            "for example B017V4IM1G. You can find it in the Audible URL for "
            "the book, or in the product details on its Audible page."
        )
    return candidate


# ── transport ────────────────────────────────────────────────────────────────


def _error_message(body: bytes) -> str | None:
    """Return Audnexus's own error text from a JSON error body, if present.

    The API explains itself well — a missing book comes back as
    ``Item not available in region 'us' for ASIN: ...`` — so its message is
    better than anything reconstructed from a status code.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        message = payload["error"].get("message")
        if isinstance(message, str) and message:
            return message
    return None


def _get(path: str, region: str, timeout: float) -> dict[str, object]:
    """GET *path* from Audnexus and return the decoded JSON object.

    The only thing sent is the ASIN embedded in *path* and the region — no
    filenames, no paths, no identifiers.
    """
    url = f"{_BASE_URL}{path}?region={urllib.parse.quote(region)}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = _error_message(exc.read()) if exc.fp is not None else None
        if exc.code == 404:
            raise M4BError(
                f"Audnexus has no book for that ASIN in region '{region}'.\n"
                + (f"{detail}\n" if detail else "")
                + "An ASIN belongs to one Audible storefront, so the most "
                "likely cause is the wrong region — try 'uk', 'de', 'fr', "
                "'ca', or 'au' if the book was not bought on audible.com."
            ) from exc
        if exc.code == 400:
            raise M4BError(
                f"Audnexus rejected that request for region '{region}'.\n"
                + (f"{detail}\n" if detail else "")
                + "This usually means the ASIN belongs to a series or an "
                "author rather than to a single book."
            ) from exc
        raise M4BError(
            f"Audnexus returned HTTP {exc.code} for region '{region}'."
            + (f"\n{detail}" if detail else "")
        ) from exc
    except TimeoutError as exc:
        raise M4BError(
            f"Audnexus did not respond within {timeout:g} seconds. "
            "Check your connection and try again."
        ) from exc
    except urllib.error.URLError as exc:
        # A socket timeout arrives wrapped in URLError on some platforms.
        if isinstance(exc.reason, TimeoutError):
            raise M4BError(
                f"Audnexus did not respond within {timeout:g} seconds. "
                "Check your connection and try again."
            ) from exc
        # A certificate failure is not a connectivity problem, and telling the
        # user to check their internet sends them looking in the wrong place.
        if isinstance(exc.reason, ssl.SSLError):
            raise M4BError(
                "Could not verify the secure connection to Audnexus.\n"
                f"{exc.reason}\n"
                "This usually means this machine's certificate store is "
                "incomplete rather than that anything is wrong with the "
                "service. On macOS, running 'Install Certificates.command' "
                "from your Python installation usually fixes it."
            ) from exc
        raise M4BError(
            f"Could not reach Audnexus ({exc.reason}). "
            "Check your internet connection and try again."
        ) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise M4BError(
            "Audnexus returned a response that could not be read as JSON. "
            "The service may be having trouble; try again shortly."
        ) from exc

    if not isinstance(payload, dict):
        raise M4BError("Audnexus returned an unexpected response shape.")
    return payload


# ── fetching ─────────────────────────────────────────────────────────────────


def _first_name(value: object) -> str | None:
    """Pull the first ``name`` out of Audnexus's list-of-objects fields.

    ``authors`` and ``narrators`` are lists of ``{"name": ...}``, not strings.
    """
    if not isinstance(value, list):
        return None
    for entry in value:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def _first_genre(value: object) -> str | None:
    """Return the first entry of ``genres`` whose type is ``genre``.

    The list mixes genres and tags; only the former belongs in the field.
    """
    if not isinstance(value, list):
        return None
    for entry in value:
        if isinstance(entry, dict) and entry.get("type") == "genre":
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def fetch_metadata(
    asin: str,
    region: str = DEFAULT_REGION,
    timeout: float = DEFAULT_TIMEOUT,
) -> AudnexusBook:
    """Fetch book metadata for *asin*. Only the ASIN leaves the machine."""
    checked = validate_asin(asin)
    payload = _get(f"/books/{checked}", region, timeout)

    title = payload.get("title")
    image = payload.get("image")
    return AudnexusBook(
        asin=checked,
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        author=_first_name(payload.get("authors")),
        narrator=_first_name(payload.get("narrators")),
        genre=_first_genre(payload.get("genres")),
        cover_url=(
            image if isinstance(image, str) and image.startswith("http") else None
        ),
    )


def fetch_chapters(
    asin: str,
    region: str = DEFAULT_REGION,
    timeout: float = DEFAULT_TIMEOUT,
) -> AudnexusChapters:
    """Fetch the chapter list for *asin*. Only the ASIN leaves the machine."""
    checked = validate_asin(asin)
    payload = _get(f"/books/{checked}/chapters", region, timeout)

    raw = payload.get("chapters")
    if not isinstance(raw, list):
        raise M4BError(
            f"Audnexus returned no chapter list for {checked} in region "
            f"'{region}'. Not every title has chapter data."
        )

    chapters: list[AudnexusChapter] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        start = entry.get("startOffsetMs")
        if not isinstance(title, str) or not isinstance(start, int):
            continue
        chapters.append(AudnexusChapter(title=title.strip(), start_ms=start))

    if not chapters:
        raise M4BError(
            f"Audnexus returned an empty chapter list for {checked} in region "
            f"'{region}'."
        )

    def _int(key: str) -> int:
        value = payload.get(key)
        return value if isinstance(value, int) else 0

    accurate = payload.get("isAccurate")
    return AudnexusChapters(
        chapters=chapters,
        brand_intro_ms=_int("brandIntroDurationMs"),
        brand_outro_ms=_int("brandOutroDurationMs"),
        is_accurate=accurate if isinstance(accurate, bool) else True,
        runtime_ms=_int("runtimeLengthMs"),
    )


# ── offset reconciliation ────────────────────────────────────────────────────


def reconcile_offsets(
    remote: list[AudnexusChapter],
    local: list[Chapter],
    tolerance: float = DEFAULT_TOLERANCE,
    brand_intro_ms: int = 0,
) -> OffsetAnalysis:
    """Derive the constant offset between *remote* timings and *local* boundaries.

    For each remote chapter, the nearest local boundary is found and the
    difference recorded. The **median** of those differences is the derived
    shift — median rather than mean because one badly-matched chapter should
    not drag the answer.

    *spread* is how far those differences scatter, measured as the **median
    absolute deviation** from the shift rather than as ``max - min``. That
    choice matters: Audible's branded intro sits *inside* chapter 1, so a file
    with the intro stripped has chapter 1 still starting at 0 while every later
    chapter moves earlier. The differences are then one ``0.0`` among a run of
    identical values — perfectly consistent data with one structurally
    explainable outlier, which ``max - min`` would reject and MAD reports as
    ``0.0``. MAD still catches real divergence: an extra announcement partway
    through a book pushes it well past any sane tolerance.

    A tight cluster means one constant offset explains the whole book and
    applying *shift* is safe. A wide spread means the copy genuinely differs
    mid-book, ``consistent`` is ``False``, and **the caller must not apply a
    shift**.

    *brand_intro_ms*, when given, is recorded so the caller can see whether the
    derived shift matches the branded intro Audible reports for its own master
    — independent evidence that the number is right rather than coincidence.

    Pure arithmetic, no I/O.
    """
    brand_intro = brand_intro_ms / 1000.0 if brand_intro_ms else None

    if not remote or not local:
        return OffsetAnalysis(brand_intro=brand_intro)

    local_times = [chapter.start_time for chapter in local]
    differences: list[float] = []
    for chapter in remote:
        remote_seconds = chapter.start_ms / 1000.0
        nearest = min(local_times, key=lambda t: abs(t - remote_seconds))
        differences.append(nearest - remote_seconds)

    shift = statistics.median(differences)
    spread = statistics.median([abs(d - shift) for d in differences])
    return OffsetAnalysis(
        shift=shift,
        spread=spread,
        consistent=spread <= tolerance,
        matched=len(differences),
        brand_intro=brand_intro,
    )


# ── applying results to a chapter list ───────────────────────────────────────


@dataclass
class ApplyResult:
    """Chapters to show the user, plus a plain account of what was done."""

    chapters: list[Chapter]
    message: str
    used_timings: bool = False
    shift: float = 0.0


def apply_names(remote: list[AudnexusChapter], local: list[Chapter]) -> ApplyResult:
    """Put Audible's titles onto locally detected boundaries.

    The default mode, and the safe one: every local ``start_time`` is preserved
    exactly and only titles change, so remote offsets are never consulted and
    the usual few-second drift cannot occur.

    When the counts differ, names are applied positionally as far as they go
    and the mismatch is reported rather than treated as a failure — a book with
    an extra "Opening Credits" entry is still better off named than not.
    """
    if not local:
        return ApplyResult(chapters=[], message="No local chapters to name.")

    named: list[Chapter] = []
    for i, chapter in enumerate(local):
        title = remote[i].title if i < len(remote) else chapter.title
        named.append(
            Chapter(
                index=chapter.index,
                start_time=chapter.start_time,
                title=title,
                source_file=chapter.source_file,
            )
        )

    if len(remote) == len(local):
        message = f"Applied {len(remote)} chapter name(s); timings unchanged."
    else:
        message = (
            f"Audible lists {len(remote)} chapter(s) but this book has "
            f"{len(local)}. Named the first {min(len(remote), len(local))} in "
            "order and left the rest; timings unchanged."
        )
    return ApplyResult(chapters=named, message=message)


def apply_timings(
    remote: list[AudnexusChapter],
    local: list[Chapter],
    brand_intro_ms: int = 0,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ApplyResult:
    """Use Audible's timings, shifted by a derived offset.

    Never applies remote offsets raw. With local boundaries to reconcile
    against, the shift is derived and applied only when it is *consistent*;
    an inconsistent book falls back to :func:`apply_names`, because a
    confidently wrong chapter map is worse than none.

    With no local boundaries there is nothing to reconcile against, so the
    branded intro Audible reports for its own master is used as the shift when
    it knows one — a principled guess rather than an arbitrary one — and the
    user is told the result is unverified.
    """
    if not remote:
        return ApplyResult(chapters=list(local), message="Audible listed no chapters.")

    if not local:
        shift = -brand_intro_ms / 1000.0 if brand_intro_ms else 0.0
        chapters = _shifted(remote, shift)
        if brand_intro_ms:
            message = (
                f"Applied {len(chapters)} chapter(s) from Audible, shifted by "
                f"{shift:+.2f}s for the branded intro Audible reports. "
                "Nothing local to check this against — review before "
                "converting."
            )
        else:
            message = (
                f"Applied {len(chapters)} chapter(s) from Audible unshifted. "
                "There are no detected boundaries to check them against, so "
                "these timings are unverified — review before converting."
            )
        return ApplyResult(
            chapters=chapters, message=message, used_timings=True, shift=shift
        )

    analysis = reconcile_offsets(remote, local, tolerance, brand_intro_ms)

    if not analysis.consistent:
        fallback = apply_names(remote, local)
        return ApplyResult(
            chapters=fallback.chapters,
            message=(
                f"Audible's timings do not line up consistently with this "
                f"book — chapter offsets differ by {analysis.spread:.1f}s on "
                "either side of the median, so no single shift can be right. "
                "This usually means the copy genuinely differs mid-book. "
                f"Kept the detected boundaries instead. {fallback.message}"
            ),
        )

    chapters = _shifted(remote, analysis.shift)
    note = ""
    if analysis.corroborated:
        note = (
            f" That matches the {analysis.brand_intro:.2f}s branded intro "
            "Audible reports for its own master, so the shift is very likely "
            "right."
        )
    return ApplyResult(
        chapters=chapters,
        message=(
            f"Applied {len(chapters)} chapter(s) from Audible, shifted by "
            f"{analysis.shift:+.2f}s to match this book's audio.{note}"
        ),
        used_timings=True,
        shift=analysis.shift,
    )


def _shifted(remote: list[AudnexusChapter], shift: float) -> list[Chapter]:
    """Return *remote* as :class:`Chapter` objects moved by *shift* seconds.

    Start times are clamped at zero: a negative shift would otherwise push the
    opening chapter before the beginning of the file.
    """
    return [
        Chapter(
            index=i,
            start_time=max(0.0, chapter.start_ms / 1000.0 + shift),
            title=chapter.title,
            source_file=None,
        )
        for i, chapter in enumerate(remote, start=1)
    ]
