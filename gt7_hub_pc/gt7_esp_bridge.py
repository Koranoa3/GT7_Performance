from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Tuple

import serial
from serial.tools import list_ports

from gt7_config import ESP_BAUD_RATE, ESP_RATE_LIMIT_HZ
from gt7_protocol import (
    FrameParser,
    FrameType,
    TelemetrySnapshot,
    build_bind_payload,
    build_frame,
    build_telemetry_payload,
    unpack_telemetry_payload,
    unpack_ipv4,
)


@dataclass
class _LinkState:
    port_name: str
    serial_port: serial.Serial
    parser: FrameParser = field(default_factory=FrameParser)
    esp_id: Optional[int] = None
    last_ping_at: float = 0.0
    last_pong_at: float = 0.0
    last_seen_at: float = 0.0
    last_sent_at: float = 0.0
    last_sent_generation: int = -1
    last_sent_source: Optional[str] = None
    next_seq: int = 1
    bound_ps5_ip: Optional[str] = None
    last_error: Optional[str] = None


class EspSerialManager:
    def __init__(
        self,
        port_names: Optional[Iterable[str]] = None,
        baudrate: int = ESP_BAUD_RATE,
        rate_limit_hz: float = ESP_RATE_LIMIT_HZ,
    ) -> None:
        self._requested_ports = list(port_names or [])
        self._baudrate = baudrate
        self._min_interval = 1.0 / float(rate_limit_hz)
        self._links: Dict[str, _LinkState] = {}
        self._binding_by_esp_id: Dict[int, str] = {}
        self._pending_telemetry: Dict[str, Tuple[int, TelemetrySnapshot]] = {}
        self._generation_by_source: Dict[str, int] = {}
        self._messages: Deque[str] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._auto_discovered = False

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._open_links_locked()
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker, name="gt7-esp-bridge", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            for link in self._links.values():
                try:
                    link.serial_port.close()
                except Exception:
                    pass
            self._links.clear()
            self._thread = None

    def bind(self, ps5_ip: str, esp_id: int) -> None:
        with self._lock:
            self._binding_by_esp_id[int(esp_id)] = ps5_ip
            self._messages.append(f"ESP {esp_id} に PS5 {ps5_ip} を紐づけ候補として登録しました。")
            link = self._find_link_by_esp_id_locked(int(esp_id))
            if link is not None:
                link.last_sent_generation = -1
                link.last_sent_source = None
                self._send_bind_locked(link, ps5_ip)

    def submit_telemetry(self, ps5_ip: str, packet: object) -> None:
        snapshot = packet if isinstance(packet, TelemetrySnapshot) else TelemetrySnapshot.from_packet(packet)
        with self._lock:
            generation = self._generation_by_source.get(ps5_ip, 0) + 1
            self._generation_by_source[ps5_ip] = generation
            self._pending_telemetry[ps5_ip] = (generation, snapshot)

    def drain_messages(self) -> List[str]:
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
            return messages

    def active_links(self) -> Dict[int, str]:
        with self._lock:
            result: Dict[int, str] = {}
            for link in self._links.values():
                if link.esp_id is not None:
                    result[link.esp_id] = link.port_name
            return result

    def _open_links_locked(self) -> None:
        port_names = list(self._requested_ports)
        if not port_names:
            port_names = [port.device for port in list_ports.comports()]
            self._auto_discovered = True
            if not port_names:
                self._messages.append("ESPポートが見つかりませんでした。接続後に再起動してください。")

        for port_name in port_names:
            if port_name in self._links:
                continue
            try:
                serial_port = serial.Serial(port=port_name, baudrate=self._baudrate, timeout=0, write_timeout=0)
            except Exception as exc:
                self._messages.append(f"ESPポート {port_name} を開けませんでした: {exc}")
                continue
            self._links[port_name] = _LinkState(port_name=port_name, serial_port=serial_port)
            self._messages.append(f"ESPポート {port_name} を開きました。")

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                with self._lock:
                    self._messages.append(f"ESPブリッジで予期しないエラーが発生しました: {exc}")
            time.sleep(0.01)

    def _poll_once(self) -> None:
        now = time.monotonic()
        with self._lock:
            links = list(self._links.values())
            pending = dict(self._pending_telemetry)
            bindings = dict(self._binding_by_esp_id)

        for link in links:
            self._read_link(link, now)

        for link in links:
            self._flush_link(link, pending, bindings, now)

    def _read_link(self, link: _LinkState, now: float) -> None:
        try:
            waiting = link.serial_port.in_waiting
            if waiting:
                data = link.serial_port.read(waiting)
                for frame in link.parser.feed(data):
                    self._handle_frame(link, frame, now)
        except Exception as exc:
            with self._lock:
                link.last_error = str(exc)
                self._messages.append(f"{link.port_name} の読み取りに失敗しました: {exc}")

    def _handle_frame(self, link: _LinkState, frame, now: float) -> None:
        link.last_seen_at = now
        if frame.frame_type == FrameType.PING:
            link.esp_id = frame.device_id
            link.last_ping_at = now
            with self._lock:
                self._messages.append(f"ESP {frame.device_id} を {link.port_name} で検出しました。")
                self._send_pong_locked(link)
                binding = self._binding_by_esp_id.get(frame.device_id)
                if binding is not None:
                    self._send_bind_locked(link, binding)
        elif frame.frame_type == FrameType.PONG:
            link.last_pong_at = now
            if frame.payload:
                pass
        elif frame.frame_type == FrameType.ACK:
            link.last_pong_at = now
            if frame.payload:
                try:
                    bound = unpack_ipv4(frame.payload)
                    link.bound_ps5_ip = bound
                    self._messages.append(f"ESP {frame.device_id} が PS5 {bound} との紐づけを受理しました。")
                except Exception:
                    self._messages.append(f"ESP {frame.device_id} から ACK を受信しました。")
        elif frame.frame_type == FrameType.TELEMETRY:
            try:
                snapshot = unpack_telemetry_payload(frame.payload)
                self._messages.append(
                    f"ESP {frame.device_id} からテレメトリ応答を受信しました: speed={snapshot.car_speed:.3f}"
                )
            except Exception:
                self._messages.append(f"ESP {frame.device_id} から未解析のテレメトリ応答を受信しました。")
        else:
            self._messages.append(f"ESP {frame.device_id} から未知のフレーム {frame.frame_type} を受信しました。")

    def _flush_link(
        self,
        link: _LinkState,
        pending: Dict[str, Tuple[int, TelemetrySnapshot]],
        bindings: Dict[int, str],
        now: float,
    ) -> None:
        if link.esp_id is None:
            return

        ps5_ip = bindings.get(link.esp_id)
        if ps5_ip is None:
            return

        pending_item = pending.get(ps5_ip)
        if pending_item is None:
            return

        generation, snapshot = pending_item
        if ps5_ip == link.last_sent_source and generation == link.last_sent_generation:
            return
        if link.last_sent_at and now - link.last_sent_at < self._min_interval:
            return

        payload = build_telemetry_payload(snapshot)
        frame = build_frame(FrameType.TELEMETRY, link.esp_id, seq=link.next_seq, payload=payload)
        link.next_seq = (link.next_seq + 1) & 0xFFFF
        try:
            link.serial_port.write(frame)
            link.serial_port.flush()
            link.last_sent_at = now
            link.last_sent_generation = generation
            link.last_sent_source = ps5_ip
        except Exception as exc:
            with self._lock:
                link.last_error = str(exc)
                self._messages.append(f"{link.port_name} へのテレメトリ送信に失敗しました: {exc}")

    def _send_pong_locked(self, link: _LinkState) -> None:
        if link.esp_id is None:
            return
        frame = build_frame(FrameType.PONG, link.esp_id, seq=link.next_seq)
        link.next_seq = (link.next_seq + 1) & 0xFFFF
        try:
            link.serial_port.write(frame)
        except Exception as exc:
            link.last_error = str(exc)
            self._messages.append(f"{link.port_name} への Pong 送信に失敗しました: {exc}")

    def _send_bind_locked(self, link: _LinkState, ps5_ip: str) -> None:
        if link.esp_id is None:
            return
        frame = build_frame(
            FrameType.BIND,
            link.esp_id,
            seq=link.next_seq,
            payload=build_bind_payload(ps5_ip),
        )
        link.next_seq = (link.next_seq + 1) & 0xFFFF
        try:
            link.serial_port.write(frame)
            link.serial_port.flush()
            link.bound_ps5_ip = ps5_ip
            self._messages.append(f"ESP {link.esp_id} へ PS5 {ps5_ip} の紐づけを送信しました。")
        except Exception as exc:
            link.last_error = str(exc)
            self._messages.append(f"{link.port_name} への Bind 送信に失敗しました: {exc}")

    def _find_link_by_esp_id_locked(self, esp_id: int) -> Optional[_LinkState]:
        for link in self._links.values():
            if link.esp_id == esp_id:
                return link
        return None
