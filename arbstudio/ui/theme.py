"""Koyu tema paleti ve durum renkleri."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..model.keyinfo import KeyStatus

BG = QColor(30, 31, 34)
BG_ALT = QColor(43, 45, 49)
BASE = QColor(24, 25, 28)
TEXT = QColor(222, 224, 228)
TEXT_DIM = QColor(150, 154, 162)
ACCENT = QColor(88, 140, 220)

STATUS_COLORS = {
    KeyStatus.MISSING: QColor(224, 88, 88),
    KeyStatus.SAME_AS_SOURCE: QColor(224, 176, 72),
    KeyStatus.TRANSLATED: QColor(96, 184, 112),
}

SEVERITY_COLORS = {
    "error": QColor(224, 88, 88),
    "warning": QColor(224, 176, 72),
    "info": QColor(120, 160, 210),
}

STYLESHEET = """
QWidget { font-size: 13px; }
QToolBar { border: none; padding: 4px; spacing: 2px; }
QToolBar QToolButton { padding: 5px 9px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #3a3d43; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #1e1f22; border: 1px solid #3a3d43; border-radius: 4px; padding: 4px;
    selection-background-color: #588cdc;
}
QPlainTextEdit:focus, QLineEdit:focus { border: 1px solid #588cdc; }
QPlainTextEdit[phError="true"] { border: 1px solid #e05858; }
QPlainTextEdit[readOnly="true"] { background: #26272b; color: #a8acb4; }
QListView { background: #1e1f22; border: none; outline: none; }
QListView::item { padding: 3px 6px; }
QListView::item:selected { background: #34517e; }
QTableWidget { background: #1e1f22; gridline-color: #34363b; border: none; }
QHeaderView::section {
    background: #2b2d31; color: #c8ccd4; padding: 4px; border: none;
    border-right: 1px solid #34363b; border-bottom: 1px solid #34363b;
}
QGroupBox {
    border: 1px solid #3a3d43; border-radius: 5px; margin-top: 9px; padding-top: 6px;
}
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; color: #9aa0ab; }
QPushButton {
    background: #3a3d43; border: none; border-radius: 4px; padding: 6px 13px;
}
QPushButton:hover { background: #464a52; }
QPushButton:disabled { background: #2b2d31; color: #6b6f77; }
QPushButton[accent="true"] { background: #3f6cb5; }
QPushButton[accent="true"]:hover { background: #4a7cc9; }
QSplitter::handle { background: #2b2d31; }
QStatusBar { background: #2b2d31; }
QProgressBar { border: 1px solid #3a3d43; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #3f6cb5; border-radius: 3px; }
QScrollBar:vertical { background: #1e1f22; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #45484f; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QToolTip { background: #2b2d31; color: #dee0e4; border: 1px solid #45484f; padding: 4px; }
"""


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, BG)
    palette.setColor(QPalette.WindowText, TEXT)
    palette.setColor(QPalette.Base, BASE)
    palette.setColor(QPalette.AlternateBase, BG_ALT)
    palette.setColor(QPalette.Text, TEXT)
    palette.setColor(QPalette.Button, BG_ALT)
    palette.setColor(QPalette.ButtonText, TEXT)
    palette.setColor(QPalette.Highlight, ACCENT)
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipBase, BG_ALT)
    palette.setColor(QPalette.ToolTipText, TEXT)
    palette.setColor(QPalette.PlaceholderText, TEXT_DIM)
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(110, 114, 122))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(110, 114, 122))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
