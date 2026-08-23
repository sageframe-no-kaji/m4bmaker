"""Tests for the painted replacements for colour-emoji glyphs — closes #22.

Two concerns:

1. The icon factories in ``m4bmaker.gui.icons`` produce real, non-null icons
   at the size asked for.
2. No colour-emoji codepoint has crept back into the GUI package. This is the
   regression guard: the crash in #22 came from a single emoji character in a
   button label, and nothing about the code around it looked dangerous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QSize

from m4bmaker.gui.icons import dark_mode_icon, moon_icon, sun_icon

GUI_PACKAGE = Path(__file__).resolve().parent.parent.parent / "m4bmaker" / "gui"


# ---------------------------------------------------------------------------
# Icon factories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", [moon_icon, sun_icon])
def test_icon_factories_produce_a_drawable_icon(qapp, factory):
    """Each factory returns a non-null icon that renders at the asked size."""
    icon = factory("#4a4a4a", 16)
    assert not icon.isNull()

    pixmap = icon.pixmap(QSize(16, 16))
    assert not pixmap.isNull()
    assert pixmap.size().width() > 0 and pixmap.size().height() > 0


def _ink(image, box=None):
    """Count opaque pixels, optionally only inside ``box`` = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box or (0, 0, image.width(), image.height())
    return sum(
        1
        for y in range(y0, y1)
        for x in range(x0, x1)
        if image.pixelColor(x, y).alpha() > 0
    )


@pytest.mark.parametrize("factory", [moon_icon, sun_icon])
def test_icons_fill_their_canvas(qapp, factory):
    """The shape must land inside the icon, at a sane size.

    The first cut of these painters drew in device coordinates on a canvas
    that QPainter addresses in logical ones, so every shape came out 4x too
    large and only its top-left corner survived the crop. The icon was not
    empty -- it just wasn't a moon. Asserting "something was painted" passes
    happily on that, so this checks coverage and placement instead.
    """
    size = 32
    image = factory("#000000", size).pixmap(QSize(size, size)).toImage()
    total = image.width() * image.height()

    coverage = _ink(image) / total
    assert 0.05 < coverage < 0.80, f"implausible ink coverage: {coverage:.0%}"

    # The shape is centred, so the middle half of the icon must carry ink.
    quarter, three_quarters = image.width() // 4, image.width() * 3 // 4
    centre = _ink(image, (quarter, quarter, three_quarters, three_quarters))
    assert centre > 0, "nothing painted in the centre of the icon"


def test_dark_mode_icon_differs_by_mode(qapp):
    """The toggle offers the mode you'd switch to, so the two must not match."""
    light = dark_mode_icon(False, 16).pixmap(QSize(16, 16)).toImage()
    dark = dark_mode_icon(True, 16).pixmap(QSize(16, 16)).toImage()
    assert not light.isNull() and not dark.isNull()
    assert light != dark


# ---------------------------------------------------------------------------
# Regression guard: no colour emoji anywhere in the GUI package
# ---------------------------------------------------------------------------

# Codepoints that macOS renders from the colour-emoji font, which is the path
# that crashes in #22. Two groups:
#
#   * VARIATION SELECTOR-16 (U+FE0F), which forces emoji presentation onto an
#     otherwise-harmless text glyph. U+2600 alone is a text glyph; U+2600
#     followed by U+FE0F is a colour emoji.
#   * The Emoji_Presentation=Yes set -- codepoints that render as colour emoji
#     with no variation selector at all.
#
# The BMP ranges below are the Emoji_Presentation=Yes members of the BMP; the
# supplementary range covers the emoji planes wholesale. Text-presentation
# characters the UI relies on -- box drawing, arrows, PLACE OF INTEREST SIGN,
# BLACK HEART SUIT, BALLOT X -- are deliberately outside these ranges and stay
# allowed.
_VARIATION_SELECTOR_16 = "\ufe0f"

_EMOJI_PRESENTATION_RANGES = [
    (0x231A, 0x231B),
    (0x23E9, 0x23EC),
    (0x23F0, 0x23F0),
    (0x23F3, 0x23F3),
    (0x25FD, 0x25FE),
    (0x2614, 0x2615),
    (0x2648, 0x2653),
    (0x267F, 0x267F),
    (0x2693, 0x2693),
    (0x26A1, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26CE, 0x26CE),
    (0x26D4, 0x26D4),
    (0x26EA, 0x26EA),
    (0x26F2, 0x26F3),
    (0x26F5, 0x26F5),
    (0x26FA, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2705, 0x2705),
    (0x270A, 0x270B),
    (0x2728, 0x2728),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2795, 0x2797),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x1F000, 0x1FAFF),
]


def _is_colour_emoji(char: str) -> bool:
    point = ord(char)
    return any(low <= point <= high for low, high in _EMOJI_PRESENTATION_RANGES)


def _gui_source_files() -> list[Path]:
    return sorted(GUI_PACKAGE.rglob("*.py"))


def test_gui_package_has_source_files_to_scan():
    """Guard the guard: a bad path would make the scan below vacuously pass."""
    files = _gui_source_files()
    assert len(files) > 5
    assert any(f.name == "window.py" for f in files)


@pytest.mark.parametrize("path", _gui_source_files(), ids=lambda p: p.name)
def test_no_colour_emoji_in_gui_source(path):
    """No colour-emoji codepoint may appear in GUI source. See #22.

    Rendering one on macOS/Apple Silicon can abort the process with SIGBUS
    inside ImageIO. Use ``m4bmaker.gui.icons`` for iconography instead.
    """
    offenders: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for char in line:
            if _is_colour_emoji(char):
                offenders.append(f"{path.name}:{lineno}: U+{ord(char):04X}")
        if _VARIATION_SELECTOR_16 in line:
            offenders.append(
                f"{path.name}:{lineno}: U+FE0F (forces emoji presentation)"
            )

    assert not offenders, "colour emoji found:\n  " + "\n  ".join(offenders)


def test_window_builds_the_toggle_from_an_icon_not_a_label():
    """The specific construction that crashed in #22 must not come back."""
    source = (GUI_PACKAGE / "window.py").read_text(encoding="utf-8")
    assert "dark_mode_icon(self._dark_mode)" in source
    assert not re.search(r"_dark_btn\s*=\s*QPushButton\(\s*['\"]", source)
