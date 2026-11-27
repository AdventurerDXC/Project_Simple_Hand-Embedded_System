"""Binary command framing for the motor-drive boards."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from time import monotonic

from protocol import CHECKSUM_INDEX, FRAME_HEADER, FRAME_SIZE


REQUEST_SOF = 0xA5
REQUEST_SIZE = 10
MOTOR_COUNT = 17
RESPONSE_SOF = 0x5A
RESPONSE_SIZE = 16

COMMAND_IMPEDANCE_POSITION = 2
COMMAND_CALIBRATE_ZERO = 5
COMMAND_ENABLE = 6
COMMAND_DISABLE = 7

STATUS_MOTOR_ENABLED = 1 << 0
STATUS_ZERO_CALIBRATING = 1 << 1
STATUS_ZERO_VALID = 1 << 2


@dataclass(frozen=True, slots=True)
class MotorResponse:
    """A validated motor-driver telemetry response from the shared CDC stream."""

    motor_id: int
    sequence: int
    position: int
    bus_voltage: float
    temperature: float
    status: int
    received_at: float

    @property
    def position_degrees(self) -> float:
        """Convert the unsigned wire representation of a signed Q15 angle."""

        signed_position = (
            self.position
            if self.position < 0x8000
            else self.position - 0x10000
        )
        return signed_position * (180.0 / 32768.0)


def crc16_ccitt_false(data: bytes | bytearray | memoryview) -> int:
    """Compute the protocol's CRC-16/CCITT-FALSE checksum."""

    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_motor_command(
    motor_id: int,
    command: int,
    value: float = 0.0,
    sequence: int = 0,
) -> bytes:
    """Encode one little-endian 10-byte request for the BDC protocol."""

    if not 0 <= motor_id <= 0xFF:
        raise ValueError("motor_id must fit in one byte")
    if motor_id >= MOTOR_COUNT and motor_id != 0xFF:
        raise ValueError(f"motor_id must be in the range 0..{MOTOR_COUNT - 1} or broadcast 0xFF")
    if not 0 <= command <= 7:
        raise ValueError("command must be in the range 0..7")
    if not 0 <= sequence <= 0xFF:
        raise ValueError("sequence must fit in one byte")
    if not math.isfinite(value):
        raise ValueError("command value must be finite")
    if motor_id == 0xFF and command != COMMAND_DISABLE:
        raise ValueError("broadcast is allowed only for DISABLE")

    payload = struct.pack("<BBBBf", REQUEST_SOF, motor_id, command, sequence, value)
    return payload + struct.pack("<H", crc16_ccitt_false(payload))


class MotorResponseParser:
    """Demultiplex known motor replies without consuming tactile-frame payload."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(
        self,
        data: bytes | bytearray | memoryview,
    ) -> list[MotorResponse]:
        responses, _ = self.feed_demultiplexed(data)
        return responses

    def feed_demultiplexed(
        self,
        data: bytes | bytearray | memoryview,
    ) -> tuple[list[MotorResponse], bytes]:
        """Parse motor telemetry and return other stream bytes for tactile parsing."""

        if data:
            self._buffer.extend(data)

        responses: list[MotorResponse] = []
        non_motor = bytearray()
        cursor = 0

        while cursor < len(self._buffer):
            remaining = len(self._buffer) - cursor
            if remaining == 1 and self._buffer[cursor] == FRAME_HEADER[0]:
                # Preserve a split tactile SOF across USB CDC reads.
                break
            if remaining == 1 and self._buffer[cursor] == RESPONSE_SOF:
                # A response SOF may be split from its ID/sequence across reads.
                break
            if remaining >= 2 and self._buffer[cursor:cursor + 2] == b"\xFF\x66":
                # A tactile frame owns its entire payload; do not scan its bytes as SOFs.
                if remaining < 79:
                    break
                candidate = bytes(self._buffer[cursor:cursor + 79])
                if self._valid_tactile_frame(candidate):
                    non_motor.extend(candidate)
                    cursor += len(candidate)
                else:
                    non_motor.append(self._buffer[cursor])
                    cursor += 1
                continue

            if self._buffer[cursor] == RESPONSE_SOF:
                if remaining < 2:
                    break

                motor_id = self._buffer[cursor + 1]
                if motor_id >= MOTOR_COUNT:
                    non_motor.append(self._buffer[cursor])
                    cursor += 1
                    continue
                if remaining < RESPONSE_SIZE:
                    break

                candidate = bytes(self._buffer[cursor:cursor + RESPONSE_SIZE])
                response = self._decode(candidate)
                if response is not None:
                    responses.append(response)
                    cursor += RESPONSE_SIZE
                else:
                    non_motor.append(self._buffer[cursor])
                    cursor += 1
                continue

            non_motor.append(self._buffer[cursor])
            cursor += 1

        if cursor:
            del self._buffer[:cursor]
        return responses, bytes(non_motor)

    @staticmethod
    def _valid_tactile_frame(frame: bytes) -> bool:
        return (
            len(frame) == FRAME_SIZE
            and frame[:len(FRAME_HEADER)] == FRAME_HEADER
            and (sum(frame[:CHECKSUM_INDEX]) & 0xFFFF)
            == ((frame[CHECKSUM_INDEX] << 8) | frame[CHECKSUM_INDEX + 1])
        )

    @staticmethod
    def _decode(frame: bytes) -> MotorResponse | None:
        if len(frame) != RESPONSE_SIZE or frame[0] != RESPONSE_SOF:
            return None

        received_crc = struct.unpack_from("<H", frame, 14)[0]
        if frame[1] >= MOTOR_COUNT or crc16_ccitt_false(frame[:14]) != received_crc:
            return None

        position, bus_voltage, temperature, status = struct.unpack_from(
            "<HffB", frame, 3
        )
        if not math.isfinite(bus_voltage) or not math.isfinite(temperature):
            return None
        return MotorResponse(
            motor_id=frame[1],
            sequence=frame[2],
            position=position,
            bus_voltage=bus_voltage,
            temperature=temperature,
            status=status,
            received_at=monotonic(),
        )


def build_test_response(
    motor_id: int,
    sequence: int,
    position: int = 0,
    bus_voltage: float = 0.0,
    temperature: float = 0.0,
    status: int = 0,
) -> bytes:
    """Build a protocol response frame for isolated parser tests."""

    if not 0 <= motor_id < MOTOR_COUNT:
        raise ValueError(f"motor_id must be in the range 0..{MOTOR_COUNT - 1}")
    if not 0 <= sequence <= 0xFF:
        raise ValueError("sequence must fit in one byte")
    if not 0 <= position <= 0xFFFF or not 0 <= status <= 0xFF:
        raise ValueError("position/status out of range")
    if not math.isfinite(bus_voltage) or not math.isfinite(temperature):
        raise ValueError("telemetry values must be finite")

    payload = struct.pack(
        "<BBBHffB",
        RESPONSE_SOF,
        motor_id,
        sequence,
        position,
        bus_voltage,
        temperature,
        status,
    )
    return payload + struct.pack("<H", crc16_ccitt_false(payload))