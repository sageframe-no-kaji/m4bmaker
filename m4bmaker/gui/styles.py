"""QSS stylesheet — design tokens applied to Qt widgets.

Palette
-------
Ink          #1a1a1a   primary text
Ink Light    #4a4a4a   body text
Ink Muted    #7a7a7a   labels / hints
Ground       #f5f2ed   window background
Ground Warm  #ebe6dd   cards / group boxes
White        #faf8f4   input surfaces
Terracotta   #c45a2d   accent / primary action
Rule         #d0c9be   borders / dividers
"""

from __future__ import annotations

STYLESHEET = """
/* ── Reset ──────────────────────────────────────────────────────────── */
* {
    font-size: 13px;
}

/* ── Window / base ───────────────────────────────────────────────────── */
QMainWindow,
QDialog {
    background-color: #f5f2ed;
}

QWidget {
    background-color: #f5f2ed;
    color: #1a1a1a;
}

/* ── Group boxes (warm cards) ────────────────────────────────────────── */
QGroupBox {
    background-color: #ebe6dd;
    border: 1px solid #d0c9be;
    border-radius: 4px;
    margin-top: 20px;
    padding-top: 6px;
    font-size: 11px;
    font-weight: 600;
    color: #7a7a7a;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 1px;
    padding: 3px 10px;
    background-color: #ebe6dd;
    border: 1px solid #d0c9be;
    border-bottom-color: #ebe6dd;
    border-radius: 4px 4px 0 0;
}

/* ── Labels ──────────────────────────────────────────────────────────── */
QLabel {
    background: transparent;
    color: #1a1a1a;
}

QLabel#statusLabel {
    color: #7a7a7a;
    font-size: 12px;
}

/* ── Line edits ──────────────────────────────────────────────────────── */
QLineEdit {
    background-color: #faf8f4;
    border: 1px solid #d0c9be;
    border-radius: 3px;
    padding: 5px 8px;
    color: #1a1a1a;
    selection-background-color: #c45a2d;
    selection-color: #faf8f4;
    min-height: 22px;
}

QLineEdit:focus {
    border-color: #c45a2d;
}

QLineEdit:disabled {
    background-color: #ebe6dd;
    color: #7a7a7a;
}

QLineEdit[readOnly="true"] {
    background-color: #ebe6dd;
    color: #4a4a4a;
}

/* ── Combo boxes ─────────────────────────────────────────────────────── */
QComboBox {
    background-color: #faf8f4;
    border: 1px solid #d0c9be;
    border-radius: 3px;
    padding: 4px 8px;
    color: #1a1a1a;
    min-height: 22px;
}

QComboBox:focus {
    border-color: #c45a2d;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background-color: #faf8f4;
    border: 1px solid #d0c9be;
    outline: none;
    selection-background-color: #c45a2d;
    selection-color: #faf8f4;
}

/* ── Buttons ─────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #ebe6dd;
    border: 1px solid #d0c9be;
    border-radius: 5px;
    padding: 4px 12px;
    color: #4a4a4a;
    min-height: 20px;
    font-size: 11px;
}

QPushButton:hover {
    background-color: #ddd7cc;
    border-color: #b5ae9e;
}

QPushButton:pressed {
    background-color: #d0c9be;
}

QPushButton:disabled {
    color: #7a7a7a;
    border-color: #e0dbd2;
}

QPushButton#convertBtn {
    background-color: #c45a2d;
    color: #faf8f4;
    border: none;
    border-radius: 4px;
    padding: 10px 32px;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.02em;
}

QPushButton#convertBtn:hover {
    background-color: #b3511f;
}

QPushButton#convertBtn:pressed {
    background-color: #9e4719;
}

QPushButton#convertBtn:disabled {
    background-color: #d0c9be;
    color: #faf8f4;
}

/* ── Radio buttons ───────────────────────────────────────────────────── */
QRadioButton {
    background: transparent;
    color: #4a4a4a;
    spacing: 6px;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #d0c9be;
    border-radius: 7px;
    background-color: #faf8f4;
}

QRadioButton::indicator:checked {
    background-color: #c45a2d;
    border-color: #c45a2d;
}

QRadioButton::indicator:hover {
    border-color: #c45a2d;
}

/* ── Check boxes ─────────────────────────────────────────────────────── */
QCheckBox {
    background: transparent;
    color: #4a4a4a;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #d0c9be;
    border-radius: 2px;
    background-color: #faf8f4;
}

QCheckBox::indicator:checked {
    background-color: #c45a2d;
    border-color: #c45a2d;
}

/* ── Scroll areas ────────────────────────────────────────────────────── */
QScrollArea,
QScrollArea > QWidget > QWidget {
    background-color: #f5f2ed;
}

/* ── Tabs ────────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #d0c9be;
    border-radius: 0 4px 4px 4px;
    background-color: #f5f2ed;
    top: -1px;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background-color: #ebe6dd;
    border: 1px solid #d0c9be;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 24px;
    min-width: 100px;
    color: #7a7a7a;
    font-size: 12px;
    margin-right: 3px;
}

QTabBar::tab:selected {
    background-color: #f5f2ed;
    color: #1a1a1a;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #ddd7cc;
    color: #4a4a4a;
}

QTabBar::tab:disabled {
    color: #b5ae9e;
}

/* ── Progress bar ────────────────────────────────────────────────────── */
QProgressBar {
    background-color: #ebe6dd;
    border: 1px solid #d0c9be;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #c45a2d;
    border-radius: 2px;
}

/* ── Table ───────────────────────────────────────────────────────────── */
QTableWidget {
    background-color: #faf8f4;
    border: 1px solid #d0c9be;
    border-radius: 3px;
    gridline-color: #d0c9be;
    alternate-background-color: #f5f2ed;
    color: #1a1a1a;
    selection-background-color: #c45a2d;
    selection-color: #faf8f4;
    outline: none;
}

QTableWidget::item {
    padding: 5px 8px;
}

QTableWidget::item:selected {
    background-color: #c45a2d;
    color: #faf8f4;
}

QHeaderView::section {
    background-color: #ebe6dd;
    border: none;
    border-right: 1px solid #d0c9be;
    border-bottom: 1px solid #d0c9be;
    padding: 6px 8px;
    color: #7a7a7a;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

QHeaderView::section:last {
    border-right: none;
}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 7px;
    margin: 2px 0;
}

QScrollBar::handle:vertical {
    background: #d0c9be;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #b5ae9e;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 7px;
    margin: 0 2px;
}

QScrollBar::handle:horizontal {
    background: #d0c9be;
    border-radius: 3px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: #b5ae9e;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Context / pop-up menus ──────────────────────────────────────────── */
QMenu {
    background-color: #faf8f4;
    border: 1px solid #d0c9be;
    border-radius: 4px;
    padding: 4px 0;
}

QMenu::item {
    padding: 5px 22px;
    color: #1a1a1a;
    background: transparent;
}

QMenu::item:selected {
    background-color: #c45a2d;
    color: #faf8f4;
}

QMenu::separator {
    height: 1px;
    background-color: #d0c9be;
    margin: 3px 8px;
}

/* ── Player transport buttons ────────────────────────────────────────── */
QPushButton#playerPlayBtn,
QPushButton#playerStopBtn {
    background-color: #4a4a4a;
    border: none;
    border-radius: 4px;
    color: #faf8f4;
    font-size: 14px;
    padding: 0;
}

QPushButton#playerPlayBtn:hover,
QPushButton#playerStopBtn:hover {
    background-color: #333333;
}

QPushButton#playerPlayBtn:pressed,
QPushButton#playerStopBtn:pressed {
    background-color: #1a1a1a;
}

QPushButton#playerPlayBtn:disabled,
QPushButton#playerStopBtn:disabled {
    background-color: #b5ae9e;
    color: #ebe6dd;
}

/* ── Dialogs ─────────────────────────────────────────────────────────── */
QDialogButtonBox QPushButton {
    min-width: 72px;
}
"""
