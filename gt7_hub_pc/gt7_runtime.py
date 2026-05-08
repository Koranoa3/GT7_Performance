from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Protocol

from granturismo.intake import Listener

from gt7_console import LiveConsole
from gt7_esp_bridge import EspSerialManager
from gt7_log_trace import LogTraceListener
from gt7_protocol import EVENT_GEAR_CHANGED
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


def run(config: RuntimeLaunchConfig) -> int:
    console = LiveConsole()
    console.log(f"接続先PS5: {config.ip_address}")
    if config.trace_mode:
        console.log("トレース再生モード: CSV出力は行いません。")
    else:
        console.log(f"CSV出力先: {config.output_path}")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    esp_manager = EspSerialManager(port_names=config.esp_ports, auto_bind_ps5_ip=(config.ip_address if config.auto_bind else None))
    last_gear: Optional[int] = None
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

                sink.write_packet(packet)
                rows_written += 1
                console.status_from_packet(packet)
                gear = getattr(packet, "current_gear", None)
                if gear is not None:
                    gear = int(gear)
                    if 0 <= gear <= 4:
                        if last_gear is None or gear != last_gear:
                            esp_manager.submit_event(config.ip_address, EVENT_GEAR_CHANGED, gear)
                        last_gear = gear
                esp_manager.submit_telemetry(config.ip_address, packet)

                now = time.monotonic()
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
