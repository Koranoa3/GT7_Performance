from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import List


class FrameType(IntEnum):
    PING = 1
    PONG = 2
    TELEMETRY = 3
    BIND = 4
    EVENT = 5
    ACK = 6


MAGIC = b"G7"
VERSION = 1
HEADER_STRUCT = struct.Struct("<2sBBBBHHH")
TELEMETRY_STRUCT = struct.Struct("<ffbBB?ffffhhii")


@dataclass
class Frame:
    frame_type: FrameType
    device_id: int
    seq: int
    flags: int
    payload: bytes


@dataclass
class TelemetrySnapshot:
    car_speed: float = 0.0
    engine_rpm: float = 0.0
    current_gear: int = -1
    throttle: int = 0
    brake: int = 0
    in_race: bool = False
    turbo_boost: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    velocity_z: float = 0.0
    lap_count: int = -1
    cars_in_race: int = -1
    best_lap_time: int = -1
    last_lap_time: int = -1

    @classmethod
    def from_packet(cls, packet: object) -> "TelemetrySnapshot":
        def get_attr(name: str, default: object = 0) -> object:
            value = getattr(packet, name, default)
            return default if value is None else value

        def int_or_default(value: object, default: int) -> int:
            if value is None or value == "":
                return default
            return int(value)

        velocity = getattr(packet, "velocity", None)
        lap_count = getattr(packet, "lap_count", None)
        cars_in_race = getattr(packet, "cars_in_race", None)
        best_lap_time = getattr(packet, "best_lap_time", None)
        last_lap_time = getattr(packet, "last_lap_time", None)

        return cls(
            car_speed=float(get_attr("car_speed", 0.0) or 0.0),
            engine_rpm=float(get_attr("engine_rpm", 0.0) or 0.0),
            current_gear=int_or_default(get_attr("current_gear", -1), -1),
            throttle=int_or_default(get_attr("throttle", 0), 0),
            brake=int_or_default(get_attr("brake", 0), 0),
            in_race=bool(getattr(getattr(packet, "flags", None), "in_race", False)),
            turbo_boost=float(get_attr("turbo_boost", 0.0) or 0.0),
            velocity_x=float(getattr(velocity, "x", 0.0) or 0.0),
            velocity_y=float(getattr(velocity, "y", 0.0) or 0.0),
            velocity_z=float(getattr(velocity, "z", 0.0) or 0.0),
            lap_count=int(lap_count) if lap_count is not None else -1,
            cars_in_race=int(cars_in_race) if cars_in_race is not None else -1,
            best_lap_time=int(best_lap_time) if best_lap_time is not None else -1,
            last_lap_time=int(last_lap_time) if last_lap_time is not None else -1,
        )


class FrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        if data:
            self._buffer.extend(data)

        frames: List[Frame] = []
        header_size = HEADER_STRUCT.size

        while True:
            if len(self._buffer) < header_size:
                break

            magic_index = self._buffer.find(MAGIC)
            if magic_index < 0:
                self._buffer.clear()
                break
            if magic_index > 0:
                del self._buffer[:magic_index]
                if len(self._buffer) < header_size:
                    break

            magic, version, frame_type, flags, _reserved, seq, device_id, payload_len = HEADER_STRUCT.unpack_from(
                self._buffer
            )
            if magic != MAGIC:
                del self._buffer[:2]
                continue
            if version != VERSION:
                del self._buffer[:header_size]
                continue

            frame_size = header_size + payload_len
            if len(self._buffer) < frame_size:
                break

            payload = bytes(self._buffer[header_size:frame_size])
            del self._buffer[:frame_size]
            try:
                frame_kind = FrameType(frame_type)
            except ValueError:
                continue
            frames.append(
                Frame(
                    frame_type=frame_kind,
                    device_id=device_id,
                    seq=seq,
                    flags=flags,
                    payload=payload,
                )
            )

        return frames


def build_frame(
    frame_type: FrameType,
    device_id: int,
    seq: int = 0,
    payload: bytes = b"",
    flags: int = 0,
) -> bytes:
    return HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        int(frame_type),
        flags & 0xFF,
        0,
        seq & 0xFFFF,
        device_id & 0xFFFF,
        len(payload) & 0xFFFF,
    ) + payload


def pack_ipv4(address: str) -> bytes:
    return ipaddress.IPv4Address(address).packed


def unpack_ipv4(payload: bytes) -> str:
    if len(payload) < 4:
        raise ValueError("IPv4 payload is too short")
    return str(ipaddress.IPv4Address(payload[:4]))


def build_telemetry_payload(snapshot: TelemetrySnapshot) -> bytes:
    return TELEMETRY_STRUCT.pack(
        float(snapshot.car_speed),
        float(snapshot.engine_rpm),
        int(snapshot.current_gear),
        int(snapshot.throttle) & 0xFF,
        int(snapshot.brake) & 0xFF,
        bool(snapshot.in_race),
        float(snapshot.turbo_boost),
        float(snapshot.velocity_x),
        float(snapshot.velocity_y),
        float(snapshot.velocity_z),
        int(snapshot.lap_count),
        int(snapshot.cars_in_race),
        int(snapshot.best_lap_time),
        int(snapshot.last_lap_time),
    )


def unpack_telemetry_payload(payload: bytes) -> TelemetrySnapshot:
    values = TELEMETRY_STRUCT.unpack(payload[: TELEMETRY_STRUCT.size])
    return TelemetrySnapshot(
        car_speed=values[0],
        engine_rpm=values[1],
        current_gear=values[2],
        throttle=values[3],
        brake=values[4],
        in_race=values[5],
        turbo_boost=values[6],
        velocity_x=values[7],
        velocity_y=values[8],
        velocity_z=values[9],
        lap_count=values[10],
        cars_in_race=values[11],
        best_lap_time=values[12],
        last_lap_time=values[13],
    )


def build_bind_payload(ps5_ip: str) -> bytes:
    return pack_ipv4(ps5_ip)
