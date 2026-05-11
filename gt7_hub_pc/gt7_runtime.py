from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional, Protocol

from granturismo.intake import Listener

from gt7_console import LiveConsole
from gt7_esp_bridge import EspSerialManager
from gt7_formatting import TELEMETRY_LAYOUT, TelemetrySnapshot, TelemetryWarning
from gt7_log_trace import LogTraceListener
from gt7_protocol import (
    EVENT_COLLISION,
    EVENT_LAP,
    LAP_EVENT_FINISH,
    LAP_EVENT_PASS,
    LAP_EVENT_PREPARE,
    LAP_EVENT_START,
)
from gt7_startup import RuntimeLaunchConfig, load_runtime_config
from gt7_writer import NullTelemetrySink, TelemetryCsvSink, TelemetrySink


class TelemetrySource(Protocol):
    def start(self) -> None:
        ...

    def close(self) -> None:
        ...

    def get(self, timeout: Optional[float] = None) -> Any:
        ...


class TelemetryReceiver:
    def __init__(self, source: TelemetrySource) -> None:
        self._source = source
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[object] = None
        self._error: Optional[Exception] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, name="gt7-telemetry-receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None

    def take_latest(self) -> Optional[object]:
        packet = self._latest
        self._latest = None
        return packet

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def _worker(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    packet = self._source.get(timeout=0.1)
                except TimeoutError:
                    continue
                except Exception as exc:
                    self._error = exc
                    break

                if packet is not None:
                    self._latest = packet
        except Exception as exc:
            self._error = exc


def build_telemetry_source(ip_address: str, log_trace_path: Optional[Path]) -> TelemetrySource:
    if log_trace_path is not None:
        return LogTraceListener(log_trace_path)
    return Listener(ip_address)


def build_telemetry_sink(output_path: Path, trace_mode: bool) -> TelemetrySink:
    if trace_mode:
        return NullTelemetrySink()
    return TelemetryCsvSink(output_path, flush_every=10)


def log_snapshot_warnings(
    console: LiveConsole,
    warnings: tuple[TelemetryWarning, ...],
    seen_keys: set[tuple[str, str, tuple[str, ...]]],
) -> None:
    for warning in warnings:
        if warning.dedupe_key in seen_keys:
            continue
        console.log(f"警告: {warning.message()}")
        seen_keys.add(warning.dedupe_key)


class EspTelemetryDirector:
    def __init__(self) -> None:
        self._recent_speeds: deque[tuple[float, float]] = deque(maxlen=16)
        self._last_lap_count: Optional[int] = None
        self._last_collision_at = 0.0
        self.play_state = 0

    def update(self, snapshot: TelemetrySnapshot, now: float) -> list[tuple[int, int]]:
        self.play_state = self._resolve_play_state(snapshot)
        events: list[tuple[int, int]] = []

        if self.play_state == 1:
            if self._collision_detected(snapshot, now):
                events.append((EVENT_COLLISION, 0))
            lap_event = self._lap_event(snapshot)
            if lap_event is not None:
                events.append((EVENT_LAP, lap_event))
        else:
            self._lap_event(snapshot)

        return events

    def _resolve_play_state(self, snapshot: TelemetrySnapshot) -> int:
        paused = bool(snapshot.get("paused", False))
        car_on_track = bool(snapshot.get("car_on_track", True))
        lap_count = snapshot.get("lap_count")
        same_speed = self._speed_is_stale(snapshot)

        if paused or not car_on_track or same_speed or lap_count is None:
            return 0
        return 1

    def _speed_is_stale(self, snapshot: TelemetrySnapshot) -> bool:
        speed = snapshot.get("car_speed")
        if speed is None:
            return True

        current = float(speed)
        samples = [current]
        for _timestamp, past_speed in list(self._recent_speeds)[-4:]:
            samples.append(past_speed)
        return len(samples) >= 5 and len(set(samples)) == 1

    def _collision_detected(self, snapshot: TelemetrySnapshot, now: float) -> bool:
        speed = snapshot.get("car_speed")
        if speed is None:
            return False

        current_speed = float(speed)
        while self._recent_speeds and now - self._recent_speeds[0][0] > 0.5:
            self._recent_speeds.popleft()

        prior_peak = max((past_speed for _timestamp, past_speed in self._recent_speeds), default=current_speed)
        self._recent_speeds.append((now, current_speed))
        if now - self._last_collision_at < 0.9:
            return False
        if prior_peak < 5.0:
            return False
        if current_speed <= prior_peak * 0.2:
            self._last_collision_at = now
            return True
        return False

    def _lap_event(self, snapshot: TelemetrySnapshot) -> Optional[int]:
        lap_count = snapshot.get("lap_count")
        current_lap = None if lap_count is None else int(lap_count)
        previous_lap = self._last_lap_count
        self._last_lap_count = current_lap

        if current_lap is None or current_lap == previous_lap:
            return None
        if previous_lap is None and current_lap == 0:
            return LAP_EVENT_PREPARE
        if previous_lap == 0 and current_lap == 1:
            return LAP_EVENT_START

        laps_in_race = snapshot.get("laps_in_race")
        if laps_in_race is not None and current_lap == int(laps_in_race) + 1:
            return LAP_EVENT_FINISH
        return LAP_EVENT_PASS


def run(config: RuntimeLaunchConfig) -> int:
    console = LiveConsole()
    console.log(f"接続先PS5: {config.ip_address}")
    if config.trace_mode:
        console.log("トレース再生モード: CSV出力は行いません。")
    else:
        console.log(f"CSV出力先: {config.output_path}")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    warning_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    esp_manager = EspSerialManager(port_names=config.esp_ports, auto_bind_ps5_ip=(config.ip_address if config.auto_bind else None))
    esp_director = EspTelemetryDirector()
    source = build_telemetry_source(config.ip_address, config.log_trace_path)
    source.start()
    receiver = TelemetryReceiver(source)

    for ps5_ip, esp_id in config.bindings:
        esp_manager.bind(ps5_ip, esp_id)

    try:
        esp_manager.start()
        receiver.start()
        for message in esp_manager.drain_messages():
            console.log(message)

        with build_telemetry_sink(config.output_path, config.trace_mode) as sink:
            console.log("PS5への接続を開始しました。テレメトリ受信を待機しています...")
            last_drain_at = time.monotonic()

            while True:
                packet = receiver.take_latest()
                if receiver.error is not None:
                    raise receiver.error

                if packet is None:
                    now = time.monotonic()
                    if now - last_drain_at >= 1.0:
                        for msg in esp_manager.drain_messages():
                            console.log(msg)
                        last_drain_at = now
                    time.sleep(0.001)
                    continue

                snapshot = TELEMETRY_LAYOUT.resolve_packet(packet)
                log_snapshot_warnings(console, snapshot.warnings, warning_keys)
                sink.write_snapshot(snapshot)
                rows_written += 1
                console.status_from_snapshot(snapshot)
                now = time.monotonic()
                events = esp_director.update(snapshot, now)
                esp_snapshot = snapshot.with_values(play_state=esp_director.play_state)
                for event_id, value in events:
                    esp_manager.submit_event(config.ip_address, event_id, value)
                esp_manager.submit_telemetry(config.ip_address, esp_snapshot)

                if now - last_drain_at >= 1.0:
                    for msg in esp_manager.drain_messages():
                        console.log(msg)
                    last_drain_at = now

                if not config.trace_mode and (rows_written == 1 or rows_written % 100 == 0):
                    console.log(f"{rows_written}行を記録しました。")

    except KeyboardInterrupt:
        console.log("")
        console.log("記録を停止しました。")
    except Exception as exc:
        print(f"実行中にエラーが発生しました: {exc}", file=sys.stderr)
        return 1
    finally:
        esp_manager.stop()
        receiver.stop()
        source.close()
        console.finish()

    if not config.trace_mode:
        print(f"CSV保存完了: {config.output_path}")
    return 0


def main() -> int:
    try:
        config = load_runtime_config()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return run(config)
