from __future__ import annotations

import bisect
import csv
import datetime as dt
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import List, Optional


@dataclass
class TraceVector3:
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]


@dataclass
class TraceRotation:
    yaw: Optional[float]


@dataclass
class TraceBounds:
    min: Optional[float]
    max: Optional[float]


@dataclass
class TraceFlags:
    in_race: bool = False
    paused: bool = False
    loading_or_processing: bool = False
    car_on_track: bool = False


@dataclass
class TracePacket:
    packet_id: int
    logged_at: str
    car_speed: Optional[float]
    velocity: TraceVector3
    orientation: Optional[float]
    angular_velocity: TraceVector3
    rotation: TraceRotation
    engine_rpm: Optional[float]
    rpm_alert: TraceBounds
    throttle: Optional[int]
    brake: Optional[int]
    turbo_boost: Optional[float]
    current_gear: Optional[int]
    flags: TraceFlags
    cars_in_race: Optional[int]
    lap_count: Optional[int]
    laps_in_race: Optional[int]
    best_lap_time: Optional[int]
    last_lap_time: Optional[int]


class LogTraceListener:
    """CSV recorded telemetry replay listener compatible with TelemetryReceiver."""

    def __init__(self, log_trace_path: Path) -> None:
        self._log_trace_path = Path(log_trace_path)
        self._closed = Event()
        self._started_at_monotonic: Optional[float] = None
        self._offsets_ms: List[float] = []
        self._packets: List[TracePacket] = []
        self._last_emitted_index = -1
        self._load_trace()

    def start(self) -> None:
        if self._started_at_monotonic is not None:
            return
        self._started_at_monotonic = time.monotonic()

    def close(self) -> None:
        self._closed.set()

    def get(self, timeout: Optional[float] = None) -> TracePacket:
        if self._closed.is_set():
            raise TimeoutError("LogTraceListener is closed")
        if self._started_at_monotonic is None:
            raise RuntimeError("LogTraceListener.start() must be called before get()")

        deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
        while True:
            if self._closed.is_set():
                raise TimeoutError("LogTraceListener is closed")

            elapsed_ms = (time.monotonic() - self._started_at_monotonic) * 1000.0
            due_index = bisect.bisect_right(self._offsets_ms, elapsed_ms) - 1
            if due_index > self._last_emitted_index:
                self._last_emitted_index = due_index
                return self._packets[due_index]

            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("No packet available in the given timeout")

            time.sleep(0.001)

    def _load_trace(self) -> None:
        if not self._log_trace_path.exists():
            raise FileNotFoundError(f"トレースCSVが見つかりません: {self._log_trace_path}")

        with self._log_trace_path.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            raise ValueError(f"トレースCSVが空です: {self._log_trace_path}")

        first_at = self._parse_datetime(rows[0]["logged_at"])
        for row in rows:
            logged_at = row.get("logged_at", "")
            packet = self._row_to_packet(row)
            at = self._parse_datetime(logged_at)
            offset_ms = (at - first_at).total_seconds() * 1000.0
            self._offsets_ms.append(offset_ms)
            self._packets.append(packet)

    def _row_to_packet(self, row: dict) -> TracePacket:
        return TracePacket(
            packet_id=self._to_int(row.get("packet_id"), default=0) or 0,
            logged_at=row.get("logged_at", ""),
            car_speed=self._to_float(row.get("car_speed")),
            velocity=TraceVector3(
                x=self._to_float(row.get("velocity_x")),
                y=self._to_float(row.get("velocity_y")),
                z=self._to_float(row.get("velocity_z")),
            ),
            orientation=self._to_float(row.get("orientation")),
            angular_velocity=TraceVector3(
                x=self._to_float(row.get("angular_velocity_x")),
                y=self._to_float(row.get("angular_velocity_y")),
                z=self._to_float(row.get("angular_velocity_z")),
            ),
            rotation=TraceRotation(yaw=self._to_float(row.get("rotation_yaw"))),
            engine_rpm=self._to_float(row.get("engine_rpm")),
            rpm_alert=TraceBounds(
                min=self._to_float(row.get("rpm_alert_min")),
                max=self._to_float(row.get("rpm_alert_max")),
            ),
            throttle=self._to_int(row.get("throttle")),
            brake=self._to_int(row.get("brake")),
            turbo_boost=self._to_float(row.get("turbo_boost")),
            current_gear=self._to_int(row.get("current_gear")),
            flags=TraceFlags(
                in_race=self._to_bool(row.get("in_race")),
                paused=self._to_bool(row.get("paused")),
                loading_or_processing=False,
                car_on_track=self._to_bool(row.get("car_on_track")),
            ),
            cars_in_race=self._to_int(row.get("cars_in_race")),
            lap_count=self._to_int(row.get("lap_count")),
            laps_in_race=self._to_int(row.get("laps_in_race")),
            best_lap_time=self._to_int(row.get("best_lap_time")),
            last_lap_time=self._to_int(row.get("last_lap_time")),
        )

    @staticmethod
    def _parse_datetime(value: str) -> dt.datetime:
        if not value:
            raise ValueError("logged_at が空です")
        return dt.datetime.fromisoformat(value)

    @staticmethod
    def _to_float(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return float(text)

    @staticmethod
    def _to_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
        if value is None:
            return default
        text = str(value).strip()
        if text == "":
            return default
        return int(text)

    @staticmethod
    def _to_bool(value: Optional[str]) -> bool:
        if value is None:
            return False
        text = str(value).strip().lower()
        if text in ("", "0", "false", "none"):
            return False
        if text in ("1", "true"):
            return True
        try:
            return bool(int(text))
        except ValueError:
            return False
