from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from gt7_config import CSV_COLUMNS
from gt7_formatting import packet_to_row


class TelemetryCsvWriter:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._file.flush()

    def write_packet(self, packet: Any) -> None:
        self._writer.writerow(packet_to_row(packet))
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "TelemetryCsvWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()