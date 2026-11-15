"""Qt界面样式表。

将视觉样式与业务逻辑分离，main.py只负责页面和通信流程。
"""

APP_STYLE = r"""
QWidget {
    background-color: #101625;
    color: #E7ECF7;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC";
    font-size: 13px;
}
QMainWindow {
    background-color: #101625;
}
QFrame#card, QFrame#topBar, QFrame#contentCard {
    background-color: #192235;
    border: 1px solid #2A3854;
    border-radius: 18px;
}
QFrame#motorToolbar {
    background-color: #1D2940;
    border: 1px solid #34435F;
    border-radius: 12px;
}
QFrame#motorCard {
    background-color: #202C43;
    border: 1px solid #354665;
    border-radius: 12px;
}
QFrame#motorCard:hover {
    border-color: #727CBA;
    background-color: #24324B;
}
QFrame#boardCard {
    background-color: #F5F7FB;
    border: 1px solid #BCC5D3;
    border-radius: 12px;
}
QLabel#boardTitleLabel {
    background-color: transparent;
    color: #172033;
    font-size: 14px;
    font-weight: 700;
}
QLabel#boardMetaLabel {
    background-color: transparent;
    color: #4B5568;
    font-size: 10px;
}
QLabel#titleLabel {
    font-size: 26px;
    font-weight: 700;
}
QLabel#motorPageTitle {
    color: #EDF2FF;
    font-size: 21px;
    font-weight: 700;
}
QLabel#motorSectionTitle {
    color: #E7ECF7;
    font-size: 19px;
    font-weight: 700;
}
QLabel#motorSectionHint {
    color: #9EACC8;
    font-size: 12px;
}
QLabel#motorFingerLabel {
    color: #E9EEFC;
    font-size: 14px;
    font-weight: 700;
}
QLabel#motorJointBadge {
    background-color: #343E65;
    color: #D5D9FF;
    border: 1px solid #515C91;
    border-radius: 7px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#motorIdLabel {
    color: #8190AE;
    font-size: 10px;
}
QDoubleSpinBox#motorTargetValue QLineEdit {
    min-width: 0;
    padding: 0 8px;
    border: 1px solid #313D60;
    border-radius: 10px;
    background-color: #182237;
    color: #AEB8FF;
    selection-background-color: #6269A0;
    font-size: 19px;
    font-weight: 700;
}
QDoubleSpinBox#motorTargetValue QLineEdit:focus {
    border-color: #858FD5;
}
QLabel#motorTelemetryValue {
    background-color: #182237;
    border: 1px solid #303D58;
    border-radius: 7px;
    color: #B8C6E2;
    padding: 3px 1px;
    font-size: 9px;
}
QLabel#motorRangeLabel {
    background-color: transparent;
    color: #8997B2;
    font-size: 10px;
}
QLabel#motorRowHeading, QLabel#motorColumnHeading {
    background-color: transparent;
    color: #ABB7D2;
    font-size: 12px;
    font-weight: 700;
}
QLabel#motorConnectionBadge {
    background-color: #3A3442;
    color: #D8C3AC;
    border: 1px solid #655644;
    border-radius: 10px;
    padding: 7px 12px;
    font-size: 12px;
    font-weight: 700;
}
QLabel#motorConnectionBadge[connected="true"] {
    background-color: #203F39;
    color: #9FE0C5;
    border-color: #357762;
}
QLabel#motorStatusLabel {
    background-color: transparent;
    color: #AEBBD6;
    font-size: 12px;
}
QLabel#motorColumnHeading {
    padding: 4px;
}
QPushButton#motorEnableButton, QPushButton#motorCalibrateButton,
QPushButton#motorDisableButton {
    min-height: 34px;
    max-height: 38px;
    padding: 0 12px;
    border-radius: 10px;
}
QPushButton#motorEnableButton {
    background-color: #286D57;
    border-color: #388C71;
}
QPushButton#motorEnableButton:hover {
    background-color: #32836A;
}
QPushButton#motorCalibrateButton {
    background-color: #3A476A;
    border-color: #586B9B;
}
QPushButton#motorCalibrateButton:hover {
    background-color: #465780;
}
QPushButton#motorDisableButton {
    background-color: #743D4B;
    border-color: #A45262;
}
QPushButton#motorDisableButton:hover {
    background-color: #8A4959;
}
QSlider#motorSlider {
    min-height: 18px;
    background: transparent;
}
QSlider#motorSlider::groove:horizontal {
    height: 7px;
    background: #37445E;
    border: 1px solid #465675;
    border-radius: 4px;
}
QSlider#motorSlider::sub-page:horizontal {
    background: #737DC0;
    border-radius: 4px;
}
QSlider#motorSlider::handle:horizontal {
    width: 19px;
    margin: -7px 0;
    background: #E2E5FF;
    border: 2px solid #858FD5;
    border-radius: 10px;
}
QSlider#motorSlider::handle:horizontal:hover {
    background: #FFFFFF;
    border-color: #A9B0F5;
}
QSlider#motorSlider:disabled {
    opacity: 0.45;
}
QLabel#subTitleLabel {
    color: #AAB6CF;
    font-size: 14px;
}
QLabel#infoLabel {
    color: #AFC0E5;
}
QPushButton {
    min-height: 42px;
    padding: 0 22px;
    border: 1px solid #34435F;
    border-radius: 13px;
    background-color: #263248;
    color: #EDF2FF;
    font-size: 15px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #303E58;
}
QPushButton:pressed {
    background-color: #202B40;
}
QPushButton#primaryButton {
    background-color: #6269A0;
    border-color: #737BB5;
}
QPushButton#primaryButton:hover {
    background-color: #7078B3;
}
QPushButton#dangerButton {
    background-color: #5B3340;
    border-color: #794756;
}
QComboBox, QSpinBox {
    min-height: 42px;
    padding: 0 12px;
    border: 1px solid #46536C;
    border-radius: 10px;
    background-color: #293247;
    color: #F3F6FC;
    selection-background-color: #6269A0;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox QAbstractItemView {
    background-color: #293247;
    color: #F3F6FC;
    selection-background-color: #6269A0;
}
QScrollArea#boardScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea#motorScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea#motorScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QMenuBar#pageMenuBar {
    background-color: #141E30;
    color: #DCE4F8;
    border-bottom: 1px solid #2B3853;
    padding: 5px 12px;
}
QMenuBar#pageMenuBar::item {
    background-color: transparent;
    border-radius: 8px;
    padding: 8px 17px;
    font-size: 13px;
    font-weight: 600;
}
QMenuBar#pageMenuBar::item:selected {
    background-color: #303C5D;
}
QScrollArea#boardScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QTableWidget#tactileTable {
    background-color: #FFFFFF;
    color: #000000;
    border: 1px solid #8F98A7;
    border-radius: 5px;
    gridline-color: #8F98A7;
    font-size: 10px;
    font-weight: 600;
    selection-background-color: transparent;
    selection-color: #000000;
}
QTableWidget#tactileTable::item {
    color: #000000;
    padding: 0px;
    border: none;
}
QHeaderView::section {
    background-color: #E9EDF3;
    color: #111827;
    border: none;
    border-right: 1px solid #AAB2BF;
    border-bottom: 1px solid #AAB2BF;
    padding: 0px;
    font-size: 10px;
    font-weight: 700;
}
QTableCornerButton::section {
    background-color: #E9EDF3;
    border: none;
    border-right: 1px solid #AAB2BF;
    border-bottom: 1px solid #AAB2BF;
}
QLabel[class="statusBadge"] {
    background-color: #EEE6E9;
    color: #7A4455;
    border: 1px solid #CDAFBA;
    border-radius: 8px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 700;
}
QLabel[class="statusBadge"][online="true"] {
    background-color: #DDF2E9;
    color: #23654F;
    border-color: #8AC6B0;
}
QLabel[class="statusBadge"][waiting="true"] {
    background-color: #E8EDF7;
    color: #4A5F89;
    border-color: #AAB9D7;
}
QLabel#footerLabel {
    background-color: #121B2C;
    border: 1px solid #2A3854;
    border-radius: 12px;
    color: #9DB2DE;
    padding: 9px 13px;
}
QDialog {
    background-color: #151D2E;
}
QDialogButtonBox QPushButton {
    min-width: 90px;
}
"""
