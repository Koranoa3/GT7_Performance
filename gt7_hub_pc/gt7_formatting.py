from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable, Iterable

CSV_TARGET = "csv"
CONSOLE_TARGET = "console"
ESP_TARGET = "esp"

_TARGET_LABELS = {
    CSV_TARGET: "CSV記録",
    CONSOLE_TARGET: "コンソール出力",
    ESP_TARGET: "ESP送信",
}
_TARGET_ORDER = (CSV_TARGET, CONSOLE_TARGET, ESP_TARGET)
_MISSING = object()


def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def packet_attr(*path: str) -> Callable[[Any], Any]:
    def getter(packet: Any) -> Any:
        current = packet
        for name in path:
            if current is None:
                return _MISSING
            try:
                current = getattr(current, name)
            except AttributeError:
                return _MISSING
        return current

    return getter


def generated_value(factory: Callable[[], Any]) -> Callable[[Any], Any]:
    def getter(_: Any) -> Any:
        return factory()

    return getter


def csv_number(value: Any, digits: int) -> Any:
    if isinstance(value, bool):
        return int(value)

    number = float(value)
    if digits == 0:
        return int(round(number))

    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def padded_number(value: Any, digits: int) -> str:
    if isinstance(value, bool):
        return str(int(value))

    number = float(value)
    if digits == 0:
        return str(int(round(number)))

    return f"{number:.{digits}f}"


def _normalize_value(value: Any, digits: int | None) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if digits == 0:
            return int(round(value))
        if digits is not None:
            return round(value, digits)
        return round(value, 3)
    return value


@dataclass(frozen=True)
class TelemetryFieldDefinition:
    name: str
    getter: Callable[[Any], Any]
    targets: frozenset[str]
    digits: int | None = None
    console_digits: int | None = None
    esp_default: Any = _MISSING


def field(
    name: str,
    getter: Callable[[Any], Any],
    *targets: str,
    digits: int | None = None,
    console_digits: int | None = None,
    esp_default: Any = _MISSING,
) -> TelemetryFieldDefinition:
    return TelemetryFieldDefinition(
        name=name,
        getter=getter,
        targets=frozenset(targets),
        digits=digits,
        console_digits=console_digits,
        esp_default=esp_default,
    )


@dataclass(frozen=True)
class TelemetryWarning:
    field_name: str
    reason: str
    targets: tuple[str, ...]
    detail: str | None = None

    @property
    def dedupe_key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.field_name, self.reason, self.targets)

    def message(self) -> str:
        labels = " / ".join(_TARGET_LABELS[target] for target in self.targets)
        message = f"'{self.field_name}' は {self.reason}ため、{labels} ではスキップします。"
        if self.detail:
            return f"{message} 詳細: {self.detail}"
        return message


@dataclass(frozen=True)
class TelemetrySnapshot:
    values: dict[str, Any]
    warnings: tuple[TelemetryWarning, ...]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def has(self, name: str) -> bool:
        return name in self.values


