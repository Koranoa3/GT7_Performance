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
    build_bind_payload,
    build_frame,
    build_event_payload,
    build_telemetry_payload,
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
    last_sent_packet_id: int = -1
    next_seq: int = 1
    bound_ps5_ip: Optional[str] = None
    last_error: Optional[str] = None


class EspSerialManager:
    def __init__(
        self,
        port_names: Optional[Iterable[str]] = None,
        baudrate: int = ESP_BAUD_RATE,
        rate_limit_hz: float = ESP_RATE_LIMIT_HZ,
        auto_bind_ps5_ip: Optional[str] = None,
    ) -> None:
        self._requested_ports = list(port_names or [])
        self._baudrate = baudrate
        self._min_interval = 1.0 / float(rate_limit_hz)
        self._links: Dict[str, _LinkState] = {}
        self._binding_by_esp_id: Dict[int, str] = {}
        self._pending_packets: Dict[str, Tuple[int, object]] = {}
        self._messages: Deque[str] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._auto_bind_ps5_ip = auto_bind_ps5_ip

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
                self._send_bind_locked(link, ps5_ip)

    def submit_telemetry(self, ps5_ip: str, packet: object) -> None:
        packet_id = int(getattr(packet, "packet_id", 0) or 0)
        with self._lock:
            self._pending_packets[ps5_ip] = (packet_id, packet)

    def submit_event(self, ps5_ip: str, event_id: int, value: int) -> None:
        with self._lock:
            for link in self._links.values():
                if self._binding_by_esp_id.get(link.esp_id) != ps5_ip:
                    continue
                self._send_event_locked(link, event_id, value)

    def drain_messages(self) -> List[str]:
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
            return messages

    def _open_links_locked(self) -> None:
        port_names = list(self._requested_ports)
        if not port_names:
            port_names = [port.device for port in list_ports.comports()]
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
            pending = dict(self._pending_packets)
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
        frame_type, device_id, _seq, payload = frame
        link.last_seen_at = now
        if frame_type == FrameType.PING:
            link.esp_id = device_id
            link.last_ping_at = now
            with self._lock:
                if not link.bound_ps5_ip:
                    self._messages.append(f"ESP {device_id} を {link.port_name} で検出しました。")
                self._send_pong_locked(link)
                # 自動バインドが指定されていれば、登録されているバインディングがなくても自動で設定する
                binding = self._binding_by_esp_id.get(device_id)
                if binding is None and self._auto_bind_ps5_ip is not None:
                    self._binding_by_esp_id[int(device_id)] = self._auto_bind_ps5_ip
                    binding = self._auto_bind_ps5_ip
                    self._messages.append(f"ESP {device_id} を自動的に PS5 {self._auto_bind_ps5_ip} に紐づけます。")

                if binding is not None and link.bound_ps5_ip != binding:
                    self._send_bind_locked(link, binding)
        elif frame_type == FrameType.PONG:
            link.last_pong_at = now
        elif frame_type == FrameType.ACK:
            link.last_pong_at = now
            if payload:
                self._messages.append(f"ESP {device_id} から ACK を受信しました。")
        elif frame_type == FrameType.TELEMETRY:
            pass
        else:
            self._messages.append(f"ESP {device_id} から未知のフレーム {frame_type} を受信しました。")

    def _flush_link(
        self,
        link: _LinkState,
        pending: Dict[str, Tuple[int, object]],
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

        packet_id, packet = pending_item
        if packet_id == link.last_sent_packet_id:
            return
        if link.last_sent_at and now - link.last_sent_at < self._min_interval:
            return

        payload = build_telemetry_payload(packet)
        frame = build_frame(FrameType.TELEMETRY, link.esp_id, seq=link.next_seq, payload=payload)
        link.next_seq = (link.next_seq + 1) & 0xFFFF
        try:
            link.serial_port.write(frame)
            link.serial_port.flush()
            link.last_sent_at = now
            link.last_sent_packet_id = packet_id
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

    def _send_event_locked(self, link: _LinkState, event_id: int, value: int) -> None:
        if link.esp_id is None:
            return
        frame = build_frame(
            FrameType.EVENT,
            link.esp_id,
            seq=link.next_seq,
            payload=build_event_payload(event_id, value),
        )
        link.next_seq = (link.next_seq + 1) & 0xFFFF
        try:
            link.serial_port.write(frame)
            link.serial_port.flush()
        except Exception as exc:
            link.last_error = str(exc)
            self._messages.append(f"{link.port_name} への Event 送信に失敗しました: {exc}")

    def _find_link_by_esp_id_locked(self, esp_id: int) -> Optional[_LinkState]:
        for link in self._links.values():
            if link.esp_id == esp_id:
                return link
        return None
