from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional, Protocol

from granturismo.intake import Listener, ReadError, SocketNotBoundError

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


class SafeListener(Listener):
    """Listener variant that keeps retrying heartbeat sends on transient socket errors."""

    def _send_heartbeat(self) -> None:
        last_heartbeat = 0.0
        retry_delay = 1.0
        while not self._terminate_event.is_set():
            curr_time = time.time()
            if curr_time - last_heartbeat < self._HEARTBEAT_DELAY:
                remaining = min(self._HEARTBEAT_DELAY - (curr_time - last_heartbeat), 0.1)
                self._terminate_event.wait(max(remaining, 0.01))
                continue

            try:
                self._sock.sendto(self._HEARTBEAT_MESSAGE, (self._addr, self._HEARTBEAT_PORT))
            except OSError:
                if self._terminate_event.wait(retry_delay):
                    break
                retry_delay = min(retry_delay * 2.0, 10.0)
                continue

            last_heartbeat = curr_time
            retry_delay = 1.0

        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock_bounded = False


class RecoveringTelemetrySource:
    """Wraps the live Listener and recreates it after transient socket failures."""

    def __init__(self, ip_address: str) -> None:
        self._ip_address = ip_address
        self._lock = threading.Lock()
        self._listener: Optional[SafeListener] = None
        self._closed = False
        self._next_retry_at = 0.0
        self._retry_delay = 1.0

    def start(self) -> None:
        self._closed = False
        self._ensure_listener(force_new=True)

    def close(self) -> None:
        self._closed = True
        listener = self._swap_listener(None)
        if listener is not None:
            listener.close()

    def get(self, timeout: Optional[float] = None) -> Any:
        deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
        while True:
            if self._closed:
                raise TimeoutError("Telemetry source is closed")

            listener = self._ensure_listener()
            if listener is None:
                if self._wait_for_retry(deadline):
                    raise TimeoutError("Telemetry source is reconnecting")
                continue

            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                return listener.get(timeout=remaining)
            except TimeoutError:
                raise
            except (ReadError, SocketNotBoundError, OSError):
                self._recover_listener(listener)
                if self._wait_for_retry(deadline):
                    raise TimeoutError("Telemetry source is reconnecting")

    def _ensure_listener(self, force_new: bool = False) -> Optional[SafeListener]:
        previous: Optional[SafeListener] = None
        with self._lock:
            if self._listener is not None and not force_new:
                return self._listener
            if self._closed:
                return None
            if not force_new and time.monotonic() < self._next_retry_at:
                return None
            previous = self._listener
            listener = SafeListener(self._ip_address)
            self._listener = listener

        try:
            listener.start()
            self._retry_delay = 1.0
            self._next_retry_at = 0.0
            if previous is not None and previous is not listener:
                previous.close()
            return listener
        except Exception:
            self._recover_listener(listener)
            return None

    def _recover_listener(self, listener: SafeListener) -> None:
        current = self._swap_listener(None)
        if current is not None and current is not listener:
            current.close()
        try:
            listener.close()
        except Exception:
            pass
        self._schedule_retry()

    def _swap_listener(self, listener: Optional[SafeListener]) -> Optional[SafeListener]:
        with self._lock:
            previous = self._listener
            self._listener = listener
            return previous

    def _schedule_retry(self) -> None:
        self._next_retry_at = time.monotonic() + self._retry_delay
        self._retry_delay = min(self._retry_delay * 2.0, 10.0)

    def _wait_for_retry(self, deadline: Optional[float]) -> bool:
        if self._closed:
            return True

        now = time.monotonic()
        wait_seconds = max(0.0, self._next_retry_at - now)
        if deadline is not None:
            wait_seconds = min(wait_seconds, max(0.0, deadline - now))

        if wait_seconds <= 0.0:
            return False

        time.sleep(min(wait_seconds, 0.1))
        return deadline is not None and time.monotonic() >= deadline


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
    return RecoveringTelemetrySource(ip_address)


