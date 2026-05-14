from __future__ import annotations

import ctypes
import re
import sys
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import serial
from serial.tools import list_ports

from gt7_config import ESP_BAUD_RATE
from gt7_protocol import (
    FrameParser,
    FrameType,
    LED_STRIP_BASE,
    LED_STRIP_MONITOR,
    build_frame,
    build_section_preview_payload,
)

DEFAULT_BASE_LED_COUNT = 60
DEFAULT_MONITOR_LED_COUNT = 60
PREVIEW_REFRESH_SECONDS = 1.0
BOOT_WAIT_SECONDS = 1.2


@dataclass(frozen=True)
class StripOption:
    strip_id: int
    label: str
    led_count: int


@dataclass(frozen=True)
class SerialSelection:
    device: str
    description: str


def enable_virtual_terminal() -> None:
    if sys.platform != "win32":
        return

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)
    if handle == 0:
        return

    mode = ctypes.c_uint()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return

    kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def load_led_counts() -> tuple[int, int]:
    repo_root = Path(__file__).resolve().parents[1]
    platformio_path = repo_root / "gt7_seat_esp" / "platformio.ini"
    if not platformio_path.exists():
        return DEFAULT_BASE_LED_COUNT, DEFAULT_MONITOR_LED_COUNT

    text = platformio_path.read_text(encoding="utf-8")
    base_match = re.search(r"-DGT7_BASE_LED_COUNT=(\d+)", text)
    monitor_match = re.search(r"-DGT7_MONITOR_LED_COUNT=(\d+)", text)
    base_count = int(base_match.group(1)) if base_match else DEFAULT_BASE_LED_COUNT
    monitor_count = int(monitor_match.group(1)) if monitor_match else DEFAULT_MONITOR_LED_COUNT
    return base_count, monitor_count


def port_is_likely_esp(port_info) -> bool:
    text = " ".join(
        part for part in (port_info.device, port_info.description, port_info.manufacturer, port_info.hwid) if part
    ).lower()
    keywords = ("esp32", "espressif", "cp210", "ch340", "usb serial", "uart", "wch")
    return any(keyword in text for keyword in keywords)


def auto_select_port() -> SerialSelection:
    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("シリアルポートが見つかりませんでした。ESP32 を接続してください。")

    selected = next((port for port in ports if port_is_likely_esp(port)), ports[0])
    description = selected.description or selected.manufacturer or selected.device
    return SerialSelection(device=selected.device, description=description)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


class PreviewSerialClient:
    def __init__(self, selection: SerialSelection, baudrate: int = ESP_BAUD_RATE) -> None:
        self.selection = selection
        self.serial_port = serial.Serial(selection.device, baudrate=baudrate, timeout=0, write_timeout=0.5)
        self.parser = FrameParser()
        self.device_id = 0
        self.next_seq = 1

        time.sleep(BOOT_WAIT_SECONDS)
        self.poll()

    def close(self) -> None:
        self.serial_port.close()

    def poll(self) -> None:
        waiting = self.serial_port.in_waiting
        if waiting <= 0:
            return

        data = self.serial_port.read(waiting)
        for frame_type, device_id, _seq, _payload in self.parser.feed(data):
            if device_id:
                self.device_id = device_id
            if frame_type == FrameType.PING:
                self._send_frame(FrameType.PONG, b"")

    def send_preview(self, strip_id: int, start_index: int, end_index: int) -> None:
        payload = build_section_preview_payload(strip_id, start_index, end_index)
        self._send_frame(FrameType.SECTION_PREVIEW, payload)

    def _send_frame(self, frame_type: FrameType, payload: bytes) -> None:
        frame = build_frame(frame_type, self.device_id, seq=self.next_seq, payload=payload)
        self.next_seq = (self.next_seq + 1) & 0xFFFF
        self.serial_port.write(frame)
        self.serial_port.flush()


class KeyReader(AbstractContextManager):
    def __enter__(self) -> "KeyReader":
        return self

    def read_key(self, timeout: float) -> Optional[str]:
        raise NotImplementedError

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        return None


class WindowsKeyReader(KeyReader):
    def __init__(self) -> None:
        import msvcrt

        self._msvcrt = msvcrt

    def read_key(self, timeout: float) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._msvcrt.kbhit():
                time.sleep(0.02)
                continue

            key = self._msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                extended = self._msvcrt.getwch()
                return {
                    "H": "up",
                    "P": "down",
                    "K": "left",
                    "M": "right",
                }.get(extended)
            if key == "\x03":
                raise KeyboardInterrupt
            if key in ("a", "A"):
                return "toggle"
        return None


