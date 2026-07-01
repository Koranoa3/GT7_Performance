from __future__ import annotations

import configparser
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FAN_SPEED_MULTIPLIER = 1.0
DEFAULT_MAX_CAR_SPEED = math.inf
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


@dataclass(frozen=True)
class AppConfig:
    fan_speed_multiplier: float = DEFAULT_FAN_SPEED_MULTIPLIER
    max_car_speed: float = DEFAULT_MAX_CAR_SPEED


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        return AppConfig()

    parser = configparser.ConfigParser(interpolation=None)
    config_text = config_path.read_text(encoding="utf-8")
    parser.read_string("[DEFAULT]\n" + config_text)

    fan_speed_multiplier = parser["DEFAULT"].getfloat(
        "FAN_SPEED_MULTIPLIER",
        fallback=DEFAULT_FAN_SPEED_MULTIPLIER,
    )
    if fan_speed_multiplier < 0.0:
        raise ValueError(
            f"config.ini の FAN_SPEED_MULTIPLIER は 0 以上で指定してください: {fan_speed_multiplier}"
        )

    max_car_speed = parser["DEFAULT"].getfloat(
        "MAX_CAR_SPEED",
        fallback=DEFAULT_MAX_CAR_SPEED,
    )
    if max_car_speed < 0.0:
        raise ValueError(
            f"config.ini の MAX_CAR_SPEED は 0 以上で指定してください: {max_car_speed}"
        )

    return AppConfig(
        fan_speed_multiplier=fan_speed_multiplier,
        max_car_speed=max_car_speed,
    )
