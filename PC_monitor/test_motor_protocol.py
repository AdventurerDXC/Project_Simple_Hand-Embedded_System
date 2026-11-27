from __future__ import annotations

import struct

import pytest

import motor_protocol as motor_protocol_module
from motor_protocol import (
    COMMAND_DISABLE,
    COMMAND_IMPEDANCE_POSITION,
    MOTOR_COUNT,
    MotorResponseParser,
    build_test_response,
    build_motor_command,
    crc16_ccitt_false,
)
from protocol import TactileStreamParser, build_test_frame


def test_builds_protocol_request_with_correct_crc_and_little_endian_data() -> None:
    frame = build_motor_command(3, COMMAND_IMPEDANCE_POSITION, 45.5, 255)

    assert len(frame) == 10
    assert frame[:4] == bytes((0xA5, 3, COMMAND_IMPEDANCE_POSITION, 255))
    assert struct.unpack_from("<f", frame, 4)[0] == pytest.approx(45.5)
    assert struct.unpack_from("<H", frame, 8)[0] == crc16_ccitt_false(frame[:8])


def test_broadcast_is_only_allowed_for_disable() -> None:
    assert len(build_motor_command(0xFF, COMMAND_DISABLE)) == 10
    with pytest.raises(ValueError, match="broadcast"):
        build_motor_command(0xFF, COMMAND_IMPEDANCE_POSITION, 1.0)


def test_motor_id_boundaries_for_commands_and_responses() -> None:
    assert MOTOR_COUNT == 17
    assert build_motor_command(16, COMMAND_IMPEDANCE_POSITION)[1] == 16
    parser = MotorResponseParser()
    responses, passthrough = parser.feed_demultiplexed(build_test_response(16, 42))
    assert [response.motor_id for response in responses] == [16]
    assert passthrough == b""
    for motor_id in (-1, 17, 254, 256):
        with pytest.raises(ValueError):
            build_motor_command(motor_id, COMMAND_DISABLE)
        with pytest.raises(ValueError):
            build_test_response(motor_id, 42)
    invalid_payload = struct.pack("<BBBHffB", 0x5A, 17, 42, 0, 12.0, 30.0, 0)
    invalid_frame = invalid_payload + struct.pack("<H", crc16_ccitt_false(invalid_payload))
    responses, passthrough = parser.feed_demultiplexed(invalid_frame)
    assert responses == []
    assert passthrough == invalid_frame


def test_interleaved_tactile_frame_is_preserved_byte_for_byte() -> None:
    tactile = build_test_frame(7, 0x1234, list(range(36)))
    parser = MotorResponseParser()

    responses, tactile_bytes = parser.feed_demultiplexed(
        b"noise" + tactile + b"tail"
    )

    assert responses == []
    assert tactile_bytes == b"noise" + tactile + b"tail"
    parsed_tactile = TactileStreamParser().feed(tactile_bytes)
    assert len(parsed_tactile) == 1
    assert parsed_tactile[0].board_id == 7


def test_tactile_payload_with_motor_like_frame_is_not_misclassified() -> None:
    embedded = build_test_response(5, 7, position=1234)
    values = [int.from_bytes(embedded[i:i + 2], "big") for i in range(0, 16, 2)]
    tactile = build_test_frame(5, 123, values + [0x5A05] * 28)
    motor = build_test_response(5, 201, position=1234)
    parser = MotorResponseParser()

    first, first_tactile = parser.feed_demultiplexed(tactile[:50])
    second, second_tactile = parser.feed_demultiplexed(tactile[50:] + motor)

    assert first == []
    assert first_tactile == b""
    assert [response.sequence for response in second] == [201]
    assert second_tactile == tactile


