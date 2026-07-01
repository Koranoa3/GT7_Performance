from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FAN_SPEED_MULTIPLIER = 1.0
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


@dataclass(frozen=True)
class AppConfig:
    fan_speed_multiplier: float = DEFAULT_FAN_SPEED_MULTIPLIER


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

    return AppConfig(fan_speed_multiplier=fan_speed_multiplier)
