"""Motor controls and command scheduling for the desktop monitor."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QAbstractSpinBox,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from motor_protocol import (
    COMMAND_CALIBRATE_ZERO,
    COMMAND_DISABLE,
    COMMAND_ENABLE,
    COMMAND_IMPEDANCE_POSITION,
    MOTOR_COUNT,
    STATUS_ZERO_VALID,
    MotorResponse,
)


MOTOR_ROW_NAMES = ("\u62c7\u6307", "\u98df\u6307", "\u4e2d\u6307", "\u65e0\u540d\u6307")
THUMB_JOINT_NAMES = ("CMC_FE", "CMC_Rotation", "MCP_FE", "PIP_FE", "DIP_FE")
FINGER_JOINT_NAMES = ("MCP_AA", "MCP_FE", "PIP_FE", "DIP_FE")
MOTOR_JOINT_NAMES = (THUMB_JOINT_NAMES,) + (FINGER_JOINT_NAMES,) * 3
MOTOR_LAYOUT = tuple(
    (finger, joint)
    for finger, joints in zip(MOTOR_ROW_NAMES, MOTOR_JOINT_NAMES)
    for joint in joints
)
ANGLE_SLIDER_SCALE = 10
POSITION_ROUND_INTERVAL_MS = 50
COMMAND_SLOT_INTERVAL_MS = 3
ENABLE_SETTLE_MS = 100
CALIBRATION_SETTLE_MS = 100
CALIBRATION_SWITCH_MS = 50
DISABLE_ROUND_INTERVAL_MS = 50
CALIBRATION_TIMEOUT_MS = 350

SendMotorCommand = Callable[
    [int, int, float, Callable[[MotorResponse], None] | None],
    bool,
]
SendPositionRound = Callable[[tuple[float, ...]], bool]


class MotorCard(QFrame):
    """One motor's target angle and bounded slider."""

    target_changed = Signal(int, float)

    def __init__(self, motor_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.motor_id = motor_id
        self.setObjectName("motorCard")
        self.setMinimumWidth(0)

        if not 0 <= motor_id < len(MOTOR_LAYOUT):
            raise ValueError("invalid motor ID")
        finger_name, joint_name = MOTOR_LAYOUT[motor_id]
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 9)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        finger_label = QLabel(finger_name)
        finger_label.setObjectName("motorFingerLabel")
        joint_label = QLabel(joint_name)
        joint_label.setObjectName("motorJointBadge")
        id_label = QLabel(f"ID {motor_id:02d}")
        id_label.setObjectName("motorIdLabel")
        title_row.addWidget(finger_label)
        title_row.addWidget(joint_label)
        title_row.addStretch(1)
        title_row.addWidget(id_label)

        self.target_input = QDoubleSpinBox()
        self.target_input.setObjectName("motorTargetValue")
        self.target_input.setRange(-180.0, 180.0)
        self.target_input.setDecimals(1)
        self.target_input.setSingleStep(0.1)
        self.target_input.setSuffix(" \u00b0")
        self.target_input.setValue(0.0)
        self.target_input.setAlignment(Qt.AlignCenter)
        self.target_input.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.target_input.setMinimumWidth(0)
        self.target_input.setMinimumHeight(36)
        self.target_input.setKeyboardTracking(False)
        self.target_input.setAccessibleName(
            f"\u7535\u673a {motor_id} \u76ee\u6807\u89d2\u5ea6\u8f93\u5165"
        )
        self.value_label = self.target_input

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName("motorSlider")
        self.slider.setRange(
            -180 * ANGLE_SLIDER_SCALE,
            180 * ANGLE_SLIDER_SCALE,
        )
        self.slider.setValue(0)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(10 * ANGLE_SLIDER_SCALE)
        self.slider.setTracking(True)
        self.slider.setAccessibleName(
            f"\u7535\u673a {motor_id} \u76ee\u6807\u89d2\u5ea6"
        )
        self.slider.setToolTip(
            "\u8bbe\u7f6e\u76ee\u6807\u89d2\u5ea6\uff1a"
            "-180\u00b0 \u81f3 +180\u00b0"
        )
        self.slider.valueChanged.connect(self._on_value_changed)
        self.target_input.valueChanged.connect(self._on_target_input_changed)

        telemetry_row = QHBoxLayout()
        telemetry_row.setSpacing(4)
        self.actual_angle_label = QLabel("\u5b9e\u9645 \u2014\u2014")
        self.actual_angle_label.setObjectName("motorTelemetryValue")
        self.bus_voltage_label = QLabel("\u6bcd\u7ebf \u2014\u2014 V")
        self.bus_voltage_label.setObjectName("motorTelemetryValue")
        self.temperature_label = QLabel("\u6e29\u5ea6 \u2014\u2014 \u00b0C")
        self.temperature_label.setObjectName("motorTelemetryValue")
        for label in (
            self.actual_angle_label,
            self.bus_voltage_label,
            self.temperature_label,
        ):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(0)
            telemetry_row.addWidget(label, 1)

        scale_row = QHBoxLayout()
        minimum_label = QLabel("-180\u00b0")
        maximum_label = QLabel("+180\u00b0")
        minimum_label.setObjectName("motorRangeLabel")
        maximum_label.setObjectName("motorRangeLabel")
        scale_row.addWidget(minimum_label)
        scale_row.addStretch(1)
        scale_row.addWidget(maximum_label)

        root.addLayout(title_row)
        root.addWidget(self.target_input)
        root.addWidget(self.slider)
        root.addLayout(scale_row)
        root.addLayout(telemetry_row)

    def target_degrees(self) -> float:
        return self.slider.value() / ANGLE_SLIDER_SCALE

    def update_telemetry(self, response: MotorResponse) -> None:
        self.actual_angle_label.setText(
            f"\u5b9e\u9645 {response.position_degrees:+.2f}\u00b0"
        )
        self.bus_voltage_label.setText(
            f"\u6bcd\u7ebf {response.bus_voltage:.2f} V"
        )
        self.temperature_label.setText(
            f"\u6e29\u5ea6 {response.temperature:.1f} \u00b0C"
        )

    def _on_value_changed(self, value: int) -> None:
        self.target_input.setValue(value / ANGLE_SLIDER_SCALE)

    def _on_target_input_changed(self, value: float) -> None:
        slider_value = round(value * ANGLE_SLIDER_SCALE)
        if self.slider.value() != slider_value:
            self.slider.setValue(slider_value)
        self.target_changed.emit(self.motor_id, value)


