APP_QSS = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QWidget {
    color: #e6e8ec;
    font-size: 13px;
}
QMainWindow, QWidget#Root, QWidget#TabPage {
    background: #0f131a;
}
QLabel {
    background: transparent;
}
QLabel#AppTitle {
    font-size: 22px;
    font-weight: 700;
    color: #f0eee8;
    letter-spacing: 0.5px;
}
QLabel#AppSubtitle {
    color: #8d97a8;
    font-size: 12px;
}
QLabel#PageTitle {
    font-size: 17px;
    font-weight: 600;
    color: #f0eee8;
}
QLabel#CardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #d8dce4;
}
QLabel#Muted {
    color: #8d97a8;
    font-size: 12px;
}
QLabel#Hint {
    color: #75808f;
    font-size: 11px;
}
QLabel#BigTimer {
    font-size: 34px;
    font-weight: 700;
    color: #e6e8ec;
}
QLabel#StateLabel {
    font-size: 14px;
    font-weight: 600;
    color: #c9a86a;
}
QLabel#NextHint {
    color: #c9a86a;
    font-size: 13px;
}
QLabel#Ticker {
    color: #9aa4b4;
    font-size: 12px;
}
QLabel#ScoreValue {
    font-size: 32px;
    font-weight: 700;
    color: #c9a86a;
}
QLabel#MetricValue {
    font-size: 20px;
    font-weight: 600;
    color: #e6e8ec;
}
QLabel#MetricTitle {
    color: #8d97a8;
    font-size: 11px;
}
QLabel#WarnText {
    color: #e06a72;
    font-size: 12px;
}
QLabel#OkText {
    color: #57c38a;
    font-size: 12px;
}
QFrame#Card {
    background: #171d26;
    border: 1px solid #28313f;
    border-radius: 12px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QWidget#SkillGrid {
    background: transparent;
}
QFrame#MetricCard {
    background: #141a22;
    border: 1px solid #28313f;
    border-radius: 10px;
}
QFrame#HeaderBar {
    background: #131922;
    border-bottom: 1px solid #252e3b;
}
QFrame#Divider {
    background: #252e3b;
    max-height: 1px;
    min-height: 1px;
}
QPushButton {
    background: #202836;
    border: 1px solid #303b4c;
    border-radius: 8px;
    padding: 8px 14px;
    color: #dfe3ea;
}
QPushButton:hover {
    background: #263042;
    border-color: #3b495e;
}
QPushButton:pressed {
    background: #1b2230;
}
QPushButton:disabled {
    color: #5d6676;
    background: #181e28;
    border-color: #252e3b;
}
QPushButton#Primary {
    background: #c9a86a;
    border: 1px solid #c9a86a;
    color: #1a1a1a;
    font-weight: 700;
    padding: 10px 16px;
}
QPushButton#Primary:hover {
    background: #d9b87a;
}
QPushButton#Primary:disabled {
    background: #4a4231;
    border-color: #4a4231;
    color: #8f8262;
}
QPushButton#Ghost {
    background: transparent;
    border: 1px solid #303b4c;
    color: #b6c0cf;
}
QPushButton#Ghost:hover {
    background: #1d2531;
}
QPushButton#Small {
    padding: 4px 10px;
    font-size: 12px;
    border-radius: 6px;
}
QPushButton#Danger {
    background: transparent;
    border: 1px solid #5c2e34;
    color: #e08a90;
}
QPushButton#Danger:hover {
    background: #2a1a1f;
}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #11161f;
    border: 1px solid #2c3644;
    border-radius: 7px;
    padding: 6px 8px;
    color: #e6e8ec;
    min-height: 20px;
    selection-background-color: #33475f;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
    border-color: #3c4a5e;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #6b7484;
    background: #151a23;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #151b24;
    border: 1px solid #2c3644;
    selection-background-color: #2a3648;
    selection-color: #f0eee8;
    outline: none;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #1c2430;
    border-left: 1px solid #2c3644;
    width: 18px;
}
QCheckBox {
    spacing: 8px;
    color: #cfd6e0;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3a4658;
    background: #11161f;
}
QCheckBox::indicator:checked {
    background: #c9a86a;
    border-color: #c9a86a;
}
QProgressBar {
    background: #11161f;
    border: 1px solid #28313f;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #c9a86a;
    border-radius: 6px;
}
QProgressBar#GaugeBar {
    background: #0d1119;
    border: 1px solid #2b3444;
    border-radius: 5px;
    height: 15px;
    color: #c8d0dc;
    font-size: 11px;
}
QProgressBar#GaugeBar::chunk {
    background: #c9a86a;
    border-radius: 4px;
}
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar {
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: #8d97a8;
    padding: 9px 18px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}
QTabBar::tab:hover {
    color: #c6ceda;
}
QTabBar::tab:selected {
    color: #f0eee8;
    border-bottom: 2px solid #c9a86a;
}
QTabBar::tab:disabled {
    color: #4d5665;
}
QTableWidget {
    background: #121821;
    alternate-background-color: #151c26;
    gridline-color: #232c39;
    border: 1px solid #28313f;
    border-radius: 8px;
    selection-background-color: #2a3648;
    selection-color: #f0eee8;
    outline: none;
}
QTableWidget::item {
    padding: 5px;
}
QHeaderView::section {
    background: #182029;
    color: #9aa4b4;
    border: none;
    border-right: 1px solid #232c39;
    border-bottom: 1px solid #232c39;
    padding: 7px 6px;
    font-size: 12px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #182029;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2c3644;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3c4a5e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2c3644;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
    width: 0;
}
QMenu {
    background: #161d27;
    border: 1px solid #2c3644;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    background: transparent;
    color: #dfe3ea;
    padding: 6px 20px 6px 14px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #2a3648;
    color: #f0eee8;
}
QMenu::item:disabled {
    color: #5d6676;
}
QMenu::separator {
    height: 1px;
    background: #2c3644;
    margin: 4px 8px;
}
QMessageBox, QInputDialog, QDialog {
    background: #141a22;
}
QMessageBox QLabel, QMessageBox QLabel#qt_msgbox_label, QInputDialog QLabel {
    color: #e6e8ec;
}
QMessageBox QPushButton {
    min-width: 76px;
}
QToolTip {
    background: #1b2330;
    color: #e6e8ec;
    border: 1px solid #39465a;
    padding: 5px 8px;
}
QTextBrowser {
    background: #121821;
    border: 1px solid #28313f;
    border-radius: 8px;
    padding: 8px;
    color: #cfd6e0;
}
QSplitter::handle {
    background: transparent;
}
"""
