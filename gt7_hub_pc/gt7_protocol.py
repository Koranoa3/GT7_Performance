from __future__ import annotations

import ipaddress
import struct
from enum import IntEnum
from typing import Any, List


class FrameType(IntEnum):
    PING = 1
    PONG = 2
    TELEMETRY = 3
    BIND = 4
    EVENT = 5
    ACK = 6


MAGIC = b"G7"
VERSION = 1
HEADER = struct.Struct("<2sBBBBHHH")
TELEMETRY = struct.Struct("<ffbBB?ffffhhii")
EVENT = struct.Struct("<BB")

EVENT_GEAR_CHANGED = 1


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


def _float(packet: Any, name: str, default: float = 0.0) -> float:
    value = getattr(packet, name, default)
    return default if value is None else float(value)


def _int(packet: Any, name: str, default: int = 0) -> int:
    value = getattr(packet, name, default)
    return default if value in (None, "") else int(value)


def _nested_float(packet: Any, group: str, name: str) -> float:
    nested = getattr(packet, group, None)
    value = getattr(nested, name, 0.0)
    return 0.0 if value is None else float(value)


def build_telemetry_payload(packet: Any) -> bytes:
    flags = getattr(packet, "flags", None)
    return TELEMETRY.pack(
        _float(packet, "car_speed"),
        _float(packet, "engine_rpm"),
        _int(packet, "current_gear", -1),
        _int(packet, "throttle"),
        _int(packet, "brake"),
        bool(getattr(flags, "in_race", False)),
        _float(packet, "turbo_boost"),
        _nested_float(packet, "velocity", "x"),
        _nested_float(packet, "velocity", "y"),
        _nested_float(packet, "velocity", "z"),
        _int(packet, "lap_count", -1),
        _int(packet, "cars_in_race", -1),
        _int(packet, "best_lap_time", -1),
        _int(packet, "last_lap_time", -1),
    )


def build_bind_payload(ps5_ip: str) -> bytes:
    return ipaddress.IPv4Address(ps5_ip).packed


def build_event_payload(event_id: int, value: int) -> bytes:
    return EVENT.pack(event_id & 0xFF, value & 0xFF)