class TelemetryLayout:
    def __init__(self, fields: Iterable[TelemetryFieldDefinition]) -> None:
        self._fields = tuple(fields)
        self._fields_by_target = {
            CSV_TARGET: tuple(field for field in self._fields if CSV_TARGET in field.targets),
            CONSOLE_TARGET: tuple(field for field in self._fields if CONSOLE_TARGET in field.targets),
            ESP_TARGET: tuple(field for field in self._fields if ESP_TARGET in field.targets),
        }

    def field_names(self, target: str) -> list[str]:
        return [field.name for field in self._fields_by_target[target]]

    def resolve_packet(self, packet: Any) -> TelemetrySnapshot:
        values: dict[str, Any] = {}
        warnings: list[TelemetryWarning] = []

        for definition in self._fields:
            if not definition.targets:
                continue

            try:
                raw_value = definition.getter(packet)
            except Exception as exc:
                warnings.append(
                    TelemetryWarning(
                        field_name=definition.name,
                        reason="取得に失敗した",
                        targets=self._ordered_targets(definition.targets),
                        detail=str(exc),
                    )
                )
                continue

            if raw_value is _MISSING or raw_value is None or raw_value == "":
                warnings.append(
                    TelemetryWarning(
                        field_name=definition.name,
                        reason="受信できなかった",
                        targets=self._ordered_targets(definition.targets),
                    )
                )
                continue

            values[definition.name] = _normalize_value(raw_value, definition.digits)

        return TelemetrySnapshot(values=values, warnings=tuple(warnings))

    @staticmethod
    def _ordered_targets(targets: Iterable[str]) -> tuple[str, ...]:
        target_set = set(targets)
        return tuple(target for target in _TARGET_ORDER if target in target_set)

    def build_csv_row(self, snapshot: TelemetrySnapshot) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for definition in self._fields_by_target[CSV_TARGET]:
            if not snapshot.has(definition.name):
                continue

            value = snapshot.get(definition.name)
            if definition.digits is None:
                row[definition.name] = value
                continue
            row[definition.name] = csv_number(value, definition.digits)
        return row

    def build_console_values(self, snapshot: TelemetrySnapshot) -> list[str]:
        values: list[str] = []
        for definition in self._fields_by_target[CONSOLE_TARGET]:
            if not snapshot.has(definition.name):
                values.append("")
                continue

            value = snapshot.get(definition.name)
            digits = definition.console_digits if definition.console_digits is not None else definition.digits
            if digits is None:
                values.append(str(value))
                continue
            values.append(padded_number(value, digits))
        return values

    def build_esp_values(self, snapshot: TelemetrySnapshot) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for definition in self._fields_by_target[ESP_TARGET]:
            if snapshot.has(definition.name):
                values[definition.name] = snapshot.get(definition.name)
                continue
            if definition.esp_default is not _MISSING:
                values[definition.name] = definition.esp_default
        return values


TELEMETRY_LAYOUT = TelemetryLayout(
    [
        field("logged_at", generated_value(now_local_iso), CSV_TARGET, CONSOLE_TARGET),
        field("packet_id", packet_attr("packet_id"), CSV_TARGET, CONSOLE_TARGET),
        field(
            "car_speed",
            packet_attr("car_speed"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_x",
            packet_attr("velocity", "x"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_y",
            packet_attr("velocity", "y"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_z",
            packet_attr("velocity", "z"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "angular_velocity_x",
            packet_attr("angular_velocity", "x"),
            CSV_TARGET,
            CONSOLE_TARGET,
            digits=3,
        ),
        field(
            "angular_velocity_y",
            packet_attr("angular_velocity", "y"),
            CSV_TARGET,
            CONSOLE_TARGET,
            digits=3,
        ),
        field(
            "angular_velocity_z",
            packet_attr("angular_velocity", "z"),
            CSV_TARGET,
            CONSOLE_TARGET,
            digits=3,
        ),
        field("rotation_yaw", packet_attr("rotation", "yaw"), CSV_TARGET, digits=3),
        field("engine_rpm", packet_attr("engine_rpm"), CSV_TARGET, ESP_TARGET, digits=0, esp_default=0.0),
        field("rpm_alert_min", packet_attr("rpm_alert", "min"), CSV_TARGET, digits=0),
        field("rpm_alert_max", packet_attr("rpm_alert", "max"), CSV_TARGET, digits=0),
        field(
            "throttle",
            packet_attr("throttle"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=0,
            esp_default=0,
        ),
        field("brake", packet_attr("brake"), CSV_TARGET, ESP_TARGET, digits=0, esp_default=0),
        field(
            "turbo_boost",
            packet_attr("turbo_boost"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "current_gear",
            packet_attr("current_gear"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=0,
            esp_default=-1,
        ),
        field("in_race", packet_attr("flags", "in_race"), CSV_TARGET, ESP_TARGET, esp_default=False),
        field("cars_in_race", packet_attr("cars_in_race"), CSV_TARGET, ESP_TARGET, esp_default=-1),
        field("lap_count", packet_attr("lap_count"), CSV_TARGET, ESP_TARGET, esp_default=-1),
        field("laps_in_race", packet_attr("laps_in_race"), CSV_TARGET),
        field("best_lap_time", packet_attr("best_lap_time"), CSV_TARGET, ESP_TARGET, esp_default=-1),
        field("last_lap_time", packet_attr("last_lap_time"), CSV_TARGET, ESP_TARGET, esp_default=-1),
        field("paused", packet_attr("flags", "paused"), CSV_TARGET),
    ]
)
