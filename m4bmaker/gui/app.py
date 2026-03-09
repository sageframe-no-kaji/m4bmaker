"""GUI entry point — run with ``m4bmaker-gui`` or ``python -m m4bmaker.gui``."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from m4bmaker.gui.styles import get_stylesheet
from m4bmaker.gui.window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("m4bmaker")
    app.setStyleSheet(get_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
