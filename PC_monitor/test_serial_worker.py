from __future__ import annotations

import os
import threading
from time import monotonic, sleep

import pytest
import serial

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import serial_worker as serial_worker_module
from motor_protocol import (
    COMMAND_DISABLE,
    COMMAND_IMPEDANCE_POSITION,
    MOTOR_COUNT,
    REQUEST_SIZE,
    build_motor_command,
    build_test_response,
)
from serial_worker import MAX_QUEUED_WRITES, SerialReader


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
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


class FakeSerial:
    def __init__(self, write_error: Exception | None = None) -> None:
        self.is_open = True
        self.write_error = write_error
        self.closed = threading.Event()
        self.written: list[bytes] = []

    @property
    def in_waiting(self) -> int:
        return 0

    def read(self, _size: int) -> bytes:
        sleep(0.001)
        return b""

    def write(self, data: bytes) -> int:
        if self.write_error is not None:
            raise self.write_error
        self.written.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.is_open = False
        self.closed.set()


def test_write_timeout_closes_port_and_finishes_worker(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_port = FakeSerial(serial.SerialTimeoutException("Write timeout"))
    monkeypatch.setattr(
        serial_worker_module.serial,
        "Serial",
        lambda **_kwargs: fake_port,
    )
    worker = SerialReader("COM_TEST")
    errors: list[str] = []
    closed_signals: list[bool] = []
    worker.error_occurred.connect(errors.append)
    worker.closed.connect(lambda: closed_signals.append(True))

    worker.start()
    assert wait_until(lambda: worker._serial_port is fake_port)
    assert worker.enqueue_write(b"test write")
    assert wait_until(lambda: not worker.isRunning())
    assert wait_until(lambda: bool(errors) and bool(closed_signals))

    assert errors == [
        "\u4e32\u53e3 COM_TEST \u901a\u4fe1\u5931\u8d25\uff1a\nWrite timeout"
    ]
    assert closed_signals == [True]
    assert fake_port.closed.is_set()
    assert not fake_port.is_open
    assert worker._serial_port is None
    assert not worker.enqueue_write(b"after failure")


def test_worker_accepts_repeated_and_broadcast_sequences(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReceivingSerial(FakeSerial):
        def __init__(self) -> None:
            super().__init__()
            self.incoming = bytearray()
            self.lock = threading.Lock()

        @property
        def in_waiting(self) -> int:
            with self.lock:
                return len(self.incoming)

        def read(self, size: int) -> bytes:
            with self.lock:
                data = bytes(self.incoming[:size])
                del self.incoming[:size]
            if not data:
                sleep(0.001)
            return data

        def receive(self, data: bytes) -> None:
            with self.lock:
                self.incoming.extend(data)

    fake_port = ReceivingSerial()
    monkeypatch.setattr(serial_worker_module.serial, "Serial", lambda **_kwargs: fake_port)
    worker = SerialReader("COM_TEST")
    responses = []
    worker.motor_response_received.connect(responses.append)
    worker.start()
    try:
        assert wait_until(lambda: worker._serial_port is fake_port)
        command = build_motor_command(16, COMMAND_DISABLE, sequence=42)
        assert worker.enqueue_motor_command(command, 16, 42)
        assert wait_until(lambda: command in fake_port.written)
        fake_port.receive(build_test_response(16, 42, position=1))
        assert wait_until(lambda: len(responses) == 1)
        fake_port.receive(build_test_response(16, 42, position=2))
        assert wait_until(lambda: len(responses) == 2)
        broadcast = build_motor_command(0xFF, COMMAND_DISABLE, sequence=43)
        assert worker.enqueue_write(broadcast)
        assert wait_until(lambda: broadcast in fake_port.written)
        fake_port.receive(build_test_response(16, 42) + build_test_response(16, 43, position=3))
        assert wait_until(lambda: len(responses) == 3)
        assert [response.position for response in responses] == [1, 2, 3]
    finally:
        worker.stop()
        assert worker.wait(2000)


def test_repeated_telemetry_updates_ui_but_callback_runs_once(app: QApplication) -> None:
    from main import MainWindow
    from motor_protocol import MotorResponseParser

    window = MainWindow()
    parser = MotorResponseParser()
    parser.expect_response(16, 42)
    callbacks = []
    window._pending_motor_acks[(16, 42)] = (callbacks.append, monotonic() + 3.0)
    for position in (100, 200):
        responses, other = parser.feed_demultiplexed(
            build_test_response(16, 42, position=position, bus_voltage=12.5)
        )
        assert other == b""
        assert len(responses) == 1
        window._on_motor_response(responses[0])
    assert [response.position for response in callbacks] == [100]
    assert window.motor_page._motor_cards[16].actual_angle_label.text() == (
        "实际 +1.10°"
    )
    window.close()


def test_motor_round_queue_is_bounded_coalesced_and_stops_safely(
    app: QApplication,
) -> None:
    worker = SerialReader("COM_TEST")
    fake_port = FakeSerial()
    worker._serial_port = fake_port  # Exercise the queue without starting I/O.

    first_round = b"".join(
        build_motor_command(
            motor_id,
            COMMAND_IMPEDANCE_POSITION,
            float(motor_id),
            motor_id,
        )
        for motor_id in range(MOTOR_COUNT)
    )
    latest_round = b"".join(
        build_motor_command(
            motor_id,
            COMMAND_IMPEDANCE_POSITION,
            float(-motor_id),
            motor_id + 1,
        )
        for motor_id in range(MOTOR_COUNT)
    )
    first_expected = tuple((motor_id, motor_id) for motor_id in range(MOTOR_COUNT))
    latest_expected = tuple(
        (motor_id, motor_id + 1) for motor_id in range(MOTOR_COUNT)
    )

    assert worker.enqueue_motor_batch(first_round, first_expected)
    assert worker.enqueue_motor_batch(latest_round, latest_expected)
    assert worker.queued_write_count == 1
    assert worker._write_queue[0].data == latest_round
    assert worker._write_queue[0].expected_responses == latest_expected

    assert worker.enqueue_write(b"regular")
    disable_frame = build_motor_command(
        0xFF,
        COMMAND_DISABLE,
        sequence=42,
    )
    assert len(disable_frame) == REQUEST_SIZE
    assert worker.enqueue_write(disable_frame)
    for _ in range(MAX_QUEUED_WRITES - worker.queued_write_count):
        assert worker.enqueue_write(b"queued")
    assert worker.queued_write_count == MAX_QUEUED_WRITES
    assert not worker.enqueue_write(b"overflow")

    replacement_disable = build_motor_command(
        0xFF,
        COMMAND_DISABLE,
        sequence=43,
    )
    assert worker.enqueue_write(replacement_disable)
    assert worker.queued_write_count == MAX_QUEUED_WRITES
    assert sum(
        queued.preserve_on_stop for queued in worker._write_queue
    ) == 1

    worker.stop()
    assert worker.queued_write_count == 1
    assert worker._write_queue[0].data == replacement_disable


def test_motor_queue_accepts_last_id_and_rejects_out_of_range() -> None:
    worker = SerialReader("COM_TEST")
    worker._serial_port = FakeSerial()
    last_frame = build_motor_command(16, COMMAND_IMPEDANCE_POSITION, sequence=7)
    assert worker.enqueue_motor_command(last_frame, 16, 7)
    assert not worker.enqueue_motor_command(last_frame, 17, 7)
    assert not worker.enqueue_motor_batch(last_frame, ((17, 7),))
    assert not worker.enqueue_motor_batch(last_frame * 18, ((16, 7),) * 18)


def test_position_round_sender_batches_all_slider_targets(app: QApplication) -> None:
    from motor_control import MotorControlPage

    sent_rounds: list[tuple[float, ...]] = []
    page = MotorControlPage(
        lambda *_args: True,
        send_position_round=lambda targets: sent_rounds.append(targets) or True,
    )
    page.set_connected(True)
    page._motor_cards[0].slider.setValue(-350)
    page._motor_cards[-1].slider.setValue(1200)
    page._enabled = True

    page._start_position_round()

    assert len(sent_rounds) == 1
    assert len(sent_rounds[0]) == MOTOR_COUNT
    assert sent_rounds[0][0] == -35.0
    assert sent_rounds[0][-1] == 120.0
    assert not page._position_round_active
    page.close()


def test_main_window_queues_seventeen_position_commands_in_order(app: QApplication) -> None:
    from main import MainWindow

    window = MainWindow()
    worker = SerialReader("COM_TEST")
    worker._serial_port = FakeSerial()
    worker.isRunning = lambda: True
    window.serial_worker = worker
    window.connected = True
    window._motor_sequence = 250
    targets = tuple(float(motor_id) for motor_id in range(17))

    assert not window.send_motor_position_round(targets[:-1])
    assert not window.send_motor_position_round(targets + (17.0,))
    assert window.send_motor_position_round(targets)
    queued = worker._write_queue[0]
    assert len(queued.data) == 17 * REQUEST_SIZE
    for motor_id in range(17):
        sequence = (250 + motor_id) & 0xFF
        assert queued.data[motor_id * REQUEST_SIZE:(motor_id + 1) * REQUEST_SIZE] == (
            build_motor_command(motor_id, COMMAND_IMPEDANCE_POSITION, float(motor_id), sequence)
        )
    assert queued.expected_responses == tuple(
        (motor_id, (250 + motor_id) & 0xFF) for motor_id in range(17)
    )
    window.serial_worker = None
    window.connected = False
    window.close()


def test_serial_error_dialog_is_modeless_and_worker_shutdown_is_deferred(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from main import MainWindow

    fake_port = FakeSerial(serial.SerialTimeoutException("Write timeout"))
    monkeypatch.setattr(
        serial_worker_module.serial,
        "Serial",
        lambda **_kwargs: fake_port,
    )
    window = MainWindow()
    window.start_serial("COM_TEST", show_monitor=False)
    worker = window.serial_worker
    assert worker is not None
    assert wait_until(lambda: window.connected)

    assert worker.enqueue_write(b"trigger timeout")

    assert wait_until(lambda: window._serial_error_dialog is not None)
    assert window._serial_error_dialog is not None
    assert not window._serial_error_dialog.isModal()
    assert wait_until(lambda: window.serial_worker is None)
    assert fake_port.closed.is_set()
    assert window.connection_page.connect_button.isEnabled() is True

    window._serial_error_dialog.close()
    window.close()