from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Iterable


FRAME_HEADER = b"\xFF\x66"
FRAME_SIZE = 79
BOARD_ID_INDEX = 2
COUNTER_INDEX = 3
ADC_DATA_INDEX = 5
ADC_POINT_COUNT = 36
CHECKSUM_INDEX = 77


@dataclass(frozen=True, slots=True)
class TactileFrame:
    """一帧已经通过帧头、长度和校验和验证的触觉数据。"""

    board_id: int
    counter: int
    adc: tuple[int, ...]
    received_at: float
    raw: bytes


class TactileStreamParser:
    """
    面向USB CDC字节流的79字节定长帧解析器。

    USB虚拟串口是字节流：一次read()可能只得到半帧，也可能同时得到多帧。
    因此不能假设每次串口读取都刚好返回79字节。
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.valid_frames = 0
        self.checksum_errors = 0
        self.discarded_bytes = 0

    def reset(self) -> None:
        self._buffer.clear()
        self.valid_frames = 0
        self.checksum_errors = 0
        self.discarded_bytes = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[TactileFrame]:
        if data:
            self._buffer.extend(data)

        frames: list[TactileFrame] = []

        while True:
            if len(self._buffer) < len(FRAME_HEADER):
                break

            header_index = self._buffer.find(FRAME_HEADER)

            if header_index < 0:
                # 若最后一个字节是0xFF，则保留它，以便与下一批数据中的0x66拼成帧头。
                keep = 1 if self._buffer[-1] == FRAME_HEADER[0] else 0
                discard_count = len(self._buffer) - keep
                if discard_count > 0:
                    del self._buffer[:discard_count]
                    self.discarded_bytes += discard_count
                break

            if header_index > 0:
                del self._buffer[:header_index]
                self.discarded_bytes += header_index

            if len(self._buffer) < FRAME_SIZE:
                break

            candidate = bytes(self._buffer[:FRAME_SIZE])

            if self._is_valid(candidate):
                del self._buffer[:FRAME_SIZE]
                frame = self._decode(candidate)
                frames.append(frame)
                self.valid_frames += 1
            else:
                # 只丢弃一个字节，重新寻找下一处0xFF 0x66，避免错误帧造成长期失步。
                del self._buffer[0]
                self.discarded_bytes += 1
                self.checksum_errors += 1

        return frames

    @staticmethod
    def _is_valid(frame: bytes) -> bool:
        if len(frame) != FRAME_SIZE:
            return False

        if frame[:2] != FRAME_HEADER:
            return False

        # Board ID 0x00～0x0B均允许使用，ID合法性由界面配置判断。
        calculated = sum(frame[:CHECKSUM_INDEX]) & 0xFFFF
        received = (frame[CHECKSUM_INDEX] << 8) | frame[CHECKSUM_INDEX + 1]
        return calculated == received

    @staticmethod
    def _decode(frame: bytes) -> TactileFrame:
        board_id = frame[BOARD_ID_INDEX]
        counter = (frame[COUNTER_INDEX] << 8) | frame[COUNTER_INDEX + 1]

        adc_values = []
        for point_index in range(ADC_POINT_COUNT):
            byte_index = ADC_DATA_INDEX + point_index * 2
            adc_value = (frame[byte_index] << 8) | frame[byte_index + 1]
            adc_values.append(adc_value)

        return TactileFrame(
            board_id=board_id,
            counter=counter,
            adc=tuple(adc_values),
            received_at=monotonic(),
            raw=frame,
        )


def build_test_frame(
    board_id: int,
    counter: int,
    adc_values: Iterable[int],
) -> bytes:
    """用于离线测试解析器，不参与正式通信。"""

    values = list(adc_values)
    if len(values) != ADC_POINT_COUNT:
        raise ValueError(f"必须提供{ADC_POINT_COUNT}个ADC值")

    frame = bytearray(FRAME_SIZE)
    frame[0:2] = FRAME_HEADER
    frame[BOARD_ID_INDEX] = board_id & 0xFF
    frame[COUNTER_INDEX] = (counter >> 8) & 0xFF
    frame[COUNTER_INDEX + 1] = counter & 0xFF

    for point_index, adc_value in enumerate(values):
        adc_value = max(0, min(0xFFFF, int(adc_value)))
        byte_index = ADC_DATA_INDEX + point_index * 2
        frame[byte_index] = (adc_value >> 8) & 0xFF
        frame[byte_index + 1] = adc_value & 0xFF

    checksum = sum(frame[:CHECKSUM_INDEX]) & 0xFFFF
    frame[CHECKSUM_INDEX] = (checksum >> 8) & 0xFF
    frame[CHECKSUM_INDEX + 1] = checksum & 0xFF
    return bytes(frame)
