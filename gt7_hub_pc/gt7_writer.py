from __future__ import annotations

import csv
from pathlib import Path
from typing import Protocol

from gt7_formatting import CSV_TARGET, TELEMETRY_LAYOUT, TelemetrySnapshot

class TelemetrySink(Protocol):
    def write_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        ...

    def close(self) -> None:
        ...

    def __enter__(self) -> "TelemetrySink":
        ...

    def __exit__(self, *_: object) -> None:
        ...


class TelemetryCsvWriter:
    def __init__(self, output_path: Path, flush_every: int = 10) -> None:
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self.output_path = output_path
        self.flush_every = flush_every
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=TELEMETRY_LAYOUT.field_names(CSV_TARGET))
        self._writer.writeheader()
        self._file.flush()
        self._rows_since_flush = 0

    def write_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        self._writer.writerow(TELEMETRY_LAYOUT.build_csv_row(snapshot))
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


class TelemetryCsvSink:
    def __init__(self, output_path: Path, flush_every: int = 10) -> None:
        self._writer = TelemetryCsvWriter(output_path, flush_every=flush_every)

    def write_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        self._writer.write_snapshot(snapshot)

    def close(self) -> None:
        self._writer.close()

    def __enter__(self) -> "TelemetryCsvSink":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class NullTelemetrySink:
    def write_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "NullTelemetrySink":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