def build_telemetry_sink(output_path: Path, trace_mode: bool, record_enabled: bool) -> TelemetrySink:
    if trace_mode or not record_enabled:
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
        self._recent_motion_samples: deque[tuple[float, float, float]] = deque(maxlen=32)
        self._last_lap_count: Optional[int] = None
        self._last_collision_at = 0.0
        self.play_state = 0

    def update(self, snapshot: TelemetrySnapshot, now: float) -> list[tuple[int, int]]:
        self.play_state = self._resolve_play_state(snapshot)
        events: list[tuple[int, int]] = []

        if self.play_state == 1:
            collision_strength = self._collision_strength(snapshot, now)
            if collision_strength is not None:
                events.append((EVENT_COLLISION, collision_strength))
            lap_event = self._lap_event(snapshot)
            if lap_event is not None:
                events.append((EVENT_LAP, lap_event))
        else:
            self._lap_event(snapshot)

        return events

    def _resolve_play_state(self, snapshot: TelemetrySnapshot) -> int:
        paused = bool(snapshot.get("paused", False))
        laps_in_race = snapshot.get("laps_in_race")
        same_speed = self._speed_is_stale(snapshot)

        if paused or same_speed:
            return 0

        if laps_in_race is None:
            return 0

        try:
            total_laps = int(laps_in_race)
        except (TypeError, ValueError):
            return 0

        if total_laps <= 0:
            return 0

        return 1

    def _speed_is_stale(self, snapshot: TelemetrySnapshot) -> bool:
        return False # !FORCE
        speed = snapshot.get("car_speed")
        if speed is None:
            return True

        current = float(speed)
        samples = [current]
        for _timestamp, past_speed in list(self._recent_speeds)[-4:]:
            samples.append(past_speed)
        return len(samples) >= 5 and len(set(samples)) == 1

    def _collision_strength(self, snapshot: TelemetrySnapshot, now: float) -> Optional[int]:
        speed = snapshot.get("car_speed")
        if speed is None:
            return None

        current_speed = float(speed)
        while self._recent_speeds and now - self._recent_speeds[0][0] > 0.5:
            self._recent_speeds.popleft()

        prior_peak = max((past_speed for _timestamp, past_speed in self._recent_speeds), default=current_speed)
        self._recent_speeds.append((now, current_speed))
        speed_delta = max(prior_peak - current_speed, 0.0)

        velocity_right = snapshot.get("velocity_right")
        velocity_forward = snapshot.get("velocity_forward")
        current_gear = snapshot.get("current_gear")
        lateral_delta = 0.0
        longitudinal_delta = 0.0

        if velocity_right is not None and velocity_forward is not None and current_gear is not None:
            current_velocity_right = float(velocity_right)
            current_velocity_forward = float(velocity_forward)

            while self._recent_motion_samples and now - self._recent_motion_samples[0][0] > 0.2:
                self._recent_motion_samples.popleft()

            lateral_delta = max(
                (
                    abs(current_velocity_right - past_velocity_right)
                    for _timestamp, past_velocity_right, _past_velocity_forward in self._recent_motion_samples
                ),
                default=0.0,
            )
            longitudinal_delta = max(
                (
                    abs(current_velocity_forward - past_velocity_forward)
                    for _timestamp, _past_velocity_right, past_velocity_forward in self._recent_motion_samples
                ),
                default=0.0,
            )
            self._recent_motion_samples.append((now, current_velocity_right, current_velocity_forward))

        if now - self._last_collision_at < 0.9:
            return None

        speed_collision = prior_peak >= 5.0 and current_speed <= prior_peak * 0.2
        lateral_collision = lateral_delta >= 5.0 and (current_gear is not None and current_gear > 1)
        longitudinal_collision = longitudinal_delta >= 10.0 and (current_gear is not None and current_gear > 2)

        if not (speed_collision or lateral_collision or longitudinal_collision):
            return None

        strength = max(
            self._scale_collision_strength(lateral_delta, 5.0) if lateral_collision else 0,
            self._scale_collision_strength(longitudinal_delta, 10.0) if longitudinal_collision else 0,
            self._scale_collision_strength(speed_delta, 5.0) if speed_delta > 0.0 else 0,
        )

        if strength <= 0:
            return None

        self._last_collision_at = now
        return strength

    @staticmethod
    def _scale_collision_strength(delta_mps: float, minimum_delta_mps: float) -> int:
        if delta_mps < minimum_delta_mps:
            return 0

        capped_delta = min(delta_mps, 40.0)
        if capped_delta <= minimum_delta_mps:
            return 1

        normalized = (capped_delta - minimum_delta_mps) / (40.0 - minimum_delta_mps)
        return int(round(1.0 + normalized * 254.0))

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
    elif config.record_enabled:
        console.log(f"CSV出力先: {config.output_path}")
    else:
        console.log("CSV記録: 無効（`--record` で有効化）")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    warning_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    esp_manager = EspSerialManager(port_names=config.esp_ports, auto_bind_ps5_ip=(config.ip_address if config.auto_bind else None))
    esp_director = EspTelemetryDirector()
    source = build_telemetry_source(config.ip_address, config.log_trace_path)
    source.start()
    receiver = TelemetryReceiver(source)
    esp_manager_running = False
    esp_reconnect_wait_logged = False
    next_esp_restart_check_at = 0.0

    for ps5_ip, esp_id in config.bindings:
        esp_manager.bind(ps5_ip, esp_id)

    def drain_esp_messages() -> None:
        for message in esp_manager.drain_messages():
            console.log(message)

    def refresh_esp_bridge(now: float) -> None:
        nonlocal esp_manager_running, esp_reconnect_wait_logged, next_esp_restart_check_at

        if esp_manager.consume_restart_request():
            if esp_manager_running:
                esp_manager.stop()
                esp_manager_running = False
                drain_esp_messages()
                console.log("ESPのバインド解除を検知したため、ESPブリッジを停止しました。再接続を待機します。")
            esp_reconnect_wait_logged = False
            next_esp_restart_check_at = now + 1.0

        if esp_manager_running or now < next_esp_restart_check_at:
            return

        next_esp_restart_check_at = now + 1.0
        esp_manager.scan_ports(now=now, force=True)
        if not esp_manager.has_open_links():
            if not esp_reconnect_wait_logged:
                console.log("ESPの再接続を待機しています...")
                esp_reconnect_wait_logged = True
            drain_esp_messages()
            return

        console.log("ESPの再接続を確認しました。ESPブリッジを再開します。")
        esp_manager.start()
        esp_manager_running = esp_manager.has_open_links()
        if not esp_manager_running:
            esp_manager.stop()
            drain_esp_messages()
            return
        esp_reconnect_wait_logged = False
        drain_esp_messages()

    try:
        esp_manager.start()
        esp_manager_running = esp_manager.has_open_links()
        if not esp_manager_running:
            esp_manager.stop()
            next_esp_restart_check_at = time.monotonic() + 1.0
        receiver.start()
        drain_esp_messages()

        with build_telemetry_sink(config.output_path, config.trace_mode, config.record_enabled) as sink:
            console.log("PS5への接続を開始しました。テレメトリ受信を待機しています...")
            last_drain_at = time.monotonic()

            while True:
                now = time.monotonic()
                refresh_esp_bridge(now)
                packet = receiver.take_latest()
                if receiver.error is not None:
                    raise receiver.error

                if packet is None:
                    if now - last_drain_at >= 1.0:
                        drain_esp_messages()
                        last_drain_at = now
                    time.sleep(0.001)
                    continue

                snapshot = TELEMETRY_LAYOUT.resolve_packet(packet)
                log_snapshot_warnings(console, snapshot.warnings, warning_keys)
                sink.write_snapshot(snapshot)
                if config.record_enabled and not config.trace_mode:
                    rows_written += 1
                console.status_from_snapshot(snapshot)
                events = esp_director.update(snapshot, now)
                esp_snapshot = snapshot.with_values(play_state=esp_director.play_state)
                if esp_manager_running:
                    for event_id, value in events:
                        esp_manager.submit_event(config.ip_address, event_id, value)
                    esp_manager.submit_telemetry(config.ip_address, esp_snapshot)

                if now - last_drain_at >= 1.0:
                    drain_esp_messages()
                    last_drain_at = now

                if config.record_enabled and not config.trace_mode and (rows_written == 1 or rows_written % 100 == 0):
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

    if config.record_enabled and not config.trace_mode:
        print(f"CSV保存完了: {config.output_path}")
    return 0


def main() -> int:
    try:
        config = load_runtime_config()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return run(config)
