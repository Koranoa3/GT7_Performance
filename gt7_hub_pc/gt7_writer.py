from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from gt7_config import CSV_COLUMNS
from gt7_formatting import packet_to_row


class TelemetryCsvWriter:
    def __init__(self, output_path: Path, flush_every: int = 10) -> None:
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self.output_path = output_path
        self.flush_every = flush_every
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._file.flush()
        self._rows_since_flush = 0

    def write_packet(self, packet: Any) -> None:
        self._writer.writerow(packet_to_row(packet))
        self._rows_since_flush += 1
        if self._rows_since_flush >= self.flush_every:
            self._file.flush()
            self._rows_since_flush = 0

    def close(self) -> None:
        if self._rows_since_flush:
            self._file.flush()
            self._rows_since_flush = 0
        self._file.close()

    def __enter__(self) -> "TelemetryCsvWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