class MotorControlPage(QWidget):
    """Four finger rows with paced bulk commands and 20 Hz target rounds."""

    connection_toggle_requested = Signal()

    def __init__(
        self,
        send_command: SendMotorCommand,
        parent: QWidget | None = None,
        *,
        send_position_round: SendPositionRound | None = None,
        send_disable_poll: SendMotorCommand | None = None,
        cancel_disable_polls: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._send_command = send_command
        self._send_position_round = send_position_round
        self._send_disable_poll = send_disable_poll or send_command
        self._cancel_disable_polls = cancel_disable_polls
        self._disable_poll_error = False
        self._connected = False
        self._enabled = False
        self._enable_settle_pending = False
        self._disable_settle_pending = False

        self._sweep_kind: str | None = None
        self._sweep_ids: list[int] = []
        self._sweep_index = 0
        self._sweep_value = 0.0

        self._position_round_active = False
        self._position_index = 0
        self._motor_cards: list[MotorCard] = []
        self._last_motor_response_at: dict[int, float] = {}

        self._calibration_stage: str | None = None
        self._calibration_generation = 0
        self._calibration_command_replies: set[int] = set()
        self._calibration_success: set[int] = set()
        self._disable_polling = False
        self._disable_round_index: int | None = None

        self._slot_timer = QTimer(self)
        self._slot_timer.setSingleShot(True)
        self._slot_timer.setTimerType(Qt.PreciseTimer)
        self._slot_timer.timeout.connect(self._on_slot_timer)

        self._position_slot_timer = QTimer(self)
        self._position_slot_timer.setSingleShot(True)
        self._position_slot_timer.setTimerType(Qt.PreciseTimer)
        self._position_slot_timer.timeout.connect(self._send_next_position)

        self._round_timer = QTimer(self)
        self._round_timer.setTimerType(Qt.PreciseTimer)
        self._round_timer.setInterval(POSITION_ROUND_INTERVAL_MS)
        self._round_timer.timeout.connect(self._start_position_round)

        self._stage_timer = QTimer(self)
        self._stage_timer.setSingleShot(True)
        self._stage_timer.setTimerType(Qt.PreciseTimer)
        self._stage_timer.timeout.connect(self._on_stage_timeout)

        self._calibration_timeout_timer = QTimer(self)
        self._calibration_timeout_timer.setSingleShot(True)
        self._calibration_timeout_timer.timeout.connect(
            self._on_calibration_timeout
        )

        self._disable_poll_timer = QTimer(self)
        self._disable_poll_timer.setSingleShot(True)
        self._disable_poll_timer.setTimerType(Qt.PreciseTimer)
        self._disable_poll_timer.timeout.connect(self._on_disable_poll_timer)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(8)

        page_title = QLabel("\u7535\u673a\u63a7\u5236")
        page_title.setObjectName("motorPageTitle")
        self.connection_label = QLabel("\u4e32\u53e3\u672a\u8fde\u63a5")
        self.connection_label.setObjectName("motorConnectionBadge")
        self.connection_button = QPushButton("\u8fde\u63a5\u4e32\u53e3")
        self.connection_button.clicked.connect(
            self.connection_toggle_requested.emit
        )
        self.enable_button = QPushButton("\u4f7f\u80fd\u5168\u90e8\u7535\u673a")
        self.enable_button.setObjectName("motorEnableButton")
        self.enable_button.clicked.connect(self._toggle_enabled)
        self.calibrate_button = QPushButton(
            "\u6807\u5b9a\u5168\u90e8\u7535\u673a\u96f6\u70b9"
        )
        self.calibrate_button.setObjectName("motorCalibrateButton")
        self.calibrate_button.clicked.connect(self._confirm_calibration)
        top_layout.addWidget(page_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.connection_label)
        top_layout.addWidget(self.connection_button)
        top_layout.addWidget(self.enable_button)
        top_layout.addWidget(self.calibrate_button)
        self.status_label = QLabel(
            f"{MOTOR_COUNT} \u4e2a\u7535\u673a\u5747\u672a\u4f7f\u80fd"
            " \u00b7 \u4f4d\u7f6e\u76ee\u6807\u5468\u671f 50 ms"
        )
        self.status_label.setObjectName("motorStatusLabel")
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        top_layout.addWidget(self.status_label, 1)

        card = QFrame()
        card.setObjectName("contentCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 15, 18, 17)
        card_layout.setSpacing(12)

        heading = QLabel("\u72ec\u7acb\u5173\u8282\u76ee\u6807\u4f4d\u7f6e")
        heading.setObjectName("motorSectionTitle")
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("motorScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        grid_container = QWidget()
        grid_container.setObjectName("motorGridContainer")
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(3, 3, 3, 3)
        grid.setHorizontalSpacing(13)
        grid.setVerticalSpacing(13)

        for column in range(len(THUMB_JOINT_NAMES)):
            grid.setColumnStretch(column + 1, 1)

        for row, (finger_name, joints) in enumerate(zip(MOTOR_ROW_NAMES, MOTOR_JOINT_NAMES)):
            row_label = QLabel(finger_name)
            row_label.setObjectName("motorRowHeading")
            row_label.setAlignment(Qt.AlignCenter)
            grid.addWidget(row_label, row, 0)
            grid.setRowStretch(row, 1)

            for column in range(len(joints)):
                motor_id = len(self._motor_cards)
                motor_card = MotorCard(motor_id, grid_container)
                motor_card.target_changed.connect(self._on_target_changed)
                self._motor_cards.append(motor_card)
                grid.addWidget(motor_card, row, column + 1)

        self.scroll_area.setWidget(grid_container)

        root.addWidget(top_bar)
        card_layout.addWidget(heading)
        card_layout.addWidget(self.scroll_area, 1)
        root.addWidget(card, 1)

        self.set_connected(False)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.connection_label.setText(
            "\u4e32\u53e3\u5df2\u8fde\u63a5"
            if connected
            else "\u4e32\u53e3\u672a\u8fde\u63a5"
        )
        self.connection_label.setProperty("connected", connected)
        self._repolish(self.connection_label)

        self.connection_button.setText(
            "\u65ad\u5f00\u4e32\u53e3" if connected else "\u8fde\u63a5\u4e32\u53e3"
        )
        self.connection_button.setObjectName(
            "motorDisableButton" if connected else "motorEnableButton"
        )
        self._repolish(self.connection_button)

        for card in self._motor_cards:
            card.slider.setEnabled(connected)

        if not connected:
            self._round_timer.stop()
            self._slot_timer.stop()
            self._position_slot_timer.stop()
            self._stage_timer.stop()
            self._calibration_timeout_timer.stop()
            self._position_round_active = False
            self._sweep_kind = None
            self._enable_settle_pending = False
            self._disable_settle_pending = False
            self._calibration_generation += 1
            self._calibration_stage = None
            self._calibration_command_replies.clear()
            self._calibration_success.clear()
            self._stop_disable_polling()
            self._enabled = False
            self._set_enabled_button_state(False)
            self.status_label.setText(
                "\u4e32\u53e3\u5df2\u65ad\u5f00"
                " \u00b7 \u8bf7\u91cd\u65b0\u8fde\u63a5\u540e\u63a7\u5236\u7535\u673a"
            )
        else:
            self.status_label.setText(
                "\u4e32\u53e3\u5df2\u8fde\u63a5"
                " \u00b7 \u7535\u673a\u5747\u672a\u4f7f\u80fd"
            )
        self._refresh_controls()

    def _confirm_calibration(self) -> None:
        if not self._can_start_operation():
            return
        answer = QMessageBox.warning(
            self,
            "\u96f6\u70b9\u6807\u5b9a\u5b89\u5168\u786e\u8ba4",
            "\u8bf7\u786e\u4fdd\u624b\u90e8\u673a\u6784\u5df2\u9759\u6b62\u3001"
            "\u65e0\u4eba\u5458\u53d7\u538b\uff0c\u5e76\u5904\u4e8e\u53ef\u5b89\u5168\u6821\u96f6\u7684\u4f4d\u7f6e\u3002"
            "\n\n\u6821\u96f6\u524d\u5c06\u5931\u80fd\u6240\u6709\u7535\u673a\u3002",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            self._calibrate_all()

    def _can_start_operation(self) -> bool:
        busy_sweep = self._sweep_kind not in (None, "position")
        return (
            self._connected
            and not busy_sweep
            and self._calibration_stage is None
            and not self._enable_settle_pending
            and not self._disable_settle_pending
        )

    def _toggle_enabled(self) -> None:
        if not self._can_start_operation():
            return

        if self._enabled:
            self._start_sweep("disable", list(range(MOTOR_COUNT)), 0.0)
        else:
            self._stop_disable_polling()
            self._start_sweep("enable", list(range(MOTOR_COUNT)), 0.0)

    def _calibrate_all(self) -> None:
        if not self._can_start_operation():
            return

        self._stop_disable_polling()
        self._stage_timer.stop()
        self._calibration_timeout_timer.stop()
        self._calibration_generation += 1
        self._enable_settle_pending = False
        self._enabled = False
        self._set_enabled_button_state(False)
        self._calibration_stage = "disabling"
        self._calibration_command_replies.clear()
        self._calibration_success.clear()
        self._start_sweep(
            "calibration_disable",
            list(range(MOTOR_COUNT)),
            0.0,
        )

    def _start_sweep(self, kind: str, motor_ids: list[int], value: float) -> None:
        self._round_timer.stop()
        self._position_slot_timer.stop()
        self._position_round_active = False
        self._sweep_kind = kind
        self._sweep_ids = motor_ids
        self._sweep_index = 0
        self._sweep_value = value
        self.status_label.setText(
            f"\u6b63\u5728\u6309 ID \u9010\u4e2a\u53d1\u9001"
            f"{self._sweep_name(kind)}\uff1a0 / {len(motor_ids)}"
        )
        self._refresh_controls()
        self._send_next_sweep_command()

    def _send_next_sweep_command(self) -> None:
        kind = self._sweep_kind
        if kind is None:
            self._slot_timer.stop()
            return

        if self._sweep_index >= len(self._sweep_ids):
            self._complete_sweep(kind)
            return

        motor_id = self._sweep_ids[self._sweep_index]
        command = {
            "enable": COMMAND_ENABLE,
            "disable": COMMAND_DISABLE,
            "calibration_disable": COMMAND_DISABLE,
            "calibrate": COMMAND_CALIBRATE_ZERO,
        }[kind]

        callback = None
        if kind == "calibrate":
            generation = self._calibration_generation
            callback = (
                lambda response, expected_id=motor_id, token=generation:
                self._on_calibration_response(expected_id, token, response)
            )

        self._sweep_index += 1
        if not self._send_command(motor_id, command, self._sweep_value, callback):
            self._fail_sweep(kind, motor_id)
            return

        self.status_label.setText(
            f"\u6b63\u5728\u6309 ID \u9010\u4e2a\u53d1\u9001"
            f"{self._sweep_name(kind)}\uff1a"
            f"{self._sweep_index} / {len(self._sweep_ids)}"
        )
        self._schedule_next_sweep_slot()

    def _schedule_next_sweep_slot(self) -> None:
        if self._sweep_index < len(self._sweep_ids):
            self._slot_timer.start(COMMAND_SLOT_INTERVAL_MS)
        else:
            kind = self._sweep_kind
            if kind is not None:
                self._complete_sweep(kind)

    def _on_slot_timer(self) -> None:
        self._send_next_sweep_command()

    def _complete_sweep(self, kind: str) -> None:
        self._slot_timer.stop()
        if self._sweep_kind != kind:
            return
        self._sweep_kind = None

        if kind == "enable":
            self._enabled = True
            self._set_enabled_button_state(True)
            self._enable_settle_pending = True
            self.status_label.setText(
                "\u4f7f\u80fd\u547d\u4ee4\u5df2\u53d1\u9001"
                " \u00b7 \u7b49\u5f85\u8c03\u5ea6\u677f\u5e94\u7528\u547d\u4ee4"
            )
            self._stage_timer.start(ENABLE_SETTLE_MS)
        elif kind == "disable":
            self._enabled = False
            self._set_enabled_button_state(False)
            self._disable_settle_pending = True
            self.status_label.setText(
                "\u5931\u80fd\u547d\u4ee4\u5df2\u53d1\u9001"
                " \u00b7 \u7b49\u5f85\u8c03\u5ea6\u677f\u4e0b\u53d1"
            )
            self._stage_timer.start(ENABLE_SETTLE_MS)
        elif kind == "calibration_disable":
            self._calibration_stage = "stabilizing"
            self.status_label.setText(
                "\u5931\u80fd\u547d\u4ee4\u5df2\u6392\u961f"
                " \u00b7 \u7b49\u5f85\u8c03\u5ea6\u677f\u5c06\u547d\u4ee4\u4e0b\u53d1"
            )
            self._stage_timer.start(CALIBRATION_SETTLE_MS)
        elif kind == "calibrate":
            self._calibration_stage = "calibration_wait"
            self.status_label.setText(
                "校零命令已排队；等待主控轮询后切换失能，不能确认校零成功"
            )
            self._stage_timer.start(CALIBRATION_SWITCH_MS)

        self._refresh_controls()

    def _fail_sweep(self, kind: str, motor_id: int) -> None:
        self._slot_timer.stop()
        self._sweep_kind = None
        self._round_timer.stop()
        self._position_slot_timer.stop()
        self._position_round_active = False
        if self._connected:
            # A partial ENABLE/DISABLE sweep must not leave an unknown subset
            # of boards energized; the protocol permits a no-response broadcast stop.
            self._send_command(0xFF, COMMAND_DISABLE, 0.0, None)

        if kind in ("calibration_disable", "calibrate"):
            self._calibration_generation += 1
            self._calibration_stage = None
            self.status_label.setText(
                f"ID {motor_id} 的校零流程排队失败；已尝试广播失能，不能确认各板状态"
            )
            self._start_disable_polling()
        else:
            self._enabled = False
            self._set_enabled_button_state(False)
            self.status_label.setText(
                f"\u53d1\u9001\u81f3 ID {motor_id} \u5931\u8d25"
                f"\uff1b{self._sweep_name(kind)}\u5df2\u505c\u6b62"
            )
        self._refresh_controls()

    def _on_stage_timeout(self) -> None:
        if self._enable_settle_pending:
            self._enable_settle_pending = False
            if self._connected and self._enabled:
                self.status_label.setText(
                    "\u4f7f\u80fd\u547d\u4ee4\u5df2\u53d1\u9001\uff0c\u72b6\u6001\u5f85\u53cd\u9988"
                    " \u00b7 \u76ee\u6807\u4f4d\u7f6e\u6bcf 50 ms \u8f6e\u8be2"
                )
                self._round_timer.start(POSITION_ROUND_INTERVAL_MS)
                self._start_position_round()
            self._refresh_controls()
            return

        if self._disable_settle_pending:
            self._disable_settle_pending = False
            self.status_label.setText(f"{MOTOR_COUNT} \u4e2a\u7535\u673a\u5df2\u5931\u80fd")
            self._refresh_controls()
            return

        if self._calibration_stage == "stabilizing":
            self._begin_calibration_sweep()
        elif self._calibration_stage == "calibration_wait":
            self._calibration_stage = "verifying"
            self._calibration_timeout_timer.start(CALIBRATION_TIMEOUT_MS)
            self._start_disable_polling()

    def _begin_calibration_sweep(self) -> None:
        if not self._connected or self._calibration_stage != "stabilizing":
            return
        self._calibration_stage = "calibrating"
        self.status_label.setText(
            "\u6b63\u5728\u9010\u677f\u53d1\u9001\u96f6\u70b9\u6821\u51c6\u547d\u4ee4"
        )
        self._start_sweep("calibrate", list(range(MOTOR_COUNT)), 0.0)

    def _start_position_round(self) -> None:
        if (
            not self._connected
            or not self._enabled
            or self._calibration_stage is not None
            or self._enable_settle_pending
            or self._position_round_active
            or self._sweep_kind not in (None, "position")
        ):
            return

        self._position_round_active = True
        self._position_index = 0
        self._sweep_kind = "position"
        if self._send_position_round is not None:
            targets = tuple(
                card.target_degrees() for card in self._motor_cards
            )
            if not self._send_position_round(targets):
                self._round_timer.stop()
                self._position_round_active = False
                self._sweep_kind = None
                self.status_label.setText(
                    "\u4f4d\u7f6e\u547d\u4ee4\u53d1\u9001\u5931\u8d25"
                    "\uff1b\u5468\u671f\u53d1\u9001\u5df2\u6682\u505c"
                )
                self._refresh_controls()
                return
            self._position_index = MOTOR_COUNT
            self._finish_position_round()
            return

        self._send_next_position()

    def _send_next_position(self) -> None:
        if not self._position_round_active or self._sweep_kind != "position":
            self._position_slot_timer.stop()
            return

        motor_id = self._position_index
        if motor_id >= MOTOR_COUNT:
            self._finish_position_round()
            return

        target = self._motor_cards[motor_id].target_degrees()
        if not self._send_command(
            motor_id,
            COMMAND_IMPEDANCE_POSITION,
            target,
            None,
        ):
            self._round_timer.stop()
            self._position_slot_timer.stop()
            self._position_round_active = False
            self._sweep_kind = None
            self.status_label.setText(
                f"ID {motor_id} \u7684\u4f4d\u7f6e\u547d\u4ee4\u53d1\u9001\u5931\u8d25"
                "\uff1b\u5468\u671f\u53d1\u9001\u5df2\u6682\u505c"
            )
            self._refresh_controls()
            return

        self._position_index += 1
        if self._position_index < MOTOR_COUNT:
            self._position_slot_timer.start(COMMAND_SLOT_INTERVAL_MS)
        else:
            self._finish_position_round()

    def _finish_position_round(self) -> None:
        self._position_slot_timer.stop()
        self._position_round_active = False
        if self._sweep_kind == "position":
            self._sweep_kind = None
        self._refresh_controls()

    def _on_calibration_response(
        self, motor_id: int, generation: int, response: MotorResponse,
    ) -> None:
        if (
            generation != self._calibration_generation
            or self._calibration_stage not in (
                "calibrating", "calibration_wait", "verifying",
            )
            or response.motor_id != motor_id
        ):
            return
        self._calibration_command_replies.add(motor_id)
        if response.status & STATUS_ZERO_VALID:
            self._calibration_success.add(motor_id)
        else:
            self._calibration_success.discard(motor_id)
        self._update_calibration_status()

    def _start_disable_polling(self) -> None:
        if not self._connected:
            return
        self._disable_polling = True
        self._disable_poll_error = False
        self._disable_round_index = 0
        self._send_next_disable_poll()

    def _stop_disable_polling(self) -> None:
        self._disable_polling = False
        self._disable_round_index = None
        self._disable_poll_timer.stop()
        if self._cancel_disable_polls is not None:
            self._cancel_disable_polls()

    def _on_disable_poll_timer(self) -> None:
        if not self._disable_polling or not self._connected:
            return
        if self._disable_round_index is None:
            self._disable_round_index = 0
        self._send_next_disable_poll()

    def _send_next_disable_poll(self) -> None:
        if not self._disable_polling or self._disable_round_index is None:
            return
        motor_id = self._disable_round_index
        callback = None
        if self._calibration_stage == "verifying":
            generation = self._calibration_generation
            callback = (
                lambda response, expected_id=motor_id, token=generation:
                self._on_calibration_response(expected_id, token, response)
            )
        if not self._send_disable_poll(motor_id, COMMAND_DISABLE, 0.0, callback):
            self._disable_poll_error = True
            self.status_label.setText(
                f"ID {motor_id} 的失能轮询排队失败，正在重试；不能确认各板状态"
            )
            self._disable_poll_timer.start(DISABLE_ROUND_INTERVAL_MS)
            return
        if self._disable_poll_error:
            self._disable_poll_error = False
            self._update_calibration_status(
                finished=self._calibration_stage is None
            )
        self._disable_round_index += 1
        if self._disable_round_index == MOTOR_COUNT:
            self._disable_round_index = None
            self._disable_poll_timer.start(DISABLE_ROUND_INTERVAL_MS)
        else:
            self._disable_poll_timer.start(COMMAND_SLOT_INTERVAL_MS)

    def handle_motor_response(self, response: object) -> None:
        """Update telemetry from an already validated motor reply."""

        motor_id = getattr(response, "motor_id", None)
        if not isinstance(motor_id, int):
            return
        if 0 <= motor_id < len(self._motor_cards):
            received_at = getattr(response, "received_at", None)
            previous_at = self._last_motor_response_at.get(motor_id, float("-inf"))
            if isinstance(received_at, (int, float)) and received_at < previous_at:
                return
            if isinstance(received_at, (int, float)):
                self._last_motor_response_at[motor_id] = received_at
            self._motor_cards[motor_id].update_telemetry(response)

    def _on_calibration_timeout(self) -> None:
        if self._calibration_stage != "verifying":
            return
        self._calibration_generation += 1
        self._calibration_stage = None
        if not self._disable_polling:
            self._start_disable_polling()
        self._update_calibration_status(finished=True)
        self._refresh_controls()

    def _update_calibration_status(self, *, finished: bool = False) -> None:
        missing = sorted(set(range(MOTOR_COUNT)) - self._calibration_command_replies)
        prefix = "校零统计结束" if finished else "校零状态"
        message = (
            f"{prefix}：收到 {len(self._calibration_command_replies)} / {MOTOR_COUNT} 板响应，"
            f"收到零点有效标志 {len(self._calibration_success)} / {MOTOR_COUNT}；"
            "不能确认本次校零成功"
        )
        if finished and missing:
            message += "; 未收到响应 ID：" + ", ".join(map(str, missing))
        if self._disable_poll_error:
            message += "；失能轮询排队失败，正在重试，不能确认各板状态"
        self.status_label.setText(message)

    def _on_target_changed(self, _motor_id: int, _degrees: float) -> None:
        # Each position slot samples the latest slider value for its own motor.
        return

    def _set_enabled_button_state(self, enabled: bool) -> None:
        self.enable_button.setText(
            "\u5931\u80fd\u5168\u90e8\u7535\u673a"
            if enabled
            else "\u4f7f\u80fd\u5168\u90e8\u7535\u673a"
        )
        self.enable_button.setObjectName(
            "motorDisableButton" if enabled else "motorEnableButton"
        )
        self._repolish(self.enable_button)

    def _refresh_controls(self) -> None:
        busy_sweep = self._sweep_kind not in (None, "position")
        can_control = (
            self._connected
            and not busy_sweep
            and self._calibration_stage is None
            and not self._enable_settle_pending
            and not self._disable_settle_pending
        )
        self.enable_button.setEnabled(can_control)
        self.calibrate_button.setEnabled(can_control)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    @staticmethod
    def _sweep_name(kind: str) -> str:
        return {
            "enable": "\u4f7f\u80fd\u547d\u4ee4",
            "disable": "\u5931\u80fd\u547d\u4ee4",
            "calibration_disable": "\u6821\u96f6\u524d\u5931\u80fd\u547d\u4ee4",
            "calibrate": "\u96f6\u70b9\u6821\u51c6\u547d\u4ee4",
            "position": "\u4f4d\u7f6e\u547d\u4ee4",
        }.get(kind, "\u63a7\u5236\u547d\u4ee4")