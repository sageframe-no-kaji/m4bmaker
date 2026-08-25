"""Vector icons painted at runtime, in place of colour-emoji glyphs.

Qt renders a colour emoji by asking the platform for the glyph. On macOS that
routes through CoreText's colour-emoji path, which decodes an embedded PNG
inside ImageIO -- and on Apple Silicon that decoder can hit a memory alignment
fault and take the whole process down with SIGBUS.

Issue #22 reported exactly that: a crescent-moon emoji on a QPushButton, built
during main-window construction, crashed the app before it drew a single frame,
reproducibly, on PySide6 6.8.3 and 6.11.1 alike. The bug is in the platform,
not in Qt or in this app, so the fix is to stop asking for colour emoji at all.

Painting the shapes ourselves keeps the emoji font out of the process
entirely, and lets each icon take its theme's foreground colour instead of
whatever the system emoji font decided it should be.

``tests/gui/test_icons.py`` enforces that no colour-emoji codepoint comes
back into the GUI package.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Painted at this many device pixels per logical pixel so the icon stays crisp
# on Retina displays and when Qt scales it up into a larger button.
_SUPERSAMPLE = 4

# These match the `color` declared for QPushButton#darkModeBtn in each theme's
# stylesheet (styles.py). A painted icon can't inherit the stylesheet's colour
# the way glyph text did, so the value is mirrored here deliberately.
_FG_LIGHT = "#4a4a4a"
_FG_DARK = "#c8c2b8"


def _canvas(size: int) -> QPixmap:
    """A transparent pixmap of ``size`` logical px, backed by 4x device px.

    Note that QPainter draws into this in *logical* coordinates -- the extra
    device pixels are supersampling, not a bigger canvas.
    """
    pixmap = QPixmap(size * _SUPERSAMPLE, size * _SUPERSAMPLE)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(float(_SUPERSAMPLE))
    return pixmap


def moon_icon(color: str, size: int = 16) -> QIcon:
    """A crescent moon: one disc with a second, offset disc subtracted."""
    pixmap = _canvas(size)
    extent = float(size)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))

    disc = QPainterPath()
    disc.addEllipse(QRectF(extent * 0.14, extent * 0.14, extent * 0.72, extent * 0.72))
    bite = QPainterPath()
    bite.addEllipse(QRectF(extent * 0.36, extent * 0.02, extent * 0.72, extent * 0.72))
    painter.drawPath(disc.subtracted(bite))
    painter.end()

    return QIcon(pixmap)


def sun_icon(color: str, size: int = 16) -> QIcon:
    """A filled disc with eight radiating rays."""
    pixmap = _canvas(size)
    extent = float(size)
    centre = QPointF(extent / 2, extent / 2)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(centre, extent * 0.22, extent * 0.22)

    pen = QPen(QColor(color))
    pen.setWidthF(extent * 0.075)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for step in range(8):
        angle = math.pi * step / 4
        unit_x, unit_y = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(
                centre.x() + unit_x * extent * 0.32,
                centre.y() + unit_y * extent * 0.32,
            ),
            QPointF(
                centre.x() + unit_x * extent * 0.44,
                centre.y() + unit_y * extent * 0.44,
            ),
        )
    painter.end()

    return QIcon(pixmap)


def dark_mode_icon(dark_mode: bool, size: int = 16) -> QIcon:
    """Icon for the dark-mode toggle: a sun while dark, a moon while light.

    The button offers the mode you would switch *to*, which is why the sun
    appears when dark mode is already on.
    """
    return sun_icon(_FG_DARK, size) if dark_mode else moon_icon(_FG_LIGHT, size)
