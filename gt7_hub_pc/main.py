from __future__ import annotations

import argparse
import csv
import datetime as dt
import signal
import sys
from pathlib import Path
from typing import Any

if not hasattr(signal, "SIGQUIT"):
    signal.SIGQUIT = signal.SIGTERM
if not hasattr(signal, "SIGABRT"):
    signal.SIGABRT = signal.SIGTERM

from granturismo.intake import Listener


CSV_COLUMNS = [
    "logged_at",
    "packet_id",
    "received_time",
    "car_speed",
    "velocity_x",
    "velocity_y",
    "velocity_z",
    "angular_velocity_x",
    "angular_velocity_y",
    "angular_velocity_z",
    "engine_rpm",
    "rpm_alert_min",
    "rpm_alert_max",
    "throttle",
    "brake",
    "turbo_boost",
    "current_gear",
    "in_race",
    "cars_in_race",
    "lap_count",
    "laps_in_race",
    "best_lap_time",
    "last_lap_time",
    "rotation_yaw",
    "paused",
]

FLOAT_PRECISION_BY_FIELD = {
    "car_speed": 3,
    "velocity_x": 3,
    "velocity_y": 3,
    "velocity_z": 3,
    "angular_velocity_x": 3,
    "angular_velocity_y": 3,
    "angular_velocity_z": 3,
    "engine_rpm": 0,
    "rpm_alert_min": 0,
    "rpm_alert_max": 0,
    "turbo_boost": 3,
}


def _now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def _safe_attr(value: Any, *path: str, default: Any = "") -> Any:
    current = value
    for name in path:
        if current is None:
            return default
        current = getattr(current, name, None)
    if current is None:
        return default
    return current


def _csv_value(value: Any) -> Any:
    # kept for backward compatibility; prefer _format_value(name, value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def _format_value(name: str, value: Any) -> Any:
    """Format value for CSV based on column name: rounds floats and converts bools to ints."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    # Integers leave as-is
    if isinstance(value, int):
        return value
    # Floats: choose precision by name
    if isinstance(value, float):
        lname = name.lower()
        # RPM and similar: integer
        if "rpm" in lname:
            return int(round(value))
        # small physical quantities and speeds: 3 decimal places
        if any(k in lname for k in ("speed", "velocity", "angular", "orientation", "distance", "height", "turbo", "road")):
            return round(value, 3)
        # fallback: 3 decimals
        return round(value, 3)
    return value


def _csv_number(value: Any, digits: int) -> Any:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return int(value)

    number = float(value)
    if digits == 0:
        return int(round(number))

    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _packet_to_row(packet: Any) -> dict[str, Any]:
    row = {
        "logged_at": _now_local_iso(),
        "packet_id": _format_value("packet_id", getattr(packet, "packet_id", "")),
        "received_time": _format_value("received_time", getattr(packet, "received_time", "")),
        "car_speed": _format_value("car_speed", getattr(packet, "car_speed", "")),
        "velocity_x": _format_value("velocity_x", _safe_attr(packet, "velocity", "x")),
        "velocity_y": _format_value("velocity_y", _safe_attr(packet, "velocity", "y")),
        "velocity_z": _format_value("velocity_z", _safe_attr(packet, "velocity", "z")),
        "angular_velocity_x": _format_value("angular_velocity_x", _safe_attr(packet, "angular_velocity", "x")),
        "angular_velocity_y": _format_value("angular_velocity_y", _safe_attr(packet, "angular_velocity", "y")),
        "angular_velocity_z": _format_value("angular_velocity_z", _safe_attr(packet, "angular_velocity", "z")),
        "engine_rpm": _format_value("engine_rpm", getattr(packet, "engine_rpm", "")),
        "rpm_alert_min": _format_value("rpm_alert_min", _safe_attr(packet, "rpm_alert", "min")),
        "rpm_alert_max": _format_value("rpm_alert_max", _safe_attr(packet, "rpm_alert", "max")),
        "throttle": _format_value("throttle", getattr(packet, "throttle", "")),
        "brake": _format_value("brake", getattr(packet, "brake", "")),
        "turbo_boost": _format_value("turbo_boost", getattr(packet, "turbo_boost", "")),
        "current_gear": _format_value("current_gear", getattr(packet, "current_gear", "")),
        "in_race": _format_value("in_race", _safe_attr(packet, "flags", "in_race")),
        "cars_in_race": _format_value("cars_in_race", getattr(packet, "cars_in_race", "")),
        "lap_count": _format_value("lap_count", getattr(packet, "lap_count", "")),
        "laps_in_race": _format_value("laps_in_race", getattr(packet, "laps_in_race", "")),
        "best_lap_time": _format_value("best_lap_time", getattr(packet, "best_lap_time", "")),
        "last_lap_time": _format_value("last_lap_time", getattr(packet, "last_lap_time", "")),
        "rotation_yaw": _format_value("rotation_yaw", _safe_attr(packet, "rotation", "yaw")),
        "paused": _format_value("paused", _safe_attr(packet, "flags", "paused")),
    }

    for field, digits in FLOAT_PRECISION_BY_FIELD.items():
        row[field] = _csv_number(row[field], digits)

    return row


class TelemetryCsvWriter:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._file.flush()

    def write_packet(self, packet: Any) -> None:
        self._writer.writerow(_packet_to_row(packet))
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "TelemetryCsvWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gran Turismo 7 telemetry collector for PS5 -> CSV logging."
    )
    parser.add_argument(
        "ip_address",
        nargs="?",
        help="PS5のIPアドレス。未指定なら起動時に入力を求めます。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSVの出力先。未指定の場合は records/ にタイムスタンプ付きで保存します。",
    )
    return parser


def resolve_ip_address(value: str | None) -> str:
    if value:
        return value.strip()
    return input("PS5のIPアドレスを入力してください: ").strip()


def default_output_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("records") / f"gt7_telemetry_{stamp}.csv"


def run(ip_address: str, output_path: Path) -> int:

    print(f"接続先PS5: {ip_address}")
    print(f"CSV出力先: {output_path}")
    print("終了するには Ctrl+C を押してください。")

    rows_written = 0
    try:
        with TelemetryCsvWriter(output_path) as writer:
            with Listener(ip_address) as listener:
                print("PS5への接続を開始しました。テレメトリ受信を待機しています...")
                while True:
                    packet = listener.get()
                    if packet is None:
                        continue
                    writer.write_packet(packet)
                    rows_written += 1
                    if rows_written == 1 or rows_written % 100 == 0:
                        print(f"{rows_written}行を記録しました。")
    except KeyboardInterrupt:
        print()
        print("記録を停止しました。")
    except Exception as exc:
        print(f"実行中にエラーが発生しました: {exc}", file=sys.stderr)
        return 1

    print(f"CSV保存完了: {output_path}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    ip_address = resolve_ip_address(args.ip_address)
    if not ip_address:
        print("IPアドレスが空です。", file=sys.stderr)
        return 1

    output_path = args.output or default_output_path()
    return run(ip_address, output_path)


if __name__ == "__main__":
    raise SystemExit(main())
