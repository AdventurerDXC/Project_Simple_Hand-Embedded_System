from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSlider

import motor_control as motor_control_module
from motor_control import MotorControlPage
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
from styles import APP_STYLE


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    instance.setStyleSheet(APP_STYLE)
    return instance


def wait_until(predicate, timeout_ms: int = 1500) -> bool:
    if predicate():
        return True

    loop = QEventLoop()
    poll_timer = QTimer()
    poll_timer.setInterval(1)
    poll_timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline_timer = QTimer()
    deadline_timer.setSingleShot(True)
    deadline_timer.timeout.connect(loop.quit)
    poll_timer.start()
    deadline_timer.start(timeout_ms)
    loop.exec()
    poll_timer.stop()
    deadline_timer.stop()
    return predicate()


def test_page_has_seventeen_motor_sliders_in_finger_joint_order(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    sliders = page.findChildren(QSlider, "motorSlider")
    angle_inputs = page.findChildren(QDoubleSpinBox, "motorTargetValue")
    expected_joints = (
        ("拇指", ("CMC_FE", "CMC_Rotation", "MCP_FE", "PIP_FE", "DIP_FE")),
        ("食指", ("MCP_AA", "MCP_FE", "PIP_FE", "DIP_FE")),
        ("中指", ("MCP_AA", "MCP_FE", "PIP_FE", "DIP_FE")),
        ("无名指", ("MCP_AA", "MCP_FE", "PIP_FE", "DIP_FE")),
    )
    grid = page.scroll_area.widget().layout()
    motor_id = 0
    for row, (finger, joints) in enumerate(expected_joints):
        for column, joint in enumerate(joints):
            card = page._motor_cards[motor_id]
            assert grid.itemAtPosition(row, column + 1).widget() is card
            assert card.findChild(type(page.status_label), "motorFingerLabel").text() == finger
            assert card.findChild(type(page.status_label), "motorJointBadge").text() == joint
            assert card.findChild(type(page.status_label), "motorIdLabel").text() == f"ID {motor_id:02d}"
            motor_id += 1
        if len(joints) == 4:
            assert grid.itemAtPosition(row, 5) is None
    assert motor_id == 17
    assert len(sliders) == 17
    assert len(angle_inputs) == 17
    assert [
        (slider.minimum(), slider.maximum(), slider.value())
        for slider in sliders
    ] == [
        (-1800, 1800, 0)
    ] * 17
    assert all(angle_input.decimals() == 1 for angle_input in angle_inputs)
    assert all(angle_input.value() == 0.0 for angle_input in angle_inputs)
    page.resize(1680, 980)
    page.show()
    app.processEvents()
    assert all(angle_input.lineEdit().isVisible() for angle_input in angle_inputs)
    assert all(
        angle_input.lineEdit().width() > angle_input.width() // 2
        for angle_input in angle_inputs
    )
    for card in page._motor_cards:
        badge = card.findChild(type(page.status_label), "motorJointBadge")
        assert badge.width() >= badge.fontMetrics().horizontalAdvance(badge.text()) + 16
    page.close()


def test_enable_then_disable_send_each_id_in_order(
    app: QApplication,
) -> None:
    sent: list[tuple[int, int, float]] = []
    page = MotorControlPage(
        lambda motor_id, command, value, *_args: sent.append(
            (motor_id, command, value)
        )
        or True
    )
    page.set_connected(True)
    page._toggle_enabled()
    assert sent == [(0, COMMAND_ENABLE, 0.0)]
    assert wait_until(lambda: len(sent) == 17)
    assert [command for _, command, _ in sent] == [COMMAND_ENABLE] * 17
    assert [motor_id for motor_id, _, _ in sent] == list(range(17))
    assert page._enable_settle_pending

    assert wait_until(lambda: not page._enable_settle_pending)
    assert "状态待反馈" in page.status_label.text()
    assert "已使能" not in page.status_label.text()
    sent.clear()
    page._toggle_enabled()
    assert sent == [(0, COMMAND_DISABLE, 0.0)]
    assert wait_until(lambda: len(sent) == 17)
    assert [command for _, command, _ in sent] == [COMMAND_DISABLE] * 17
    assert [motor_id for motor_id, _, _ in sent] == list(range(17))
    assert page._disable_settle_pending
    assert wait_until(lambda: not page._disable_settle_pending)
    page.close()


def test_position_sweep_uses_current_slider_degrees(app: QApplication) -> None:
    sent: list[tuple[int, int, float]] = []
    page = MotorControlPage(
        lambda motor_id, command, value, *_args: sent.append(
            (motor_id, command, value)
        )
        or True
    )
    page.set_connected(True)
    page._motor_cards[0].slider.setValue(-450)
    page._motor_cards[16].slider.setValue(1800)
    page._enabled = True
    page._start_position_round()

    assert wait_until(lambda: not page._position_round_active)

    assert len(sent) == 17
    assert [motor_id for motor_id, _, _ in sent] == list(range(17))
    assert all(command == COMMAND_IMPEDANCE_POSITION for _, command, _ in sent)
    assert sent[0][2] == -45.0
    assert sent[-1][2] == 180.0
    page.close()


def test_numeric_target_entry_and_slider_stay_synchronized(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    card = page._motor_cards[0]
    changed: list[tuple[int, float]] = []
    card.target_changed.connect(lambda motor_id, value: changed.append((motor_id, value)))

    card.target_input.setValue(37.4)
    assert card.slider.value() == 374
    assert card.target_degrees() == pytest.approx(37.4)
    assert changed[-1] == (0, pytest.approx(37.4))

    card.slider.setValue(-1267)
    assert card.target_input.value() == pytest.approx(-126.7)
    assert card.target_degrees() == pytest.approx(-126.7)
    assert changed[-1] == (0, pytest.approx(-126.7))

    card.target_input.setValue(250.0)
    assert card.target_input.value() == 180.0
    assert card.slider.value() == 1800
    page.close()


def test_target_input_text_is_visible_and_accepts_keyboard_entry(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    page.resize(1680, 980)
    page.show()
    app.processEvents()
    target_input = page._motor_cards[0].target_input
    line_edit = target_input.lineEdit()

    assert line_edit.isVisible()
    assert line_edit.width() > target_input.width() // 2

    target_input.setFocus()
    line_edit.selectAll()
    QTest.keyClicks(line_edit, "42.5")
    QTest.keyClick(line_edit, Qt.Key_Enter)
    app.processEvents()

    assert target_input.value() == pytest.approx(42.5)
    assert target_input.text().startswith("42.5")
    assert page._motor_cards[0].slider.value() == 425
    page.close()


def test_motor_response_updates_live_telemetry_for_matching_card(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    response = MotorResponse(
        16,
        1,
        -0x2000 & 0xFFFF,
        12.75,
        36.4,
        0,
        1.0,
    )

    page.handle_motor_response(response)

    assert page._motor_cards[16].actual_angle_label.text() == "\u5b9e\u9645 -45.00\u00b0"
    assert page._motor_cards[16].bus_voltage_label.text() == "\u6bcd\u7ebf 12.75 V"
    assert page._motor_cards[16].temperature_label.text() == "\u6e29\u5ea6 36.4 \u00b0C"
    assert page._motor_cards[15].actual_angle_label.text() == "\u5b9e\u9645 \u2014\u2014"
    page.close()


def test_unmatched_motor_response_does_not_advance_calibration(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    page.set_connected(True)
    page._calibration_stage = "calibrating"
    response = MotorResponse(3, 1, 0, 12.0, 30.0, STATUS_ZERO_VALID, 1.0)

    page.handle_motor_response(response)

    assert page._calibration_command_replies == set()
    assert page._calibration_success == set()
    assert page._motor_cards[3].bus_voltage_label.text() == "母线 12.00 V"
    page.set_connected(False)
    page.close()

def test_motor_toolbar_is_one_row_and_long_hint_is_removed(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    assert page.enable_button.parentWidget() is page.connection_label.parentWidget()
    assert page.calibrate_button.parentWidget() is page.enable_button.parentWidget()
    assert page.status_label.parentWidget() is page.enable_button.parentWidget()
    assert page.findChild(QDoubleSpinBox, "motorTargetInput") is None
    assert not page.findChildren(type(page.status_label), "motorSectionHint")
    page.close()


def test_calibration_disables_first_then_verifies_zero_valid_status(
    app: QApplication,
) -> None:
    sent: list[tuple[int, int, float, object]] = []

    def send_command(motor_id, command, value, callback=None):
        sent.append((motor_id, command, value, callback))
        if callback is not None:
            if command == COMMAND_CALIBRATE_ZERO:
                response = MotorResponse(
                    motor_id,
                    len(sent) & 0xFF,
                    0,
                    0.0,
                    0.0,
                    STATUS_ZERO_CALIBRATING,
                    0.0,
                )
            else:
                response = MotorResponse(
                    motor_id,
                    len(sent) & 0xFF,
                    0,
                    0.0,
                    0.0,
                    STATUS_ZERO_VALID,
                    0.0,
                )
            QTimer.singleShot(0, lambda: callback(response))
        return True

    page = MotorControlPage(send_command)
    page.set_connected(True)
    page._calibrate_all()
    assert sent[0][:3] == (0, COMMAND_DISABLE, 0.0)
    assert wait_until(lambda: len(sent) == 17)
    assert [command for _, command, _, _ in sent] == [COMMAND_DISABLE] * 17
    assert page._calibration_stage == "stabilizing"

    assert wait_until(lambda: page._calibration_stage is None, timeout_ms=5000)
    calibration_commands = [entry for entry in sent if entry[1] == COMMAND_CALIBRATE_ZERO]
    assert [motor_id for motor_id, _, _, _ in calibration_commands] == list(range(17))
    assert all(callback is not None for _, _, _, callback in calibration_commands)
    verification_commands = [
        entry
        for entry in sent
        if entry[1] == COMMAND_DISABLE and entry[3] is not None
    ]
    assert [motor_id for motor_id, _, _, _ in verification_commands[:17]] == list(
        range(17)
    )

    assert page._calibration_success == set(range(17))
    assert "收到零点有效标志" in page.status_label.text()
    assert "不能确认本次校零成功" in page.status_label.text()
    assert page.calibrate_button.isEnabled() is True
    page.close()


def test_calibration_progress_reports_flags_not_verified_success(app: QApplication) -> None:
    page = MotorControlPage(lambda *_args: True)
    page._calibration_command_replies.update((0, 1))
    page._calibration_success.add(0)
    page._update_calibration_status()
    assert "收到零点有效标志 1 / 17" in page.status_label.text()
    assert "不能确认本次校零成功" in page.status_label.text()
    assert "已验证" not in page.status_label.text()
    page.close()


def test_calibration_response_requires_matching_id_and_current_generation(
    app: QApplication,
) -> None:
    page = MotorControlPage(lambda *_args: True)
    page.set_connected(True)
    page._calibration_stage = "calibrating"
    generation = page._calibration_generation
    response = MotorResponse(5, 1, 0, 0.0, 0.0, STATUS_ZERO_VALID, 0.0)
    page._on_calibration_response(6, generation, response)
    assert page._calibration_command_replies == set()
    page._on_calibration_response(5, generation, response)
    assert page._calibration_command_replies == {5}
    assert page._calibration_success == {5}
    page.set_connected(False)
    page.set_connected(True)
    page._calibration_stage = "calibrating"
    page._on_calibration_response(5, generation, response)
    assert page._calibration_command_replies == set()
    page.set_connected(False)
    page.close()

def test_calibration_skips_absent_ids_and_reaches_installed_finger(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(motor_control_module, "CALIBRATION_SETTLE_MS", 2)
    monkeypatch.setattr(motor_control_module, "CALIBRATION_SWITCH_MS", 10)
    monkeypatch.setattr(motor_control_module, "COMMAND_SLOT_INTERVAL_MS", 1)
    monkeypatch.setattr(motor_control_module, "CALIBRATION_TIMEOUT_MS", 100)

    installed_ids = set(range(5, 9))
    sent: list[tuple[int, int, object]] = []

    def send_command(motor_id, command, _value, callback=None):
        sent.append((motor_id, command, callback))
        if callback is not None and motor_id in installed_ids:
            status = (
                STATUS_ZERO_CALIBRATING
                if command == COMMAND_CALIBRATE_ZERO
                else STATUS_ZERO_VALID
            )
            response = MotorResponse(
                motor_id,
                len(sent) & 0xFF,
                0,
                0.0,
                0.0,
                status,
                0.0,
            )
            QTimer.singleShot(
                0,
                lambda current_callback=callback, current_response=response:
                current_callback(current_response),
            )
        return True

    page = MotorControlPage(send_command)
    page.set_connected(True)
    page._calibrate_all()

    assert wait_until(lambda: page._calibration_stage == "calibrating")
    assert wait_until(lambda: page._calibration_stage is None, timeout_ms=5000)

    attempted_ids = [
        motor_id
        for motor_id, command, _ in sent
        if command == COMMAND_CALIBRATE_ZERO
    ]
    assert attempted_ids == list(range(MOTOR_COUNT))
    assert page._calibration_success == installed_ids
    assert page._calibration_command_replies == installed_ids
    assert "未收到响应" in page.status_label.text()
    assert "0, 1, 2" in page.status_label.text()
    assert "收到零点有效标志" in page.status_label.text()
    assert "不能确认本次校零成功" in page.status_label.text()
    page.close()


def test_main_window_serial_shutdown_waits_for_worker_finished(
    app: QApplication,
) -> None:
    from main import MainWindow
    from serial_worker import SerialReader

    window = MainWindow()
    completions: list[object] = []
    fake_worker = SerialReader("COM_TEST")
    fake_worker.finished.connect(window._on_serial_worker_finished)
    window.serial_worker = fake_worker
    window._shutdown_pending = True
    window._close_after_shutdown = True
    window._complete_serial_worker_shutdown = lambda worker: completions.append(worker)

    fake_worker.finished.emit()
    assert wait_until(lambda: completions == [fake_worker])

    # The queued app-close is intentionally not executed in the test.
    window._close_after_shutdown = False
    window._shutdown_pending = False
    window.close()


def test_calibration_single_round_then_periodic_disable_until_enable(
    app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from time import monotonic

    monkeypatch.setattr(motor_control_module, "CALIBRATION_SETTLE_MS", 5)
    monkeypatch.setattr(motor_control_module, "CALIBRATION_SWITCH_MS", 60)
    monkeypatch.setattr(motor_control_module, "CALIBRATION_TIMEOUT_MS", 100)
    monkeypatch.setattr(motor_control_module, "COMMAND_SLOT_INTERVAL_MS", 1)
    sent = []

    def send(motor_id, command, value, callback=None):
        sent.append((monotonic(), motor_id, command, callback))
        return True

    page = MotorControlPage(send)
    page.set_connected(True)
    page._calibrate_all()
    assert wait_until(lambda: sum(x[2] == COMMAND_CALIBRATE_ZERO for x in sent) == 17)
    cal = [x for x in sent if x[2] == COMMAND_CALIBRATE_ZERO]
    assert [x[1] for x in cal] == list(range(MOTOR_COUNT))
    after_cal = len(sent)
    QTest.qWait(15)
    assert len(sent) == after_cal
    assert wait_until(lambda: len(sent) >= after_cal + 17)
    after = sent[after_cal:]
    assert all(x[2] == COMMAND_DISABLE for x in after)
    assert [x[1] for x in after[:17]] == list(range(MOTOR_COUNT))
    assert after[0][0] - cal[-1][0] >= 0.045
    assert wait_until(lambda: len(sent) >= after_cal + 34)
    assert sum(x[2] == COMMAND_CALIBRATE_ZERO for x in sent) == 17
    assert wait_until(lambda: page._calibration_stage is None)
    page._toggle_enabled()
    assert wait_until(lambda: any(x[2] == COMMAND_ENABLE for x in sent))
    enable_index = next(i for i, x in enumerate(sent) if x[2] == COMMAND_ENABLE)
    QTest.qWait(90)
    assert all(x[2] != COMMAND_DISABLE for x in sent[enable_index:])
    page.set_connected(False)
    page.close()


def test_partial_calibration_enqueue_failure_starts_disable_polling(
    app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(motor_control_module, "CALIBRATION_SETTLE_MS", 1)
    monkeypatch.setattr(motor_control_module, "COMMAND_SLOT_INTERVAL_MS", 1)
    commands = []
    polls = []

    def send(motor_id, command, _value, _callback=None):
        commands.append((motor_id, command))
        return not (motor_id == 2 and command == COMMAND_CALIBRATE_ZERO)

    page = MotorControlPage(
        send,
        send_disable_poll=lambda motor_id, command, *_args:
            polls.append((motor_id, command)) or True,
    )
    try:
        page.set_connected(True)
        page._calibrate_all()
        assert wait_until(lambda: bool(polls))
        assert [motor_id for motor_id, command in commands
                if command == COMMAND_CALIBRATE_ZERO] == [0, 1, 2]
        assert (0xFF, COMMAND_DISABLE) in commands
        assert polls[0] == (0, COMMAND_DISABLE)
        assert "不能确认各板状态" in page.status_label.text()
        QTest.qWait(25)
        assert len([command for _, command in commands
                    if command == COMMAND_CALIBRATE_ZERO]) == 3
    finally:
        page.set_connected(False)
        page.close()


def test_disable_poll_retries_enqueue_failure_and_stops_on_disconnect(
    app: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(motor_control_module, "DISABLE_ROUND_INTERVAL_MS", 5)
    attempts = []
    cancel_calls = []

    def send_poll(motor_id, command, value, callback=None):
        attempts.append((motor_id, command))
        return len(attempts) > 1

    page = MotorControlPage(
        lambda *_args: True,
        send_disable_poll=send_poll,
        cancel_disable_polls=lambda: cancel_calls.append(True),
    )
    try:
        page.set_connected(True)
        page._start_disable_polling()
        assert attempts == [(0, COMMAND_DISABLE)]
        assert "正在重试" in page.status_label.text()
        assert wait_until(lambda: len(attempts) >= 2)
        assert attempts[1] == (0, COMMAND_DISABLE)
        assert page._disable_polling
        page.set_connected(False)
        stopped_count = len(attempts)
        QTest.qWait(30)
        assert len(attempts) == stopped_count
        assert not page._disable_poll_timer.isActive()
        assert cancel_calls
    finally:
        page.set_connected(False)
        page.close()


def test_disconnect_stops_pending_motor_position_timer(app: QApplication) -> None:
    page = MotorControlPage(lambda *_args: True)
    page.set_connected(True)
    page._enabled = True
    page._start_position_round()

    assert page._position_slot_timer.isActive()
    page.set_connected(False)
    assert not page._position_slot_timer.isActive()
    page.close()