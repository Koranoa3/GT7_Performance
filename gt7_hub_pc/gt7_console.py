from __future__ import annotations

import sys
from typing import Any

from gt7_config import FLOAT_PRECISION_BY_FIELD, LOG_COLUMNS
from gt7_formatting import format_value, padded_number, safe_attr


class StartupConsole:
    def __init__(self, stream: Any = None, input_func: Any = None) -> None:
        self.stream = stream or sys.stdout
        self.input_func = input_func or input

    def write(self, message: str = "") -> None:
        self.stream.write(message + "\n")
        self.stream.flush()

    def prompt(self, message: str) -> str:
        return str(self.input_func(message))

    def prompt_ip_address(self, current_value: str | None = None) -> str:
        if current_value and current_value.strip():
            return current_value.strip()
        return self.prompt("PS5のIPアドレスを入力してください: ").strip()

    def prompt_bindings(self) -> list[str]:
        bindings: list[str] = []
        self.write("手動紐づけを入力してください。空行で終了します。形式: PS5_IP:ESP_ID")
        while True:
            value = self.prompt("bind> ").strip()
            if not value:
                return bindings
            bindings.append(value)


class LiveConsole:
    def __init__(self, stream: Any = None) -> None:
        self.stream = stream or sys.stdout
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self._status_text = ""

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _clear_status_line(self) -> None:
        if self.enabled and self._status_text:
            self._write("\r\x1b[2K")

    def _format_log_value(self, column: str, value: Any) -> str:
        if value is None or value == "":
            return ""
        if column in FLOAT_PRECISION_BY_FIELD:
            return padded_number(value, FLOAT_PRECISION_BY_FIELD[column])
        if isinstance(value, bool):
            return str(int(value))
        return str(value)

    def log(self, message: str = "") -> None:
        self._clear_status_line()
        self._write(message + "\n")
        if self._status_text:
            self._write("\r\x1b[2K" + self._status_text)

    def status(self, text: str) -> None:
        if not self.enabled:
            return

        self._status_text = text
        self._write("\r\x1b[2K" + text)

    def status_from_packet(self, packet: Any) -> None:
        row = {
            "logged_at": getattr(packet, "logged_at", ""),
            "packet_id": format_value("packet_id", getattr(packet, "packet_id", "")),
            "car_speed": getattr(packet, "car_speed", ""),
            "throttle": getattr(packet, "throttle", ""),
            "velocity_x": safe_attr(packet, "velocity", "x"),
            "velocity_y": safe_attr(packet, "velocity", "y"),
            "velocity_z": safe_attr(packet, "velocity", "z"),
            "angular_velocity_x": safe_attr(packet, "angular_velocity", "x"),
            "angular_velocity_y": safe_attr(packet, "angular_velocity", "y"),
            "angular_velocity_z": safe_attr(packet, "angular_velocity", "z"),
            "turbo_boost": getattr(packet, "turbo_boost", ""),
            "current_gear": getattr(packet, "current_gear", ""),
        }
        values = [self._format_log_value(column, row[column]) for column in LOG_COLUMNS]
        self.status(" | ".join(values))

    def finish(self) -> None:
        self._clear_status_line()
        self._status_text = ""