def test_valid_motor_response_is_separated_from_tactile() -> None:
    tactile = build_test_frame(2, 0x4455, [91] * 36)
    response = build_test_response(
        4,
        23,
        position=1234,
        bus_voltage=12.5,
        temperature=35.0,
        status=1 << 1,
    )
    parser = MotorResponseParser()

    first, first_tactile = parser.feed_demultiplexed(tactile[:40] + response[:9])
    second, second_tactile = parser.feed_demultiplexed(response[9:] + tactile[40:])

    assert first == []
    assert first_tactile == b""
    assert len(second) == 1
    assert second[0].motor_id == 4
    assert second[0].sequence == 23
    assert second[0].position == 1234
    assert second[0].status == 1 << 1
    assert second_tactile == tactile


def test_telemetry_accepts_any_sequence_with_fragments_and_interleaved_tactile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(motor_protocol_module, "monotonic", lambda: clock[0])
    parser = MotorResponseParser()
    tactile = build_test_frame(2, 12, [91] * 36)
    first = build_test_response(16, 255, position=100)
    second = build_test_response(16, 0, position=200)
    responses, other = parser.feed_demultiplexed(first + tactile + second[:7])
    assert [(response.sequence, response.position) for response in responses] == [(255, 100)]
    assert other == tactile
    clock[0] += 5.0
    responses, other = parser.feed_demultiplexed(second[7:])
    assert [(response.sequence, response.position) for response in responses] == [(0, 200)]
    assert other == b""

    older = build_test_response(16, 255, position=300)
    responses, other = parser.feed_demultiplexed(older + second + second)
    assert [response.position for response in responses] == [300, 200, 200]
    assert other == b""


def test_invalid_crc_and_nonfinite_values_do_not_produce_telemetry() -> None:
    parser = MotorResponseParser()
    corrupt = bytearray(build_test_response(16, 42))
    corrupt[-1] ^= 1
    payload = struct.pack("<BBBHffB", 0x5A, 5, 99, 1, float("nan"), 30.0, 0)
    nonfinite = payload + struct.pack("<H", crc16_ccitt_false(payload))
    invalid = bytes(corrupt) + nonfinite
    responses, other = parser.feed_demultiplexed(invalid)
    assert responses == []
    assert other == invalid
    responses, other = parser.feed_demultiplexed(build_test_response(16, 42))
    assert len(responses) == 1
    assert other == b""


def test_motor_response_without_prior_command_is_telemetry() -> None:
    response = build_test_response(5, 12)
    parser = MotorResponseParser()

    parsed, passthrough = parser.feed_demultiplexed(response)

    assert [(frame.motor_id, frame.sequence) for frame in parsed] == [(5, 12)]
    assert passthrough == b""


def test_motor_stream_preserves_a_split_tactile_header() -> None:
    tactile = build_test_frame(11, 0x1234, [17] * 36)
    parser = MotorResponseParser()

    first_responses, first_bytes = parser.feed_demultiplexed(tactile[:1])
    second_responses, second_bytes = parser.feed_demultiplexed(tactile[1:])

    assert first_responses == []
    assert first_bytes == b""
    assert second_responses == []
    assert second_bytes == tactile


def test_builds_test_response_for_each_valid_motor() -> None:
    for motor_id in range(MOTOR_COUNT):
        parser = MotorResponseParser()
        responses, passthrough = parser.feed_demultiplexed(
            build_test_response(motor_id, 9)
        )
        assert len(responses) == 1
        assert responses[0].motor_id == motor_id
        assert passthrough == b""


@pytest.mark.parametrize(
    ("raw_position", "expected_degrees"),
    [
        (0x0000, 0.0),
        (0x4000, 90.0),
        (0x7FFF, 180.0 - 180.0 / 32768.0),
        (0x8000, -180.0),
        (0xC000, -90.0),
    ],
)
def test_motor_response_position_is_converted_from_signed_q15(
    raw_position: int,
    expected_degrees: float,
) -> None:
    parser = MotorResponseParser()

    responses, passthrough = parser.feed_demultiplexed(
        build_test_response(3, 21, position=raw_position)
    )

    assert passthrough == b""
    assert len(responses) == 1
    assert responses[0].position_degrees == pytest.approx(expected_degrees)