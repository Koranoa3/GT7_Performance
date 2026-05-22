from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple

import serial
from serial.tools import list_ports

from gt7_config import ESP_BAUD_RATE, ESP_RATE_LIMIT_HZ
from gt7_formatting import TELEMETRY_LAYOUT, TelemetrySnapshot
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
        self._pending_packets: Dict[str, Tuple[int, TelemetrySnapshot]] = {}
        self._messages: Deque[str] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._auto_bind_ps5_ip = auto_bind_ps5_ip
        self._restart_requested = False
        self._port_scan_interval = 1.0
        self._last_port_scan_at = 0.0
        self._last_detected_ports: Tuple[str, ...] = tuple()
        self._denied_ports: Set[str] = set()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._restart_requested = False
            self._denied_ports.clear()
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
            self._restart_requested = False
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

    def submit_telemetry(self, ps5_ip: str, snapshot: TelemetrySnapshot) -> None:
        packet_id = int(snapshot.get("packet_id", 0) or 0)
        with self._lock:
            self._pending_packets[ps5_ip] = (packet_id, snapshot)

    def submit_event(self, ps5_ip: str, event_id: int, value: int) -> None:
        with self._lock:
            for link in self._links.values():
                if link.bound_ps5_ip != ps5_ip:
                    continue
                self._send_event_locked(link, event_id, value)

    def drain_messages(self) -> List[str]:
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
            return messages

    def has_open_links(self) -> bool:
        with self._lock:
            return bool(self._links)

    def scan_ports(self, now: Optional[float] = None, force: bool = False) -> bool:
        with self._lock:
            return self._scan_ports_locked(now=now, force=force)

    def consume_restart_request(self) -> bool:
        with self._lock:
            requested = self._restart_requested
            self._restart_requested = False
            return requested

    def has_reconnect_candidate(self) -> bool:
        try:
            available_ports = {port.device for port in list_ports.comports()}
        except Exception:
            return False

        if self._requested_ports:
            return any(port_name in available_ports for port_name in self._requested_ports)
        return bool(available_ports)

    def _open_links_locked(self) -> None:
        self._scan_ports_locked(force=True)

    def _scan_ports_locked(self, now: Optional[float] = None, force: bool = False) -> bool:
        scan_time = time.monotonic() if now is None else now
        if not force and scan_time - self._last_port_scan_at < self._port_scan_interval:
            return False
        self._last_port_scan_at = scan_time

        try:
            detected_ports = [port.device for port in list_ports.comports()]
        except Exception as exc:
            self._messages.append(f"ESPポートのスキャンに失敗しました: {exc}")
            return False
        detected_set = set(detected_ports)
        if tuple(detected_ports) != self._last_detected_ports:
            if detected_ports:
                self._messages.append(f"ESPポートを検出しました: {', '.join(detected_ports)}")
            else:
                self._messages.append("ESPポートが見つかりませんでした。接続待機を継続します。")
            self._last_detected_ports = tuple(detected_ports)

        port_names = list(self._requested_ports)
        if port_names:
            port_names = [port_name for port_name in port_names if port_name in detected_set]
        else:
            port_names = detected_ports

        opened_any = False
        for port_name in port_names:
            if port_name in self._links:
                continue
            if port_name in self._denied_ports:
                continue
            try:
                serial_port = serial.Serial(port=port_name, baudrate=self._baudrate, timeout=0, write_timeout=0)
            except Exception as exc:
                self._denied_ports.add(port_name)
                self._messages.append(f"ESPポート {port_name} を開けませんでした: {exc}")
                self._messages.append(f"ESPポート {port_name} は今回の起動中は再試行しません。")
                continue
            self._links[port_name] = _LinkState(port_name=port_name, serial_port=serial_port)
            self._messages.append(f"ESPポート {port_name} を開きました。")
            opened_any = True
        return opened_any

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
            self._scan_ports_locked(now=now)
            links = list(self._links.values())
            pending = dict(self._pending_packets)
            bindings = dict(self._binding_by_esp_id)

        readable_links: List[_LinkState] = []
        for link in links:
            if self._read_link(link, now):
                readable_links.append(link)

        for link in readable_links:
            self._flush_link(link, pending, bindings, now)

    def _read_link(self, link: _LinkState, now: float) -> bool:
        try:
            waiting = link.serial_port.in_waiting
            if waiting:
                data = link.serial_port.read(waiting)
                for frame in link.parser.feed(data):
                    self._handle_frame(link, frame, now)
            return True
        except Exception as exc:
            with self._lock:
                link.last_error = str(exc)
                self._messages.append(f"{link.port_name} の読み取りに失敗しました: {exc}")
                self._reset_binding_locked(link)
            return False

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
        pending: Dict[str, Tuple[int, TelemetrySnapshot]],
        bindings: Dict[int, str],
        now: float,
    ) -> None:
        if link.esp_id is None:
            return

        ps5_ip = bindings.get(link.esp_id)
        if ps5_ip is None:
            return
        if link.bound_ps5_ip != ps5_ip:
            return

        pending_item = pending.get(ps5_ip)
        if pending_item is None:
            return

        packet_id, snapshot = pending_item
        if packet_id == link.last_sent_packet_id:
            return
        if link.last_sent_at and now - link.last_sent_at < self._min_interval:
            return

        payload = build_telemetry_payload(TELEMETRY_LAYOUT.build_esp_values(snapshot))
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
                self._reset_binding_locked(link)

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

    def _reset_binding_locked(self, link: _LinkState) -> None:
        released_ps5_ip = link.bound_ps5_ip
        registered_ps5_ip = self._binding_by_esp_id.get(link.esp_id) if link.esp_id is not None else None

        link.bound_ps5_ip = None
        link.last_sent_packet_id = -1
        self._restart_requested = True

        ps5_ip = released_ps5_ip or registered_ps5_ip
        if link.esp_id is not None and ps5_ip is not None:
            self._messages.append(
                f"ESP {link.esp_id} と PS5 {ps5_ip} の紐づけを解除しました。再度バインド受付状態に戻します。"
            )
        elif link.esp_id is not None:
            self._messages.append(f"ESP {link.esp_id} を再度バインド受付状態に戻します。")
