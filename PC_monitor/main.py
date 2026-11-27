from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from time import monotonic

from PySide6.QtCore import QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from protocol import TactileFrame
from motor_control import MotorControlPage
from motor_protocol import (
    COMMAND_DISABLE,
    COMMAND_IMPEDANCE_POSITION,
    MOTOR_COUNT,
    build_motor_command,
)
from serial_worker import SerialReader
from styles import APP_STYLE
from widgets import ADC_MAX, BoardPanel


# 传感板ID与底层轮询配置保持一致：0x00～0x0B。
BOARD_IDS = tuple(range(12))
SERIAL_BAUDRATE = 460800



class ConnectionPage(QWidget):
    connect_requested = Signal(str)

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.addStretch(1)

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(520)
        card.setMinimumHeight(490)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 32, 34, 32)
        card_layout.setSpacing(18)

        title = QLabel("设备连接")
        title.setObjectName("titleLabel")

        subtitle = QLabel(
            "选择STM32 USB虚拟串口。"
        )
        subtitle.setObjectName("subTitleLabel")
        subtitle.setWordWrap(True)

        serial_label = QLabel("串口（COM）")
        serial_label.setObjectName("infoLabel")

        serial_row = QHBoxLayout()
        serial_row.setSpacing(10)

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setFixedWidth(120)
        self.refresh_button.clicked.connect(self.refresh_ports)

        serial_row.addWidget(self.port_combo, 1)
        serial_row.addWidget(self.refresh_button)

        self.connect_button = QPushButton("连接")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._request_connect)

        self.status_label = QLabel("请选择串口")
        self.status_label.setObjectName("subTitleLabel")
        self.status_label.setAlignment(Qt.AlignCenter)

        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(8)
        card_layout.addWidget(serial_label)
        card_layout.addLayout(serial_row)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.connect_button)
        card_layout.addWidget(self.status_label)
        card_layout.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)
        center_row.addWidget(card)
        center_row.addStretch(1)

        root.addLayout(center_row)
        root.addStretch(1)

        self.refresh_ports()

    def current_port(self) -> str:
        value = self.port_combo.currentData()
        return str(value) if value else ""

    def refresh_ports(self) -> None:
        previous_port = self.current_port() or str(
            self._settings.value("last_port", "")
        )

        ports = sorted(
            list_ports.comports(),
            key=lambda item: item.device,
        )

        self.port_combo.clear()

        for port in ports:
            description = port.description or "串口设备"
            self.port_combo.addItem(
                f"{port.device}  —  {description}",
                port.device,
            )

        if previous_port:
            for index in range(self.port_combo.count()):
                if self.port_combo.itemData(index) == previous_port:
                    self.port_combo.setCurrentIndex(index)
                    break

        if ports:
            self.status_label.setText(f"发现 {len(ports)} 个串口")
        else:
            self.status_label.setText("未发现串口，请连接设备后刷新")

    def set_connecting(self, connecting: bool) -> None:
        self.connect_button.setEnabled(not connecting)
        self.refresh_button.setEnabled(not connecting)
        self.port_combo.setEnabled(not connecting)
        self.status_label.setText(
            "正在打开串口……" if connecting else "请选择串口"
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _request_connect(self) -> None:
        port = self.current_port()
        if not port:
            QMessageBox.warning(self, "未选择串口", "请先选择一个COM端口。")
            return
        self.connect_requested.emit(port)


class OffsetDialog(QDialog):
    def __init__(self, current_offset: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 ADC 固定减少值")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        explanation = QLabel(
            "校准公式：显示值 = max(0, ADC原始值 − Offset)\n"
            "该Offset同时应用于所有6×6传感板。"
        )
        explanation.setObjectName("subTitleLabel")
        explanation.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(14)

        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(0, ADC_MAX)
        self.offset_spin.setValue(current_offset)
        self.offset_spin.setSuffix(" ADC")

        form.addRow("6×6 Offset", self.offset_spin)

        range_label = QLabel("建议范围：0～4095（0表示不减少）")
        range_label.setObjectName("subTitleLabel")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root.addWidget(explanation)
        root.addLayout(form)
        root.addWidget(range_label)
        root.addWidget(buttons)

    def offset(self) -> int:
        return self.offset_spin.value()


class MonitorPage(QWidget):
    back_requested = Signal()
    settings_requested = Signal()
    connection_toggle_requested = Signal()

    GRID_COLUMNS = 4

    def __init__(self, board_ids: tuple[int, ...], parent=None) -> None:
        super().__init__(parent)
        self._connected = False
        self._port = ""
        self._board_panels: dict[int, BoardPanel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(10)

        self.back_button = QPushButton("返回")
        self.back_button.clicked.connect(self.back_requested)

        type_label = QLabel("类型：12 × 6×6")
        unit_label = QLabel("单位：ADC")
        for label in (type_label, unit_label):
            label.setObjectName("infoLabel")

        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self.settings_requested)

        self.connection_button = QPushButton("断开连接")
        self.connection_button.clicked.connect(
            self.connection_toggle_requested
        )

        self.time_label = QLabel()
        self.time_label.setObjectName("infoLabel")
        self.time_label.setMinimumWidth(170)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        top_layout.addWidget(self.back_button)
        top_layout.addSpacing(6)
        top_layout.addWidget(type_label)
        top_layout.addWidget(unit_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.settings_button)
        top_layout.addWidget(self.connection_button)
        top_layout.addWidget(self.time_label)

        content = QFrame()
        content.setObjectName("contentCard")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("boardScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        board_container = QWidget()
        board_grid = QGridLayout(board_container)
        board_grid.setContentsMargins(2, 2, 2, 2)
        board_grid.setHorizontalSpacing(10)
        board_grid.setVerticalSpacing(10)

        for column in range(self.GRID_COLUMNS):
            board_grid.setColumnStretch(column, 1)

        for index, board_id in enumerate(board_ids):
            panel = BoardPanel(board_id)
            self._board_panels[board_id] = panel

            row = index // self.GRID_COLUMNS
            column = index % self.GRID_COLUMNS
            board_grid.addWidget(panel, row, column)

        row_count = (
            len(board_ids) + self.GRID_COLUMNS - 1
        ) // self.GRID_COLUMNS
        for row in range(row_count):
            board_grid.setRowStretch(row, 1)

        self.scroll_area.setWidget(board_container)
        content_layout.addWidget(self.scroll_area)

        self.footer_label = QLabel(
            "等待连接 | 有效帧：0 | 校验错误：0 | 丢弃字节：0"
        )
        self.footer_label.setObjectName("footerLabel")

        root.addWidget(top_bar)
        root.addWidget(content, 1)
        root.addWidget(self.footer_label)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def set_connected(self, connected: bool, port: str) -> None:
        self._connected = connected
        self._port = port

        self.connection_button.setText(
            "断开连接" if connected else "连接"
        )
        self.connection_button.setObjectName(
            "dangerButton" if connected else "primaryButton"
        )
        self.connection_button.style().unpolish(self.connection_button)
        self.connection_button.style().polish(self.connection_button)

        for panel in self._board_panels.values():
            if connected:
                panel.mark_waiting()
            else:
                panel.mark_disconnected()

    def update_frame(self, frame: TactileFrame, offset: int) -> bool:
        panel = self._board_panels.get(frame.board_id)
        if panel is None:
            return False
        panel.update_frame(frame, offset)
        return True

    def set_offset(self, offset: int) -> None:
        for panel in self._board_panels.values():
            panel.set_offset(offset)

    def update_statistics(
        self,
        valid_frames: int,
        checksum_errors: int,
        discarded_bytes: int,
    ) -> None:
        port_text = self._port if self._port else "--"
        state_text = "已连接" if self._connected else "已断开"
        self.footer_label.setText(
            f"{state_text}：{port_text}  |  "
            f"有效帧：{valid_frames}  |  "
            f"校验错误：{checksum_errors}  |  "
            f"丢弃字节：{discarded_bytes}"
        )

    def set_footer_message(self, message: str) -> None:
        self.footer_label.setText(message)

    def _update_clock(self) -> None:
        self.time_label.setText(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("多传感器触觉监控")
        # 4列×3行布局在1600×950附近可同时完整展示12块传感板。
        # 小屏幕下会自动出现滚动条，避免表格被压缩到不可读。
        self.resize(1680, 980)
        self.setMinimumSize(1180, 760)

        self.settings = QSettings("SimpleHand", "TactileMonitor")
        self.offset = int(self.settings.value("adc_offset", 0))
        self.selected_port = str(self.settings.value("last_port", ""))

        self.serial_worker: SerialReader | None = None
        self.connected = False
        self._show_monitor_after_open = False
        self._statistics = (0, 0, 0)
        self._motor_sequence = 0
        self._pending_motor_acks: dict[
            tuple[int, int],
            tuple[Callable[[object], None], float],
        ] = {}
        self._shutdown_guard_timer = QTimer(self)
        self._shutdown_guard_timer.setSingleShot(True)
        self._shutdown_guard_timer.timeout.connect(self._finish_shutdown)
        self._shutdown_pending = False
        self._close_after_shutdown = False
        self._serial_error_message = ""
        self._serial_error_dialog: QMessageBox | None = None

        self.pages = QStackedWidget()
        self.connection_page = ConnectionPage(self.settings)
        self.monitor_page = MonitorPage(BOARD_IDS)
        self.motor_page = MotorControlPage(
            self.send_motor_command,
            send_position_round=self.send_motor_position_round,
            send_disable_poll=self.send_motor_disable_poll,
            cancel_disable_polls=self.cancel_motor_disable_polls,
        )

        self.pages.addWidget(self.connection_page)
        self.pages.addWidget(self.monitor_page)
        self.pages.addWidget(self.motor_page)
        self.setCentralWidget(self.pages)

        menu_bar = QMenuBar(self)
        menu_bar.setObjectName("pageMenuBar")
        menu_bar.setNativeMenuBar(False)
        self._tactile_action = menu_bar.addAction("触觉传感", self.show_tactile_page)
        self._motor_action = menu_bar.addAction("电机控制", self.show_motor_page)
        self.setMenuBar(menu_bar)
        self.pages.currentChanged.connect(self._update_page_actions)
        self._update_page_actions()

        self.connection_page.connect_requested.connect(
            lambda port: self.start_serial(port, show_monitor=True)
        )
        self.monitor_page.back_requested.connect(self.return_to_connection)
        self.monitor_page.settings_requested.connect(self.open_settings)
        self.monitor_page.connection_toggle_requested.connect(
            self.toggle_connection
        )
        self.motor_page.connection_toggle_requested.connect(
            self.toggle_connection
        )

        self.monitor_page.set_offset(self.offset)

    def start_serial(self, port: str, show_monitor: bool) -> None:
        if self.serial_worker is not None or self._shutdown_pending:
            return

        self.selected_port = port
        self._show_monitor_after_open = show_monitor
        self.connection_page.set_connecting(True)

        worker = SerialReader(port, SERIAL_BAUDRATE, self)
        worker.opened.connect(self._on_serial_opened)
        worker.closed.connect(self._on_serial_closed)
        worker.error_occurred.connect(self._on_serial_error)
        worker.finished.connect(self._on_serial_worker_finished)
        worker.frame_received.connect(self._on_frame)
        worker.motor_response_received.connect(self._on_motor_response)
        worker.statistics_changed.connect(self._on_statistics_changed)

        self.serial_worker = worker
        worker.start()

    def stop_serial(self) -> None:
        worker = self.serial_worker
        if worker is None:
            self.connected = False
            self.monitor_page.set_connected(False, self.selected_port)
            self.motor_page.set_connected(False)
            return

        # Stop GUI timers first, then request a safe stop for all boards before closing CDC.
        self.motor_page.set_connected(False)
        self._shutdown_pending = True
        self.connection_page.set_connecting(True)

        if self.connected and worker.isRunning():
            sequence = self._motor_sequence
            self._motor_sequence = (self._motor_sequence + 1) & 0xFF
            frame = build_motor_command(
                0xFF,
                COMMAND_DISABLE,
                0.0,
                sequence,
            )
            if worker.enqueue_write(frame):
                self._shutdown_guard_timer.start(120)
                return

        self._finish_shutdown()

    def _finish_shutdown(self) -> None:
        if not self._shutdown_pending:
            return

        self._shutdown_guard_timer.stop()
        worker = self.serial_worker
        if worker is not None:
            worker.stop()
            if worker.isRunning():
                return
            self._complete_serial_worker_shutdown(worker)
            return

        self._shutdown_pending = False
        self.connected = False
        self._pending_motor_acks.clear()
        self.monitor_page.set_connected(False, self.selected_port)
        self.motor_page.set_connected(False)
        self.connection_page.set_connecting(False)
        if self._close_after_shutdown:
            self._close_after_shutdown = False
            QTimer.singleShot(0, self.close)

    @Slot()
    def _on_serial_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            self._complete_serial_worker_shutdown(worker)

    def _complete_serial_worker_shutdown(self, worker: SerialReader) -> None:
        if self.serial_worker is not worker:
            return
        self.serial_worker = None
        worker.deleteLater()
        self._shutdown_pending = False
        self.connected = False
        self._pending_motor_acks.clear()
        self.monitor_page.set_connected(False, self.selected_port)
        self.motor_page.set_connected(False)
        self.connection_page.set_connecting(False)
        if self._serial_error_message:
            self.connection_page.set_status(self._serial_error_message)
        elif not self._close_after_shutdown:
            self.connection_page.set_status("请选择串口")
        if self._close_after_shutdown:
            self._close_after_shutdown = False
            QTimer.singleShot(0, self.close)

    def toggle_connection(self) -> None:
        if self.connected:
            self.stop_serial()
            self.monitor_page.set_footer_message(
                f"已断开：{self.selected_port}。点击“连接”可重新打开串口。"
            )
        else:
            if not self.selected_port:
                self.pages.setCurrentWidget(self.connection_page)
                self.connection_page.refresh_ports()
                self.connection_page.set_status("请选择COM端口后连接")
                return
            self.start_serial(self.selected_port, show_monitor=False)

    def return_to_connection(self) -> None:
        self.stop_serial()
        self.pages.setCurrentWidget(self.connection_page)
        self.connection_page.refresh_ports()
        self.connection_page.set_status("已断开，请选择串口")

    def open_settings(self) -> None:
        dialog = OffsetDialog(self.offset, self)
        if dialog.exec() == QDialog.Accepted:
            self.offset = dialog.offset()
            self.settings.setValue("adc_offset", self.offset)
            self.monitor_page.set_offset(self.offset)
            self.monitor_page.set_footer_message(
                f"已应用全局ADC减少值：{self.offset}"
            )

    def _on_serial_opened(self, port: str) -> None:
        if self._shutdown_pending or self.serial_worker is None:
            return
        self.connected = True
        self.selected_port = port
        self._serial_error_message = ""
        if self._serial_error_dialog is not None:
            self._serial_error_dialog.close()
            self._serial_error_dialog = None
        self.settings.setValue("last_port", port)

        self.connection_page.set_connecting(False)
        self.connection_page.set_status(f"{port} 连接成功")
        self.monitor_page.set_connected(True, port)
        self.motor_page.set_connected(True)
        self.monitor_page.update_statistics(*self._statistics)

        if self._show_monitor_after_open:
            self.pages.setCurrentWidget(self.monitor_page)

    def _on_serial_closed(self) -> None:
        self.connected = False
        self._pending_motor_acks.clear()
        self.monitor_page.set_connected(False, self.selected_port)
        self.motor_page.set_connected(False)

    def _on_serial_error(self, message: str) -> None:
        self.connected = False
        self._serial_error_message = message.replace("\n", " ")
        self._pending_motor_acks.clear()
        if self.serial_worker is None:
            self.connection_page.set_connecting(False)
            self.connection_page.set_status(self._serial_error_message)
        else:
            self.connection_page.set_connecting(True)
            self.connection_page.set_status("通信错误，正在释放串口…")
        self.monitor_page.set_connected(False, self.selected_port)
        self.monitor_page.set_footer_message(self._serial_error_message)
        self.motor_page.set_connected(False)
        if self._serial_error_dialog is not None:
            self._serial_error_dialog.close()
        dialog = QMessageBox(
            QMessageBox.Critical,
            "串口错误",
            message,
            QMessageBox.Ok,
            self,
        )
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._serial_error_dialog = dialog
        dialog.finished.connect(
            lambda _result, current=dialog:
            self._clear_serial_error_dialog(current)
        )
        dialog.show()

    def _clear_serial_error_dialog(self, dialog: QMessageBox) -> None:
        if self._serial_error_dialog is dialog:
            self._serial_error_dialog = None

    def show_tactile_page(self) -> None:
        self.pages.setCurrentWidget(self.monitor_page)

    def show_motor_page(self) -> None:
        self.pages.setCurrentWidget(self.motor_page)

    def _update_page_actions(self, _index: int = -1) -> None:
        current_page = self.pages.currentWidget()
        self._tactile_action.setEnabled(current_page is not self.monitor_page)
        self._motor_action.setEnabled(current_page is not self.motor_page)

    def send_motor_command(
        self,
        motor_id: int,
        command: int,
        value: float,
        on_response: Callable[[object], None] | None = None,
    ) -> bool:
        return self._enqueue_motor_command(
            motor_id, command, value, on_response, disable_poll=False
        )

    def send_motor_disable_poll(
        self,
        motor_id: int,
        command: int,
        value: float,
        on_response: Callable[[object], None] | None = None,
    ) -> bool:
        if command != COMMAND_DISABLE or motor_id == 0xFF:
            return False
        return self._enqueue_motor_command(
            motor_id, command, value, on_response, disable_poll=True
        )

    def cancel_motor_disable_polls(self) -> None:
        if self.serial_worker is not None:
            self.serial_worker.cancel_motor_disable_polls()

    def _enqueue_motor_command(
        self,
        motor_id: int,
        command: int,
        value: float,
        on_response: Callable[[object], None] | None,
        *,
        disable_poll: bool,
    ) -> bool:
        worker = self.serial_worker
        if not self.connected or worker is None or not worker.isRunning():
            return False

        self._pending_motor_acks = {
            key: ack
            for key, ack in self._pending_motor_acks.items()
            if monotonic() <= ack[1]
        }
        sequence = self._motor_sequence
        self._motor_sequence = (self._motor_sequence + 1) & 0xFF
        frame = build_motor_command(motor_id, command, value, sequence)
        if motor_id == 0xFF:
            return (
                on_response is None
                and command == COMMAND_DISABLE
                and worker.enqueue_write(frame)
            )

        response_key = (motor_id, sequence)
        if on_response is not None:
            self._pending_motor_acks[response_key] = (
                on_response,
                monotonic() + 3.0,
            )
        if disable_poll:
            queued = worker.enqueue_motor_disable_poll(frame, motor_id, sequence)
        else:
            queued = worker.enqueue_motor_command(frame, motor_id, sequence)
        if not queued and on_response is not None:
            self._pending_motor_acks.pop(response_key, None)
        return queued

    def send_motor_position_round(self, targets: tuple[float, ...]) -> bool:
        worker = self.serial_worker
        if (
            not self.connected
            or worker is None
            or not worker.isRunning()
            or len(targets) != MOTOR_COUNT
        ):
            return False

        frames = bytearray()
        expected_responses: list[tuple[int, int]] = []
        for motor_id, target in enumerate(targets):
            sequence = self._motor_sequence
            self._motor_sequence = (self._motor_sequence + 1) & 0xFF
            frames.extend(
                build_motor_command(
                    motor_id,
                    COMMAND_IMPEDANCE_POSITION,
                    target,
                    sequence,
                )
            )
            expected_responses.append((motor_id, sequence))

        return worker.enqueue_motor_batch(
            bytes(frames),
            tuple(expected_responses),
        )

    def _on_motor_response(self, response: object) -> None:
        sequence = getattr(response, "sequence", None)
        motor_id = getattr(response, "motor_id", None)
        status = getattr(response, "status", None)
        if not isinstance(sequence, int) or not isinstance(motor_id, int):
            return

        # Every validated reply updates live telemetry, but control workflows
        # advance only through the callback for this exact pending request.
        self.motor_page.handle_motor_response(response)
        pending = self._pending_motor_acks.pop((motor_id, sequence), None)
        if pending is None:
            return

        callback, expires_at = pending
        # Only callbacks registered for this exact ID and sequence affect control flow.
        if monotonic() <= expires_at and isinstance(status, int):
            callback(response)

    def _on_frame(self, frame: TactileFrame) -> None:
        accepted = self.monitor_page.update_frame(frame, self.offset)
        if not accepted:
            self.monitor_page.set_footer_message(
                f"收到未配置的传感板ID：{frame.board_id}。"
                f"当前BOARD_IDS={BOARD_IDS}"
            )

    def _on_statistics_changed(
        self,
        valid_frames: int,
        checksum_errors: int,
        discarded_bytes: int,
    ) -> None:
        self._statistics = (
            valid_frames,
            checksum_errors,
            discarded_bytes,
        )
        self.monitor_page.update_statistics(*self._statistics)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.serial_worker is not None:
            # Keep the event loop alive while the queued broadcast DISABLE is
            # written and the serial-owning thread closes its port. Closing
            # the last window immediately would cancel the shutdown timer and
            # could destroy a still-running QThread.
            self._close_after_shutdown = True
            if not self._shutdown_pending:
                self.stop_serial()
            event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TactileMonitor")
    app.setOrganizationName("SimpleHand")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Microsoft YaHei", 10))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
