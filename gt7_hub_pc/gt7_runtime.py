from __future__ import annotations

import argparse
import datetime as dt
import queue
import threading
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from granturismo.intake import Listener

from gt7_console import LiveConsole
from gt7_esp_bridge import EspSerialManager
from gt7_writer import TelemetryCsvWriter


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
    def __init__(self, listener: Listener) -> None:
        self._listener = listener
        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=4)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
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

    def get(self, timeout: float = 0.05) -> Optional[object]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def _worker(self) -> None:
        try:
            with self._listener:
                while not self._stop_event.is_set():
                    try:
                        packet = self._listener.get(timeout=0.1)
                    except TimeoutError:
                        continue
                    except Exception as exc:
                        self._error = exc
                        break

                    if packet is None:
                        continue

                    try:
                        self._queue.put_nowait(packet)
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self._queue.put_nowait(packet)
                        except queue.Full:
                            pass
        except Exception as exc:
            self._error = exc


def run(
    ip_address: str,
    output_path: Path,
    esp_ports: List[str],
    bindings: List[Tuple[str, int]],
) -> int:
    console = LiveConsole()
    console.log(f"接続先PS5: {ip_address}")
    console.log(f"CSV出力先: {output_path}")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    esp_manager = EspSerialManager(port_names=esp_ports)
    listener = Listener(ip_address)
    receiver = TelemetryReceiver(listener)
    
    for ps5_ip, esp_id in bindings:
        esp_manager.bind(ps5_ip, esp_id)

    try:
        console.start()
        esp_manager.start()
        receiver.start()
        for message in esp_manager.drain_messages():
            console.log(message)

        with TelemetryCsvWriter(output_path, flush_every=10) as writer:
            console.log("PS5への接続を開始しました。テレメトリ受信を待機しています...")
            last_drain_at = time.monotonic()
            
            while True:
                packet = receiver.get(timeout=0.05)
                
                # Check for receiver errors
                if receiver.error is not None:
                    raise receiver.error
                
                if packet is None:
                    # No packet received; check if time to drain messages
                    now = time.monotonic()
                    if now - last_drain_at >= 1.0:
                        messages = esp_manager.drain_messages()
                        for msg in messages:
                            console.log(msg)
                        last_drain_at = now
                    continue

                # Process valid packet
                writer.write_packet(packet)
                rows_written += 1
                
                # Enqueue for async console rendering (non-blocking)
                console.enqueue_packet(packet)
                
                # Submit to ESP manager
                esp_manager.submit_telemetry(ip_address, packet)

                # Periodically drain messages from ESP manager (1 second interval)
                now = time.monotonic()
                if now - last_drain_at >= 1.0:
                    messages = esp_manager.drain_messages()
                    for msg in messages:
                        console.log(msg)
                    last_drain_at = now

                # Progress log every 100 packets
                if rows_written == 1 or rows_written % 100 == 0:
                    console.log(f"{rows_written}行を記録しました。")
                    
    except KeyboardInterrupt:
        console.log("")
        console.log("記録を停止しました。")
    except Exception as exc:
        print(f"実行中にエラーが発生しました: {exc}", file=sys.stderr)
        return 1
    finally:
        console.finish()
        esp_manager.stop()
        receiver.stop()

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
    return run(ip_address, output_path, args.esp_port, bindings)
