from __future__ import annotations

import sys
from typing import Any
import threading
import queue
from typing import Optional

from gt7_config import FLOAT_PRECISION_BY_FIELD, LOG_COLUMNS
from gt7_formatting import format_value, padded_number, safe_attr


class LiveConsole:
    def __init__(self, stream: Any = None) -> None:
        self.stream = stream or sys.stdout
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self._status_text = ""
        # async worker for rendering status lines
        self._queue: "queue.Queue[Optional[Any]]" = queue.Queue(maxsize=4)
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._lock = threading.Lock()

    def _write(self, text: str) -> None:
        with self._lock:
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

    def start(self) -> None:
        """Start background worker that renders status lines from a queue."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self, *, join_timeout: float = 1.0) -> None:
        """Stop background worker and drain queue."""
        if not self._thread:
            return
        if self._stop_event:
            self._stop_event.set()
        # try to wake the worker
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=join_timeout)
        self._thread = None
        self._stop_event = None

    def enqueue_packet(self, packet: Any) -> None:
        """Enqueue a packet for async status rendering. Drops packet if queue is full."""
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            # drop packet to preserve real-time; do not block
            return

    def _worker(self) -> None:
        while not (self._stop_event and self._stop_event.is_set()):
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                # render synchronously in worker thread
                self.status_from_packet(item)
            except Exception:
                # swallow exceptions in worker to avoid crashing main loop
                pass
        # clear any pending status text on exit
        self.finish()

    def log(self, message: str = "") -> None:
        # Ensure the status line is cleared before writing the log message,
        # then re-draw the status line with proper carriage return so it stays
        # as the last line (avoids leaving stray text when interleaved).
        self._clear_status_line()
        self._write(message + "\n")
        if self._status_text:
            # redraw status line at the start of the last line
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
