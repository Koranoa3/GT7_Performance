from __future__ import annotations

import argparse
import datetime as dt
import threading
import sys
import time
from pathlib import Path
from typing import List, Optional, Protocol, Tuple, Any

from granturismo.intake import Listener

from gt7_console import LiveConsole
from gt7_log_trace import LogTraceListener
from gt7_esp_bridge import EspSerialManager
from gt7_protocol import EVENT_GEAR_CHANGED
from gt7_writer import NullTelemetrySink, TelemetryCsvSink, TelemetrySink


class TelemetrySource(Protocol):
    def start(self) -> None:
        ...

    def close(self) -> None:
        ...

    def get(self, timeout: Optional[float] = None) -> Any:
        ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gran Turismo 7 telemetry collector for PS5 -> CSV logging."
    )
    parser.add_argument(
        "ip_address",
        nargs="?",
        help="PS5のIPアドレス。未指定なら起動時に入力を求めます。",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        default=None,
        help="records/ に保存したCSVを疑似トレース入力として使います。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSVの出力先。未指定の場合は records/ にタイムスタンプ付きで保存します。",
    )
    parser.add_argument(
        "--esp-port",
        action="append",
        default=[],
        help="ESP32 のシリアルポート。複数指定可。未指定なら接続可能なポートを自動探索します。",
    )
    parser.add_argument(
        "--bind",
        action="append",
        default=[],
        help="手動紐づけ。形式は PS5_IP:ESP_ID です。複数指定可。",
    )
    return parser


def resolve_ip_address(value: Optional[str]) -> str:
    if value:
        return value.strip()
    return input("PS5のIPアドレスを入力してください: ").strip()


def default_output_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("records") / f"gt7_telemetry_{stamp}.csv"


def parse_bindings(values: List[str]) -> List[Tuple[str, int]]:
    bindings: List[Tuple[str, int]] = []
    for raw in values:
        value = raw.strip()
        if not value:
            continue
        if ":" not in value:
            raise ValueError(f"無効な紐づけ指定です: {raw}")
        ps5_ip, esp_id_text = value.split(":", 1)
        ps5_ip = ps5_ip.strip()
        esp_id_text = esp_id_text.strip()
        if not ps5_ip or not esp_id_text:
            raise ValueError(f"無効な紐づけ指定です: {raw}")
        bindings.append((ps5_ip, int(esp_id_text)))
    return bindings


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


def run(
    ip_address: str,
    log_trace_path: Optional[Path],
    output_path: Path,
    esp_ports: List[str],
    bindings: List[Tuple[str, int]],
) -> int:
    console = LiveConsole()
    console.log(f"接続先PS5: {ip_address}")
    trace_mode = log_trace_path is not None
    if trace_mode:
        console.log("トレース再生モード: CSV出力は行いません。")
    else:
        console.log(f"CSV出力先: {output_path}")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    esp_manager = EspSerialManager(port_names=esp_ports)
    last_gear: Optional[int] = None
    source = build_telemetry_source(ip_address, log_trace_path)
    source.start()
    receiver = TelemetryReceiver(source)

    for ps5_ip, esp_id in bindings:
        esp_manager.bind(ps5_ip, esp_id)

    try:
        esp_manager.start()
        receiver.start()
        for message in esp_manager.drain_messages():
            console.log(message)

        with build_telemetry_sink(output_path, trace_mode) as sink:
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
                            esp_manager.submit_event(ip_address, EVENT_GEAR_CHANGED, gear)
                        last_gear = gear
                esp_manager.submit_telemetry(ip_address, packet)

                now = time.monotonic()
                if now - last_drain_at >= 1.0:
                    for msg in esp_manager.drain_messages():
                        console.log(msg)
                    last_drain_at = now

                if not trace_mode and (rows_written == 1 or rows_written % 100 == 0):
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

    if not trace_mode:
        print(f"CSV保存完了: {output_path}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    ip_address = resolve_ip_address(args.ip_address)
    if not ip_address:
        print("IPアドレスが空です。", file=sys.stderr)
        return 1

    output_path = args.output or default_output_path()
    try:
        bindings = parse_bindings(args.bind)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return run(ip_address, args.trace, output_path, args.esp_port, bindings)
