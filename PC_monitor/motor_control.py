"""Motor controls and command scheduling for the desktop monitor."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

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
    STATUS_ZERO_CALIBRATING,
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
CALIBRATION_COMMAND_GUARD_MS = POSITION_ROUND_INTERVAL_MS * 2 + 20
CALIBRATION_RETRY_MS = 100
CALIBRATION_RESPONSE_TIMEOUT_MS = 350
CALIBRATION_TIMEOUT_MS = 15000

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
    ) -> None:
        super().__init__(parent)
        self._send_command = send_command
        self._send_position_round = send_position_round
        self._connected = False
        self._enabled = False
        self._enable_settle_pending = False
        self._disable_settle_pending = False

        self._sweep_kind: str | None = None
        self._sweep_ids: list[int] = []
        self._sweep_index = 0
        self._active_motor_id: int | None = None
        self._sweep_value = 0.0

        self._position_round_active = False
        self._position_index = 0
        self._motor_cards: list[MotorCard] = []
        self._last_motor_response_at: dict[int, float] = {}

        self._calibration_stage: str | None = None
        self._calibration_waiting: set[int] = set()
        self._calibration_command_replies: set[int] = set()
        self._calibration_accepted: set[int] = set()
        self._calibration_started_at: dict[int, float] = {}
        self._calibration_verification_waiting: set[int] = set()
        self._calibration_verification_scheduled: set[int] = set()
        self._calibration_response_motor_id: int | None = None
        self._calibration_in_progress: int | None = None
        self._calibration_success: set[int] = set()
        self._calibration_failed: set[int] = set()

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

        self._calibration_response_timer = QTimer(self)
        self._calibration_response_timer.setSingleShot(True)
        self._calibration_response_timer.timeout.connect(
            self._on_calibration_response_timeout
        )

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
            self._calibration_stage = None
            self._calibration_waiting.clear()
            self._calibration_command_replies.clear()
            self._calibration_accepted.clear()
            self._calibration_started_at.clear()
            self._calibration_verification_waiting.clear()
            self._calibration_verification_scheduled.clear()
            self._calibration_response_timer.stop()
            self._calibration_response_motor_id = None
            self._calibration_in_progress = None
            self._calibration_success.clear()
            self._calibration_failed.clear()
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
            self._start_sweep("enable", list(range(MOTOR_COUNT)), 0.0)

    def _calibrate_all(self) -> None:
        if not self._can_start_operation():
            return

        self._stage_timer.stop()
        self._calibration_timeout_timer.stop()
        self._enable_settle_pending = False
        self._enabled = False
        self._set_enabled_button_state(False)
        self._calibration_stage = "disabling"
        self._calibration_waiting.clear()
        self._calibration_command_replies.clear()
        self._calibration_accepted.clear()
        self._calibration_started_at.clear()
        self._calibration_verification_waiting.clear()
        self._calibration_verification_scheduled.clear()
        self._calibration_response_timer.stop()
        self._calibration_response_motor_id = None
        self._calibration_in_progress = None
        self._calibration_success.clear()
        self._calibration_failed.clear()
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
        self._active_motor_id = motor_id
        command = {
            "enable": COMMAND_ENABLE,
            "disable": COMMAND_DISABLE,
            "calibration_disable": COMMAND_DISABLE,
            "calibrate": COMMAND_CALIBRATE_ZERO,
        }[kind]

        callback = None
        if kind == "calibrate":
            self._calibration_waiting.add(motor_id)
            self._calibration_started_at[motor_id] = monotonic()
            callback = (
                lambda response, expected_id=motor_id:
                self._on_calibration_command_response(expected_id, response)
            )

        if kind != "calibrate":
            self._sweep_index += 1
        queued = self._send_command(motor_id, command, self._sweep_value, callback)
        if not queued:
            if kind == "calibrate":
                self._calibration_waiting.discard(motor_id)
                self._complete_calibration_motor(motor_id, success=False)
            else:
                self._fail_sweep(kind, motor_id)
            return

        if kind == "calibrate":
            # The bridge serializes board requests and responses; calibrate
            # one board at a time so status queries cannot collide with a
            # different board's in-flight CAL_ZERO response.
            QTimer.singleShot(
                CALIBRATION_COMMAND_GUARD_MS,
                lambda expected_id=motor_id:
                self._on_calibration_command_guard_timeout(expected_id),
            )
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
        if self._sweep_kind == "calibrate":
            motor_id = self._active_motor_id
            if (
                motor_id is not None
                and (
                    motor_id in self._calibration_success
                    or motor_id in self._calibration_failed
                )
            ):
                self._active_motor_id = None
                self._send_next_sweep_command()
            return
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
            self.status_label.setText(
                "\u6821\u96f6\u547d\u4ee4\u5df2\u53d1\u9001"
                " \u00b7 \u7b49\u5f85\u5404\u677f\u56de\u4f20\u96f6\u70b9\u72b6\u6001"
            )
            self._maybe_finish_calibration()

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

        if kind == "calibration_disable":
            self._calibration_stage = None
            self.status_label.setText(
                f"ID {motor_id} \u7684\u5931\u80fd\u547d\u4ee4\u53d1\u9001\u5931\u8d25"
                "\uff1b\u5df2\u53d6\u6d88\u6821\u96f6"
            )
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

    def _begin_calibration_sweep(self) -> None:
        if not self._connected or self._calibration_stage != "stabilizing":
            return
        self._calibration_stage = "calibrating"
        self._calibration_timeout_timer.start(CALIBRATION_TIMEOUT_MS)
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

    def _on_calibration_command_response(
        self,
        motor_id: int,
        response: MotorResponse,
    ) -> None:
        if (
            self._calibration_stage != "calibrating"
            or motor_id not in self._calibration_waiting
            or self._active_motor_id != motor_id
        ):
            return

        self._calibration_waiting.remove(motor_id)
        self._calibration_command_replies.add(motor_id)
        if response.status & STATUS_ZERO_CALIBRATING:
            self._calibration_accepted.add(motor_id)
            self._calibration_in_progress = motor_id
            self._calibration_started_at[motor_id] = monotonic()
            self._queue_calibration_stop(motor_id)
            return

        if response.status & STATUS_ZERO_VALID:
            # If a previous timeout reset the parser's expectation after a
            # genuine CAL_ZERO response, this may be the final status. Still
            # replace the table entry, but require the 100 ms minimum.
            self._calibration_accepted.add(motor_id)
            self._calibration_started_at.setdefault(motor_id, monotonic())
            self._queue_calibration_stop(motor_id)
            return

        # A valid reply without either calibration or valid-zero status means
        # the request was rejected. Replace the persistent table entry and
        # continue with the next motor while retaining this failure.
        self._send_command(motor_id, COMMAND_DISABLE, 0.0, None)
        self._complete_calibration_motor(motor_id, success=False)

    def _on_calibration_command_guard_timeout(self, motor_id: int) -> None:
        if (
            self._calibration_stage != "calibrating"
            or self._active_motor_id != motor_id
            or motor_id not in self._calibration_waiting
        ):
            return

        # The scheduler may miss the brief CALIBRATING reply during Flash
        # operations. Replace the command before it can retrigger on later
        # poll rounds, then allow the first status query after the guard.
        self._calibration_waiting.remove(motor_id)
        self._calibration_verification_scheduled.add(motor_id)
        if not self._send_command(motor_id, COMMAND_DISABLE, 0.0, None):
            self._calibration_verification_scheduled.discard(motor_id)
            self._complete_calibration_motor(motor_id, success=False)
            return
        QTimer.singleShot(
            CALIBRATION_SETTLE_MS,
            lambda expected_id=motor_id:
            self._begin_calibration_verification(expected_id),
        )

    def _queue_calibration_stop(self, motor_id: int) -> None:
        if (
            not self._connected
            or self._calibration_stage != "calibrating"
            or motor_id in self._calibration_success
            or motor_id in self._calibration_failed
            or motor_id in self._calibration_verification_waiting
            or motor_id in self._calibration_verification_scheduled
        ):
            return

        # Replace CAL_ZERO in the bridge's persistent command table, but do
        # not treat this immediate reply as the final state query. The
        # firmware requires at least 100 ms after calibration begins before
        # continuing to poll its status.
        self._calibration_verification_scheduled.add(motor_id)
        if not self._send_command(motor_id, COMMAND_DISABLE, 0.0, None):
            self._calibration_verification_scheduled.discard(motor_id)
            self._complete_calibration_motor(motor_id, success=False)
            return
        QTimer.singleShot(
            CALIBRATION_SETTLE_MS,
            lambda expected_id=motor_id:
            self._begin_calibration_verification(expected_id),
        )

    def _begin_calibration_verification(self, motor_id: int) -> None:
        self._calibration_verification_scheduled.discard(motor_id)
        if (
            not self._connected
            or self._calibration_stage != "calibrating"
            or self._active_motor_id != motor_id
            or motor_id in self._calibration_success
            or motor_id in self._calibration_failed
            or motor_id in self._calibration_verification_waiting
        ):
            return

        self._calibration_verification_waiting.add(motor_id)
        if not self._send_command(
            motor_id,
            COMMAND_DISABLE,
            0.0,
            lambda response, expected_id=motor_id:
            self._on_calibration_verification(expected_id, response),
        ):
            self._calibration_verification_waiting.discard(motor_id)
            self._complete_calibration_motor(motor_id, success=False)
            return
        self._start_calibration_response_timeout(motor_id)
        self._update_calibration_status()

    def _on_calibration_verification(
        self,
        motor_id: int,
        response: MotorResponse,
    ) -> None:
        if (
            self._calibration_stage != "calibrating"
            or motor_id not in self._calibration_verification_waiting
        ):
            return

        self._calibration_verification_waiting.remove(motor_id)
        self._stop_calibration_response_timeout(motor_id)
        self._calibration_verification_scheduled.discard(motor_id)
        self._calibration_command_replies.add(motor_id)
        if motor_id not in self._calibration_accepted:
            if response.status & STATUS_ZERO_CALIBRATING:
                # The CAL_ZERO reply may have been lost during the firmware's
                # Flash stall, but a later matching poll proves it was accepted.
                self._calibration_accepted.add(motor_id)
                self._calibration_in_progress = motor_id
                self._calibration_started_at.setdefault(motor_id, monotonic())
                self._update_calibration_status()
                QTimer.singleShot(
                    CALIBRATION_RETRY_MS,
                    lambda expected_id=motor_id:
                    self._retry_calibration_verification(expected_id),
                )
                return
            self._complete_calibration_motor(motor_id, success=False)
            return
        if (
            response.status & STATUS_ZERO_VALID
            and not response.status & STATUS_ZERO_CALIBRATING
        ):
            if self._calibration_in_progress == motor_id:
                self._calibration_in_progress = None
            started_at = self._calibration_started_at.get(motor_id, monotonic())
            elapsed_ms = (monotonic() - started_at) * 1000
            if elapsed_ms < CALIBRATION_SETTLE_MS:
                remaining_ms = max(
                    1,
                    int(CALIBRATION_SETTLE_MS - elapsed_ms + 0.999),
                )
                self._update_calibration_status()
                QTimer.singleShot(
                    remaining_ms,
                    lambda expected_id=motor_id:
                    self._retry_calibration_verification(expected_id),
                )
                return
            self._complete_calibration_motor(motor_id, success=True)
            return

        self._update_calibration_status()
        if self._calibration_in_progress == motor_id:
            QTimer.singleShot(
                CALIBRATION_RETRY_MS,
                lambda expected_id=motor_id:
                self._retry_calibration_verification(expected_id),
            )
            return
        QTimer.singleShot(
            CALIBRATION_RETRY_MS,
            lambda expected_id=motor_id:
            self._retry_calibration_verification(expected_id),
        )

    def _retry_calibration_verification(self, motor_id: int) -> None:
        if (
            not self._connected
            or self._calibration_stage != "calibrating"
            or motor_id in self._calibration_success
            or motor_id in self._calibration_failed
            or motor_id in self._calibration_verification_waiting
            or motor_id in self._calibration_verification_scheduled
        ):
            return

        self._calibration_verification_scheduled.add(motor_id)
        self._calibration_verification_waiting.add(motor_id)
        if not self._send_command(
            motor_id,
            COMMAND_DISABLE,
            0.0,
            lambda response, expected_id=motor_id:
            self._on_calibration_verification(expected_id, response),
        ):
            self._calibration_verification_scheduled.discard(motor_id)
            self._calibration_verification_waiting.discard(motor_id)
            self._complete_calibration_motor(motor_id, success=False)
            return
        self._start_calibration_response_timeout(motor_id)
        self._update_calibration_status()

    def _start_calibration_response_timeout(self, motor_id: int) -> None:
        self._calibration_response_motor_id = motor_id
        self._calibration_response_timer.start(
            CALIBRATION_RESPONSE_TIMEOUT_MS
        )

    def _stop_calibration_response_timeout(self, motor_id: int) -> None:
        if self._calibration_response_motor_id == motor_id:
            self._calibration_response_timer.stop()
            self._calibration_response_motor_id = None

    def _on_calibration_response_timeout(self) -> None:
        motor_id = self._calibration_response_motor_id
        self._calibration_response_motor_id = None
        if (
            motor_id is None
            or self._calibration_stage != "calibrating"
            or self._active_motor_id != motor_id
            or motor_id not in self._calibration_verification_waiting
        ):
            return

        self._calibration_verification_waiting.discard(motor_id)
        self._calibration_verification_scheduled.discard(motor_id)
        # Replace a timed-out CAL_ZERO before advancing, so the bridge cannot
        # replay the persistent calibration command on a later poll round.
        if self._connected:
            self._send_command(motor_id, COMMAND_DISABLE, 0.0, None)
        self._complete_calibration_motor(motor_id, success=False)

    def _complete_calibration_motor(self, motor_id: int, *, success: bool) -> None:
        self._stop_calibration_response_timeout(motor_id)
        if success:
            self._calibration_success.add(motor_id)
        else:
            self._calibration_failed.add(motor_id)
        self._calibration_waiting.discard(motor_id)
        self._calibration_verification_waiting.discard(motor_id)
        self._calibration_verification_scheduled.discard(motor_id)
        self._calibration_started_at.pop(motor_id, None)
        self._calibration_accepted.discard(motor_id)
        if self._calibration_in_progress == motor_id:
            self._calibration_in_progress = None
        self._update_calibration_status()

        if self._sweep_kind != "calibrate":
            return
        if self._calibration_in_progress is not None:
            return
        self._sweep_index += 1
        self._slot_timer.start(COMMAND_SLOT_INTERVAL_MS)

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
        if self._calibration_stage != "calibrating":
            return

        self._calibration_failed.update(
            set(range(MOTOR_COUNT)) - self._calibration_success
        )
        self._slot_timer.stop()
        self._calibration_waiting.clear()
        self._calibration_response_timer.stop()
        self._calibration_response_motor_id = None
        self._active_motor_id = None
        self._calibration_accepted.clear()
        self._calibration_started_at.clear()
        self._calibration_verification_waiting.clear()
        self._calibration_verification_scheduled.clear()
        self._calibration_in_progress = None
        if self._connected:
            # CAL_ZERO remains the bridge's latest command until replaced.
            self._send_command(0xFF, COMMAND_DISABLE, 0.0, None)
        self._finish_calibration()

    def _update_calibration_status(self) -> None:
        self.status_label.setText(
            f"\u6821\u96f6\u72b6\u6001\uff1a"
            f"\u5df2\u6536\u5230 {len(self._calibration_command_replies)} / "
            f"{MOTOR_COUNT} \u677f\u54cd\u5e94"
            f"\uff0c\u6536\u5230\u96f6\u70b9\u6709\u6548\u6807\u5fd7 "
            f"{len(self._calibration_success)} / {MOTOR_COUNT}"
            "\uff1b\u4e0d\u80fd\u786e\u8ba4\u672c\u6b21\u6821\u96f6\u6210\u529f"
        )

    def _maybe_finish_calibration(self) -> None:
        if self._calibration_stage != "calibrating":
            return
        if self._sweep_kind == "calibrate":
            return
        accounted = self._calibration_success | self._calibration_failed
        if len(accounted) == MOTOR_COUNT:
            self._finish_calibration()

    def _finish_calibration(self) -> None:
        self._calibration_timeout_timer.stop()
        self._calibration_response_timer.stop()
        self._calibration_response_motor_id = None
        self._stage_timer.stop()
        self._slot_timer.stop()
        self._calibration_stage = None
        self._sweep_kind = None
        self._enabled = False
        self._set_enabled_button_state(False)

        missing = sorted(set(range(MOTOR_COUNT)) - self._calibration_success)
        if missing:
            ids = ", ".join(str(motor_id) for motor_id in missing)
            self.status_label.setText(
                f"\u6821\u96f6\u7ed3\u675f\uff1b\u6536\u5230\u96f6\u70b9\u6709\u6548\u6807\u5fd7 "
                f"{len(self._calibration_success)} / {MOTOR_COUNT}"
                "\uff1b\u4e0d\u80fd\u786e\u8ba4\u672c\u6b21\u6821\u96f6\u6210\u529f"
                f"\uff1b\u5931\u8d25 ID\uff1a{ids}"
            )
        else:
            self.status_label.setText(
                f"{MOTOR_COUNT} \u4e2a\u7535\u673a\u6536\u5230\u96f6\u70b9\u6709\u6548\u6807\u5fd7"
                "\uff1b\u4e0d\u80fd\u786e\u8ba4\u672c\u6b21\u6821\u96f6\u6210\u529f"
            )
        self._refresh_controls()

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