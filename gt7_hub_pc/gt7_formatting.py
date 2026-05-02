from __future__ import annotations

import datetime as dt
from typing import Any

from gt7_config import FLOAT_PRECISION_BY_FIELD


def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def safe_attr(value: Any, *path: str, default: Any = "") -> Any:
    current = value
    for name in path:
        if current is None:
            return default
        current = getattr(current, name, None)
    if current is None:
        return default
    return current


def format_value(name: str, value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        lname = name.lower()
        if "rpm" in lname:
            return int(round(value))
        if any(
            key in lname
            for key in (
                "speed",
                "velocity",
                "angular",
                "orientation",
                "distance",
                "height",
                "turbo",
                "road",
            )
        ):
            return round(value, 3)
        return round(value, 3)
    return value


def csv_number(value: Any, digits: int) -> Any:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return int(value)

    number = float(value)
    if digits == 0:
        return int(round(number))

    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def padded_number(value: Any, digits: int) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return str(int(value))

    number = float(value)
    if digits == 0:
        return str(int(round(number)))

    return f"{number:.{digits}f}"


def packet_to_row(packet: Any) -> dict[str, Any]:
    row = {
        "logged_at": now_local_iso(),
        "packet_id": format_value("packet_id", getattr(packet, "packet_id", "")),
        "car_speed": format_value("car_speed", getattr(packet, "car_speed", "")),
        "velocity_x": format_value("velocity_x", safe_attr(packet, "velocity", "x")),
        "velocity_y": format_value("velocity_y", safe_attr(packet, "velocity", "y")),
        "velocity_z": format_value("velocity_z", safe_attr(packet, "velocity", "z")),
        "angular_velocity_x": format_value("angular_velocity_x", safe_attr(packet, "angular_velocity", "x")),
        "angular_velocity_y": format_value("angular_velocity_y", safe_attr(packet, "angular_velocity", "y")),
        "angular_velocity_z": format_value("angular_velocity_z", safe_attr(packet, "angular_velocity", "z")),
        "engine_rpm": format_value("engine_rpm", getattr(packet, "engine_rpm", "")),
        "rpm_alert_min": format_value("rpm_alert_min", safe_attr(packet, "rpm_alert", "min")),
        "rpm_alert_max": format_value("rpm_alert_max", safe_attr(packet, "rpm_alert", "max")),
        "throttle": format_value("throttle", getattr(packet, "throttle", "")),
        "brake": format_value("brake", getattr(packet, "brake", "")),
        "turbo_boost": format_value("turbo_boost", getattr(packet, "turbo_boost", "")),
        "current_gear": format_value("current_gear", getattr(packet, "current_gear", "")),
        "in_race": format_value("in_race", safe_attr(packet, "flags", "in_race")),
        "cars_in_race": format_value("cars_in_race", getattr(packet, "cars_in_race", "")),
        "lap_count": format_value("lap_count", getattr(packet, "lap_count", "")),
        "laps_in_race": format_value("laps_in_race", getattr(packet, "laps_in_race", "")),
        "best_lap_time": format_value("best_lap_time", getattr(packet, "best_lap_time", "")),
        "last_lap_time": format_value("last_lap_time", getattr(packet, "last_lap_time", "")),
        "rotation_yaw": format_value("rotation_yaw", safe_attr(packet, "rotation", "yaw")),
        "paused": format_value("paused", safe_attr(packet, "flags", "paused")),
    }

    for field, digits in FLOAT_PRECISION_BY_FIELD.items():
        row[field] = csv_number(row[field], digits)

    return row