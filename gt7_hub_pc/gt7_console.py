from __future__ import annotations

import sys
from typing import Any

from gt7_formatting import TELEMETRY_LAYOUT, TelemetrySnapshot


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

    def status_from_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        values = TELEMETRY_LAYOUT.build_console_values(snapshot)
        self.status(" | ".join(values))

    def finish(self) -> None:
        self._clear_status_line()
        self._status_text = ""
