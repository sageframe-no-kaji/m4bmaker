"""Side-by-side cover chooser for looked-up cover art.

An Audnexus lookup usually returns official publisher art, and the book on
disk usually already has *something* — art found beside the files, or a
thumbnail embedded in a CD rip. Neither is reliably the better one, and
silently picking either is wrong: applying the fetched art discards a cover
the user may have chosen deliberately, while keeping the existing one makes
the lookup they asked for do nothing.

So both are shown, at the size they actually are, and the user picks. The
pixel dimensions are the useful part of the comparison — an embedded rip
thumbnail is often 200px next to publisher art ten times that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: Edge length of each preview, in pixels.
_PREVIEW = 220


def describe_cover(path: Path) -> str:
    """Return a short ``WIDTH x HEIGHT`` description of the image at *path*.

    Falls back to the file name when the image cannot be read, so a cover that
    Qt cannot decode still gets a row rather than an empty space.
    """
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return "unreadable image"
    return f"{pixmap.width()} x {pixmap.height()} px"


def _preview(path: Path, caption: str, detail: str) -> QWidget:
    """Build one labelled preview column."""
    column = QWidget()
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    title = QLabel(caption)
    title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    title.setStyleSheet("font-weight: 600;")
    layout.addWidget(title)

    thumb = QLabel()
    thumb.setFixedSize(_PREVIEW, _PREVIEW)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    thumb.setStyleSheet("border: 1px solid palette(mid);")
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        thumb.setText("Preview unavailable")
    else:
        thumb.setPixmap(
            pixmap.scaled(
                _PREVIEW,
                _PREVIEW,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    layout.addWidget(thumb)

    size_label = QLabel(detail)
    size_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    size_label.setStyleSheet("color: #7a7a7a; font-size: 11px;")
    layout.addWidget(size_label)

    return column


class CoverChoiceDialog(QDialog):
    """Ask which of two covers to use. Returns the chosen path, or ``None``.

    Deliberately has no default-accept: the user clicks the one they want.
    Closing the dialog keeps the existing cover, because doing nothing should
    never be the destructive option.
    """

    def __init__(
        self,
        current: Path,
        fetched: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._current = current
        self._fetched = fetched
        self._chosen: Optional[Path] = None
        self.setWindowTitle("Choose Cover Art")
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        blurb = QLabel("The lookup found cover art. Which would you like to use?")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        previews = QHBoxLayout()
        previews.setSpacing(16)
        previews.addWidget(
            _preview(self._current, "Current", describe_cover(self._current))
        )
        previews.addWidget(
            _preview(self._fetched, "From lookup", describe_cover(self._fetched))
        )
        layout.addLayout(previews)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()

        keep_btn = QPushButton("Keep Current")
        keep_btn.clicked.connect(self._keep_current)
        buttons.addWidget(keep_btn)

        use_btn = QPushButton("Use Looked-Up Cover")
        use_btn.setDefault(True)
        use_btn.clicked.connect(self._use_fetched)
        buttons.addWidget(use_btn)

        layout.addLayout(buttons)

    def _keep_current(self) -> None:
        self._chosen = self._current
        self.accept()

    def _use_fetched(self) -> None:
        self._chosen = self._fetched
        self.accept()

    def chosen(self) -> Optional[Path]:
        """The cover the user picked, or ``None`` if the dialog was dismissed."""
        return self._chosen
