from __future__ import annotations

import ipaddress
import struct
from enum import IntEnum
from typing import Any, List, Mapping


class FrameType(IntEnum):
    PING = 1
    PONG = 2
    TELEMETRY = 3
    BIND = 4
    EVENT = 5
    ACK = 6
    SECTION_PREVIEW = 7


MAGIC = b"G7"
VERSION = 1
HEADER = struct.Struct("<2sBBBBHHH")
TELEMETRY = struct.Struct("<ffffBBbffB")
EVENT = struct.Struct("<BB")
SECTION_PREVIEW = struct.Struct("<BHH")

EVENT_COLLISION = 1
EVENT_LAP = 2

LED_STRIP_BASE = 0
LED_STRIP_MONITOR = 1

LAP_EVENT_PREPARE = 0
LAP_EVENT_START = 1
LAP_EVENT_PASS = 2
LAP_EVENT_FINISH = 3


class FrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[tuple[int, int, int, bytes]]:
        if data:
            self._buffer.extend(data)

        frames: List[tuple[int, int, int, bytes]] = []
        size = HEADER.size
        while len(self._buffer) >= size:
            if self._buffer[:2] != MAGIC:
                del self._buffer[:1]
                continue

            magic, version, frame_type, flags, _reserved, seq, device_id, payload_len = HEADER.unpack_from(self._buffer)
            if version != VERSION:
                del self._buffer[:size]
                continue

            frame_len = size + payload_len
            if len(self._buffer) < frame_len:
                break

            payload = bytes(self._buffer[size:frame_len])
            del self._buffer[:frame_len]
            frames.append((frame_type, device_id, seq, payload))

        return frames


def build_frame(frame_type: FrameType, device_id: int, seq: int = 0, payload: bytes = b"") -> bytes:
    return HEADER.pack(MAGIC, VERSION, int(frame_type), 0, 0, seq & 0xFFFF, device_id & 0xFFFF, len(payload)) + payload


def _float(values: Mapping[str, Any], name: str, default: float = 0.0) -> float:
    value = values.get(name, default)
    return default if value is None else float(value)


def _int(values: Mapping[str, Any], name: str, default: int = 0) -> int:
    value = values.get(name, default)
    return default if value in (None, "") else int(value)


def build_telemetry_payload(values: Mapping[str, Any]) -> bytes:
    return TELEMETRY.pack(
        _float(values, "car_speed"),
        _float(values, "engine_rpm"),
        _float(values, "rpm_alert_min"),
        _float(values, "rpm_alert_max"),
        _int(values, "throttle"),
        _int(values, "brake"),
        _int(values, "current_gear", -1),
        _float(values, "velocity_right"),
        _float(values, "fan_speed_multiplier", 1.0),
        _int(values, "play_state"),
    )


def build_bind_payload(ps5_ip: str) -> bytes:
    return ipaddress.IPv4Address(ps5_ip).packed


def build_event_payload(event_id: int, value: int) -> bytes:
    return EVENT.pack(event_id & 0xFF, value & 0xFF)


def build_section_preview_payload(strip_id: int, start_index: int, end_index: int) -> bytes:
    return SECTION_PREVIEW.pack(strip_id & 0xFF, start_index & 0xFFFF, end_index & 0xFFFF)
