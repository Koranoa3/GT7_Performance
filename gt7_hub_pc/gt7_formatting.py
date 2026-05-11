from __future__ import annotations

import datetime as dt
import math
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
Getter = Callable[["TelemetryResolveContext"], Any]


def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def packet_attr(*path: str) -> Getter:
    def getter(context: "TelemetryResolveContext") -> Any:
        current = context.packet
        for name in path:
            if current is None:
                return _MISSING
            try:
                current = getattr(current, name)
            except AttributeError:
                return _MISSING
        return current

    return getter


def generated_value(factory: Callable[[], Any]) -> Getter:
    def getter(_: "TelemetryResolveContext") -> Any:
        return factory()

    return getter


def computed_value(factory: Getter) -> Getter:
    return factory


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
    getter: Getter
    targets: frozenset[str]
    digits: int | None = None
    console_digits: int | None = None
    esp_default: Any = _MISSING


def field(
    name: str,
    getter: Getter,
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


class TelemetryResolveContext:
    def __init__(self, packet: Any, fields_by_name: dict[str, TelemetryFieldDefinition]) -> None:
        self.packet = packet
        self._fields_by_name = fields_by_name
        self._resolved_values: dict[str, Any] = {}
        self._memoized_values: dict[str, Any] = {}
        self._resolving_fields: set[str] = set()

    def value(self, name: str) -> Any:
        if name in self._resolved_values:
            return self._resolved_values[name]

        definition = self._fields_by_name[name]
        if name in self._resolving_fields:
            raise RuntimeError(f"循環参照を検出しました: {name}")

        self._resolving_fields.add(name)
        try:
            raw_value = definition.getter(self)
        finally:
            self._resolving_fields.remove(name)

        if raw_value is _MISSING or raw_value is None or raw_value == "":
            value = _MISSING
        else:
            value = _normalize_value(raw_value, definition.digits)
        self._resolved_values[name] = value
        return value

    def memoize(self, key: str, factory: Callable[[], Any]) -> Any:
        if key not in self._memoized_values:
            self._memoized_values[key] = factory()
        return self._memoized_values[key]


class TelemetryLayout:
    def __init__(self, fields: Iterable[TelemetryFieldDefinition]) -> None:
        self._fields = tuple(fields)
        self._fields_by_name = {field.name: field for field in self._fields}
        self._fields_by_target = {
            CSV_TARGET: tuple(field for field in self._fields if CSV_TARGET in field.targets),
            CONSOLE_TARGET: tuple(field for field in self._fields if CONSOLE_TARGET in field.targets),
            ESP_TARGET: tuple(field for field in self._fields if ESP_TARGET in field.targets),
        }

    def field_names(self, target: str) -> list[str]:
        return [field.name for field in self._fields_by_target[target]]

    def resolve_packet(self, packet: Any) -> TelemetrySnapshot:
        context = TelemetryResolveContext(packet, self._fields_by_name)
        values: dict[str, Any] = {}
        warnings: list[TelemetryWarning] = []

        for definition in self._fields:
            if not definition.targets:
                continue

            try:
                value = context.value(definition.name)
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

            if value is _MISSING:
                warnings.append(
                    TelemetryWarning(
                        field_name=definition.name,
                        reason="受信できなかった",
                        targets=self._ordered_targets(definition.targets),
                    )
                )
                continue

            values[definition.name] = value

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


def _orientation_to_direction(orientation: float) -> float:
    clamped = max(-1.0, min(1.0, float(orientation)))
    return math.degrees(math.asin(clamped)) * 2.0


def _heading_components(context: TelemetryResolveContext) -> tuple[float, float, float]:
    def compute() -> tuple[float, float, float]:
        rotation_yaw = context.value("rotation_yaw")
        if rotation_yaw is _MISSING:
            return (_MISSING, _MISSING, _MISSING)

        direction = 90 - _orientation_to_direction(float(rotation_yaw))
        radians = math.radians(direction)
        return (direction, math.sin(radians), math.cos(radians))

    return context.memoize("heading_components", compute)


def _direction_value(context: TelemetryResolveContext) -> Any:
    direction, _sin_value, _cos_value = _heading_components(context)
    return direction


def _velocity_forward_value(context: TelemetryResolveContext) -> Any:
    velocity_x = context.value("velocity_x")
    velocity_z = context.value("velocity_z")
    if velocity_x is _MISSING or velocity_z is _MISSING:
        return _MISSING

    _direction, sin_value, cos_value = _heading_components(context)
    if sin_value is _MISSING or cos_value is _MISSING:
        return _MISSING

    return (-float(velocity_x) * cos_value) + (-float(velocity_z) * sin_value)


def _velocity_right_value(context: TelemetryResolveContext) -> Any:
    velocity_x = context.value("velocity_x")
    velocity_z = context.value("velocity_z")
    if velocity_x is _MISSING or velocity_z is _MISSING:
        return _MISSING

    _direction, sin_value, cos_value = _heading_components(context)
    if sin_value is _MISSING or cos_value is _MISSING:
        return _MISSING

    return (float(velocity_x) * sin_value) - (float(velocity_z) * cos_value)


TELEMETRY_LAYOUT = TelemetryLayout(
    [
        field("logged_at", generated_value(now_local_iso), CSV_TARGET, CONSOLE_TARGET),
        field("packet_id", packet_attr("packet_id"), CSV_TARGET, CONSOLE_TARGET),
        field(
            "car_speed", # m/s
            packet_attr("car_speed"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_x", # east
            packet_attr("velocity", "x"),
            CSV_TARGET,
            CONSOLE_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_y", # up
            packet_attr("velocity", "y"),
            CSV_TARGET,
            ESP_TARGET,
            digits=3,
            esp_default=0.0,
        ),
        field(
            "velocity_z", # south
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
        field("orientation", packet_attr("orientation"), CSV_TARGET, CONSOLE_TARGET, digits=3), # asin(orientation)*2 = -180~180 | 0=north, 90=west, 180=south, -90=east
        field("direction", computed_value(_direction_value), CSV_TARGET, CONSOLE_TARGET, digits=0), # -180~180 | 0=north, 90=west, +-180=south, -90=east
        field("velocity_forward", computed_value(_velocity_forward_value), CSV_TARGET, CONSOLE_TARGET, digits=3), # local forward (+) / backward (-)
        field("velocity_right", computed_value(_velocity_right_value), CSV_TARGET, CONSOLE_TARGET, digits=3), # local right (+) / left (-)
        field("engine_rpm", packet_attr("engine_rpm"), CSV_TARGET, ESP_TARGET, digits=0, esp_default=0.0),
        field("rpm_alert_min", packet_attr("rpm_alert", "min"), CSV_TARGET, digits=0),
        field("rpm_alert_max", packet_attr("rpm_alert", "max"), CSV_TARGET, digits=0),
        field(
            "throttle", # 255
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
        field("lap_count", packet_attr("lap_count"), CSV_TARGET, CONSOLE_TARGET, ESP_TARGET, esp_default=-1),
        field("laps_in_race", packet_attr("laps_in_race"), CSV_TARGET, digits=0),
        field("last_lap_time", packet_attr("last_lap_time"), CSV_TARGET, ESP_TARGET, esp_default=-1),
        field("paused", packet_attr("flags", "paused"), CSV_TARGET),
        field("car_on_track", packet_attr("flags", "car_on_track"), CSV_TARGET)
    ]
)