class PosixKeyReader(KeyReader):
    def __init__(self) -> None:
        import termios
        import tty

        self._select = __import__("select")
        self._termios = termios
        self._tty = tty
        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)

    def __enter__(self) -> "PosixKeyReader":
        self._tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old_settings)
        return None

    def read_key(self, timeout: float) -> Optional[str]:
        ready, _, _ = self._select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None

        char = sys.stdin.read(1)
        if char == "\x03":
            raise KeyboardInterrupt
        if char in ("a", "A"):
            return "toggle"
        if char != "\x1b":
            return None

        sequence = char
        ready, _, _ = self._select.select([sys.stdin], [], [], 0.02)
        if not ready:
            return None
        sequence += sys.stdin.read(1)
        ready, _, _ = self._select.select([sys.stdin], [], [], 0.02)
        if not ready:
            return None
        sequence += sys.stdin.read(1)

        return {
            "\x1b[A": "up",
            "\x1b[B": "down",
            "\x1b[D": "left",
            "\x1b[C": "right",
        }.get(sequence)


def create_key_reader() -> KeyReader:
    if sys.platform == "win32":
        return WindowsKeyReader()
    return PosixKeyReader()


def clear_screen() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def redraw_ui(selection: SerialSelection, strip: StripOption, start_index: int, end_index: int, selected_field: int, step: int) -> None:
    sys.stdout.write("\x1b[H\x1b[J")
    sys.stdout.write("GT7 LED section adjustment\n")
    sys.stdout.write(f"Serial : {selection.device} ({selection.description})\n")
    sys.stdout.write(f"Strip  : {strip.label} / 0..{strip.led_count - 1}\n")
    sys.stdout.write(f"Step   : {step}\n")
    sys.stdout.write("Keys   : Up/Down select, Left/Right adjust, A toggle step, Ctrl+C exit\n\n")
    sys.stdout.write(f"{'>' if selected_field == 0 else ' '} Start : {start_index}\n")
    sys.stdout.write(f"{'>' if selected_field == 1 else ' '} End   : {end_index}\n\n")
    sys.stdout.write("この数値を目視で確認して led_renderer.h に反映してください。\n")
    sys.stdout.flush()


def prompt_strip_choice(base_count: int, monitor_count: int) -> StripOption:
    options = {
        "0": StripOption(strip_id=LED_STRIP_BASE, label="BASE", led_count=base_count),
        "1": StripOption(strip_id=LED_STRIP_MONITOR, label="MONITOR", led_count=monitor_count),
    }
    while True:
        print("対象LEDテープを選択してください")
        print(f"  0: BASE ({base_count} LEDs)")
        print(f"  1: MONITOR ({monitor_count} LEDs)")
        choice = input("選択 [0/1]: ").strip()
        if choice in options:
            return options[choice]
        print("0 か 1 を入力してください。\n")


def run_adjustment_loop(client: PreviewSerialClient, strip: StripOption) -> None:
    start_index = 0
    end_index = strip.led_count - 1
    selected_field = 0
    step = 1
    dirty = True
    last_sent_at = 0.0

    enable_virtual_terminal()
    clear_screen()
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    try:
        with create_key_reader() as reader:
            redraw_ui(client.selection, strip, start_index, end_index, selected_field, step)
            while True:
                client.poll()
                now = time.monotonic()
                if dirty or (now - last_sent_at) >= PREVIEW_REFRESH_SECONDS:
                    client.send_preview(strip.strip_id, start_index, end_index)
                    last_sent_at = now
                    dirty = False

                key = reader.read_key(0.1)
                if key is None:
                    continue
                if key == "up":
                    selected_field = 0
                elif key == "down":
                    selected_field = 1
                elif key == "toggle":
                    step = 10 if step == 1 else 1
                elif key == "left":
                    if selected_field == 0:
                        start_index = clamp(start_index - step, 0, strip.led_count - 1)
                    else:
                        end_index = clamp(end_index - step, 0, strip.led_count - 1)
                elif key == "right":
                    if selected_field == 0:
                        start_index = clamp(start_index + step, 0, strip.led_count - 1)
                    else:
                        end_index = clamp(end_index + step, 0, strip.led_count - 1)
                else:
                    continue

                dirty = True
                redraw_ui(client.selection, strip, start_index, end_index, selected_field, step)
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def main() -> int:
    base_count, monitor_count = load_led_counts()
    selection = auto_select_port()
    print(f"ESP候補ポートを選択しました: {selection.device} ({selection.description})")
    print("ESP32 に接続しています...")

    client = PreviewSerialClient(selection)
    try:
        if client.device_id:
            print(f"ESP device_id: {client.device_id}")
        else:
            print("ESP device_id は未検出です。プレビュー送信は継続します。")

        strip = prompt_strip_choice(base_count, monitor_count)
        print("調整UIを開始します。")
        time.sleep(0.6)
        run_adjustment_loop(client, strip)
    except KeyboardInterrupt:
        print("\nadjustment tool を終了します。")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
