from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import serial
from PySide6.QtCore import QThread, Signal

from motor_protocol import (
    COMMAND_DISABLE,
    MOTOR_COUNT,
    REQUEST_SIZE,
    REQUEST_SOF,
    MotorResponseParser,
)
from protocol import TactileStreamParser


MAX_QUEUED_WRITES = 64


@dataclass(frozen=True, slots=True)
class _QueuedWrite:
    data: bytes
    expected_responses: tuple[tuple[int, int], ...] = ()
    coalesce_key: str | None = None
    preserve_on_stop: bool = False


class SerialReader(QThread):
    """
    后台串口接收线程。

    线程只负责：
    1. 打开USB CDC对应的COM口；
    2. 连续读取字节流；
    3. 解析79字节触觉帧；
    4. 通过Qt信号把完整帧交给GUI线程。
    """

    opened = Signal(str)
    closed = Signal()
    frame_received = Signal(object)
    motor_response_received = Signal(object)
    statistics_changed = Signal(int, int, int)
    error_occurred = Signal(str)

    def __init__(
        self,
        port: str,
        baudrate: int = 460800,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self._stop_event = threading.Event()
        self._write_queue: deque[_QueuedWrite] = deque()
        self._write_queue_lock = threading.Lock()
        self._serial_lock = threading.Lock()
        self._serial_port: serial.Serial | None = None

    def enqueue_write(self, data: bytes) -> bool:
        """Queue a complete batch for the serial-owning worker thread to write."""

        is_broadcast_disable = (
            len(data) >= REQUEST_SIZE
            and data[0] == REQUEST_SOF
            and data[1] == 0xFF
            and data[2] == COMMAND_DISABLE
        )
        return self._enqueue(
            data,
            coalesce_key="broadcast-disable" if is_broadcast_disable else None,
            preserve_on_stop=is_broadcast_disable,
        )

    def enqueue_motor_command(
        self,
        data: bytes,
        motor_id: int,
        sequence: int,
    ) -> bool:
        """Queue a motor command with its ID and sequence metadata."""

        if not 0 <= motor_id < MOTOR_COUNT or not 0 <= sequence <= 0xFF:
            return False
        return self._enqueue(data, ((motor_id, sequence),))

    def enqueue_motor_disable_poll(
        self,
        data: bytes,
        motor_id: int,
        sequence: int,
    ) -> bool:
        """Queue at most one pending periodic DISABLE per motor."""

        if not 0 <= motor_id < MOTOR_COUNT or not 0 <= sequence <= 0xFF:
            return False
        return self._enqueue(
            data,
            ((motor_id, sequence),),
            coalesce_key=f"disable-poll-{motor_id}",
        )

    def cancel_motor_disable_polls(self) -> None:
        """Remove unsent periodic DISABLEs before a new control operation."""

        with self._write_queue_lock:
            self._write_queue = deque(
                queued for queued in self._write_queue
                if queued.coalesce_key is None
                or not queued.coalesce_key.startswith("disable-poll-")
            )

    def enqueue_motor_batch(
        self,
        data: bytes,
        expected_responses: tuple[tuple[int, int], ...],
    ) -> bool:
        """Queue a concatenated motor round, replacing any stale queued round."""

        if (
            not data
            or len(data) % REQUEST_SIZE != 0
            or len(data) // REQUEST_SIZE != len(expected_responses)
            or not expected_responses
            or len(expected_responses) > MOTOR_COUNT
            or any(
                not 0 <= motor_id < MOTOR_COUNT
                or not 0 <= sequence <= 0xFF
                for motor_id, sequence in expected_responses
            )
        ):
            return False
        return self._enqueue(
            data,
            expected_responses,
            coalesce_key="motor-position-round",
        )

    @property
    def queued_write_count(self) -> int:
        with self._write_queue_lock:
            return len(self._write_queue)

    def _enqueue(
        self,
        data: bytes,
        expected_responses: tuple[tuple[int, int], ...] = (),
        *,
        coalesce_key: str | None = None,
        preserve_on_stop: bool = False,
    ) -> bool:
        if not data:
            return False

        with self._serial_lock:
            serial_port = self._serial_port
            if serial_port is None or not serial_port.is_open:
                return False
            with self._write_queue_lock:
                if self._stop_event.is_set():
                    return False
                if coalesce_key is not None:
                    self._write_queue = deque(
                        queued
                        for queued in self._write_queue
                        if queued.coalesce_key != coalesce_key
                    )
                if len(self._write_queue) >= MAX_QUEUED_WRITES:
                    if not preserve_on_stop:
                        return False
                    for index, queued in enumerate(self._write_queue):
                        if not queued.preserve_on_stop:
                            del self._write_queue[index]
                            break
                    if len(self._write_queue) >= MAX_QUEUED_WRITES:
                        return False
                self._write_queue.append(
                    _QueuedWrite(
                        bytes(data),
                        expected_responses,
                        coalesce_key,
                        preserve_on_stop,
                    )
                )
        return True

    def stop(self) -> None:
        """Stop after any queued broadcast DISABLE, discarding stale targets."""

        with self._write_queue_lock:
            self._stop_event.set()
            self._write_queue = deque(
                queued
                for queued in self._write_queue
                if queued.preserve_on_stop
            )

    def run(self) -> None:
        parser = TactileStreamParser()
        motor_parser = MotorResponseParser()
        serial_port = None
        last_statistics = (-1, -1, -1)

        try:
            serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.002,
                write_timeout=0.2,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            with self._serial_lock:
                self._serial_port = serial_port
            self.opened.emit(self.port)

            while True:
                with self._write_queue_lock:
                    outgoing = (
                        self._write_queue.popleft()
                        if self._write_queue
                        else None
                    )
                    queue_empty = not self._write_queue

                if self._stop_event.is_set() and queue_empty and outgoing is None:
                    break

                if outgoing is not None:
                    written = serial_port.write(outgoing.data)
                    if written != len(outgoing.data):
                        raise serial.SerialTimeoutException(
                            f"仅写入 {written}/{len(outgoing.data)} 字节"
                        )
                    continue

                if self._stop_event.is_set():
                    break

                waiting = serial_port.in_waiting
                read_size = min(max(waiting, 1), 4096)
                chunk = serial_port.read(read_size)

                if not chunk:
                    continue

                motor_responses, tactile_chunk = motor_parser.feed_demultiplexed(chunk)

                for frame in parser.feed(tactile_chunk):
                    self.frame_received.emit(frame)

                for response in motor_responses:
                    self.motor_response_received.emit(response)

                statistics = (
                    parser.valid_frames,
                    parser.checksum_errors,
                    parser.discarded_bytes,
                )
                if statistics != last_statistics:
                    last_statistics = statistics
                    self.statistics_changed.emit(*statistics)

        except serial.SerialException as exc:
            if not self._stop_event.is_set():
                self.error_occurred.emit(
                    f"串口 {self.port} 通信失败：\n{exc}"
                )
        except Exception as exc:  # 防止后台线程异常静默退出
            if not self._stop_event.is_set():
                self.error_occurred.emit(
                    f"串口接收线程发生未预期错误：\n{exc}"
                )
        finally:
            try:
                if serial_port is not None and serial_port.is_open:
                    serial_port.close()
            except Exception:
                # Closing must never prevent the worker's lifecycle signals.
                pass
            with self._serial_lock:
                self._serial_port = None
            with self._write_queue_lock:
                self._write_queue.clear()
            self.closed.emit()
