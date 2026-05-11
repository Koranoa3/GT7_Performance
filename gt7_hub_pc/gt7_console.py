from __future__ import annotations

import sys
from typing import Any

from gt7_formatting import CONSOLE_TARGET, TELEMETRY_LAYOUT, TelemetrySnapshot


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
        self._title_text = " | ".join(TELEMETRY_LAYOUT.field_names(CONSOLE_TARGET))
        self._status_text = ""
        self._status_visible = False

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _clear_status_block(self) -> None:
        if self.enabled and self._status_visible:
            self._write("\r\x1b[2K\x1b[1A\r\x1b[2K\r")
            self._status_visible = False

    def _render_status_block(self) -> None:
        if not self.enabled or not self._status_text:
            return
        if self._status_visible:
            self._write("\r\x1b[1A")
            self._write(self._title_text + "\x1b[K\n")
            self._write(self._status_text + "\x1b[K")
            return
        self._write(self._title_text + "\n" + self._status_text + "\x1b[K")
        self._status_visible = True

    def log(self, message: str = "") -> None:
        self._clear_status_block()
        self._write(message + "\n")
        if self._status_text:
            self._render_status_block()

    def status(self, text: str) -> None:
        if not self.enabled:
            return

        self._status_text = text
        self._render_status_block()

    def status_from_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        values = TELEMETRY_LAYOUT.build_console_values(snapshot)
        self.status(" | ".join(values))

    def finish(self) -> None:
        self._clear_status_block()
        self._status_text = ""
