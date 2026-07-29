"""Modern dark/light-aware QSS stylesheet for PlasmaGuard.

Plasma themes vary wildly, so we keep this conservative: rounded corners,
generous padding, accent colors that match the shield icon, and no reliance
on KDE-specific widgets.
"""

QSS = """
* {
    font-family: "Inter", "Noto Sans", "Segoe UI", "Cantarell", "Ubuntu", sans-serif;
    font-size: 11pt;
}

QMainWindow, QDialog, QWidget#centralWidget {
    background-color: palette(window);
    color: palette(text);
}

/* Headings ----------------------------------------------------------- */

QLabel#titleLabel {
    font-size: 22pt;
    font-weight: 600;
    color: #1B73B8;
}

QLabel#subtitleLabel {
    font-size: 10pt;
    color: palette(mid);
}

QLabel#cardTitle {
    font-size: 11pt;
    font-weight: 600;
}

QLabel#cardBig {
    font-size: 20pt;
    font-weight: 700;
}

QLabel#cardSub {
    font-size: 10pt;
    color: palette(mid);
}

QLabel#statusOK      { color: #2E7D32; font-weight: 600; }
QLabel#statusWarn    { color: #C77800; font-weight: 600; }
QLabel#statusBad     { color: #C62828; font-weight: 600; }
QLabel#statusDot     { font-size: 28px; color: #2E7D32; }
QLabel#sidebarStatus { padding: 10px 12px; font-weight: 600; }
QLabel#scanBold      { font-weight: 600; }

/* Sidebar ------------------------------------------------------------ */

QListWidget#sidebar {
    background: palette(window);
    border: none;
    padding: 12px 6px;
    outline: 0;
}

QListWidget#sidebar::item {
    padding: 10px 14px;
    border-radius: 8px;
    margin: 2px 4px;
    color: palette(text);
}

QListWidget#sidebar::item:selected {
    background: #1B73B8;
    color: white;
}

QListWidget#sidebar::item:hover:!selected {
    background: rgba(27, 115, 184, 0.15);
}

/* Cards -------------------------------------------------------------- */

QFrame#card {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 12px;
}

QFrame#cardDanger {
    background: palette(base);
    border: 1px solid #E0B4B4;
    border-radius: 12px;
}

QFrame#cardOk {
    background: palette(base);
    border: 1px solid #B4DBC0;
    border-radius: 12px;
}

/* Buttons ------------------------------------------------------------ */

QPushButton {
    background: palette(button);
    border: 1px solid palette(mid);
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 18px;
}

QPushButton:hover {
    background: palette(midlight);
}

QPushButton:pressed {
    background: palette(mid);
}

QPushButton:disabled {
    color: palette(mid);
}

QPushButton#primary {
    background: #1B73B8;
    color: white;
    border: 1px solid #1B73B8;
    font-weight: 600;
}

QPushButton#primary:hover {
    background: #1A6BAA;
}

QPushButton#primary:pressed {
    background: #155B95;
}

QPushButton#danger {
    background: #C62828;
    color: white;
    border: 1px solid #C62828;
    font-weight: 600;
}

QPushButton#danger:hover { background: #B71C1C; }

QPushButton#ghost {
    background: transparent;
    border: 1px solid transparent;
}

QPushButton#ghost:hover { background: rgba(27,115,184,0.10); }

QPushButton#outline {
    background: transparent;
    border: 1px solid #1B73B8;
}

QPushButton#outline:hover {
    background: rgba(27, 115, 184, 0.10);
}

/* Progress ----------------------------------------------------------- */

QProgressBar {
    border: 1px solid palette(mid);
    border-radius: 6px;
    text-align: center;
    background: palette(base);
    min-height: 18px;
}

QProgressBar::chunk {
    background: #1B73B8;
    border-radius: 5px;
}

/* Inputs ------------------------------------------------------------- */

QLineEdit {
    background: palette(base);
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 11pt;
    selection-background-color: #1B73B8;
    min-height: 18px;
}

QLineEdit:focus {
    border: 1px solid #1B73B8;
}

QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox {
    font-size: 11pt;
    selection-background-color: #1B73B8;
    min-height: 18px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid palette(mid);
    background: palette(base);
}

QCheckBox::indicator:checked {
    background: #1B73B8;
    border: 1px solid #1B73B8;
}

/* Tables / lists ----------------------------------------------------- */

QTableWidget, QTreeWidget, QListWidget {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: palette(midlight);
}

QHeaderView::section {
    background: palette(midlight);
    padding: 6px 8px;
    border: none;
    font-weight: 600;
}

QPlainTextEdit#logView {
    background: #0E1A26;
    color: #E6F0F9;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", "Consolas", monospace;
    font-size: 10pt;
    border-radius: 8px;
    border: 1px solid #1B73B8;
    padding: 10px;
    selection-background-color: #1B73B8;
}

/* Scrollbars --------------------------------------------------------- */

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px 2px 4px 2px;
}
QScrollBar::handle:vertical {
    background: palette(mid);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #1B73B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; }
QScrollBar::handle:horizontal {
    background: palette(mid);
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #1B73B8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* Drop zone ---------------------------------------------------------- */

QFrame#dropZone {
    background: palette(base);
    border: 2px dashed palette(mid);
    border-radius: 8px;
    margin: 4px 0;
}

QFrame#dropZone[drag-over="true"] {
    border: 2px dashed #1B73B8;
    background: rgba(27, 115, 184, 0.10);
}

QLabel#dropZoneLabel {
    color: palette(mid);
    font-size: 10pt;
}

QFrame#dropZone[drag-over="true"] QLabel#dropZoneLabel {
    color: #1B73B8;
}

/* Status bar --------------------------------------------------------- */

QStatusBar {
    background: palette(window);
    border-top: 1px solid palette(midlight);
    font-size: 9pt;
    padding: 2px 8px;
    min-height: 20px;
}

QStatusBar QLabel {
    font-size: 9pt;
    color: palette(mid);
    padding: 0 6px;
}

/* Tray menu ---------------------------------------------------------- */

QMenu {
    background: palette(window);
    border: 1px solid palette(mid);
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 22px;
    border-radius: 4px;
}

QMenu::item:selected {
    background: #1B73B8;
    color: white;
}
"""
