from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from gt7_console import StartupConsole


@dataclass(frozen=True)
class RuntimeLaunchConfig:
    ip_address: str
    log_trace_path: Optional[Path]
    output_path: Path
    record_enabled: bool
    esp_ports: list[str]
    bindings: list[tuple[str, int]]
    auto_bind: bool

    @property
    def trace_mode(self) -> bool:
        return self.log_trace_path is not None


def default_output_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("records") / f"gt7_telemetry_{stamp}.csv"


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
        "--trace",
        type=Path,
        default=None,
        help="records/ に保存したCSVを疑似トレース入力として使います。",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="CSV記録を有効化します（未指定時は記録しません）。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSVの出力先。`--record` 指定時のみ有効です。未指定時は records/ にタイムスタンプ付きで保存します。",
    )
    parser.add_argument(
        "--esp-port",
        dest="esp_ports",
        nargs="+",
        action="append",
        default=[],
        metavar="PORT",
        help="ESP32 のシリアルポート。複数同時指定可。未指定なら接続可能なポートを自動探索します。",
    )
    parser.add_argument(
        "--bind",
        dest="binding_groups",
        nargs="+",
        action="append",
        default=[],
        metavar="PS5_IP:ESP_ID",
        help="手動紐づけ。1回の指定で複数登録できます。複数回指定も可能です。",
    )
    parser.add_argument(
        "--interactive-bind",
        action="store_true",
        help="起動時に対話形式で複数バインドを入力します。",
    )
    parser.add_argument(
        "--auto-bind",
        action="store_true",
        default=True,
        help="検出したESPとPS5のIPが分かり次第自動でバインドします。`--interactive-bind`より優先されます。",
    )
    return parser


def flatten_cli_values(groups: Sequence[Sequence[str]]) -> list[str]:
    values: list[str] = []
    for group in groups:
        for raw in group:
            value = raw.strip()
            if value:
                values.append(value)
    return values


def parse_bindings(values: Iterable[str]) -> list[tuple[str, int]]:
    bindings: list[tuple[str, int]] = []
    for raw in values:
        value = raw.strip()
        if not value:
            continue
        if ":" not in value:
            raise ValueError(f"無効な紐づけ指定です: {raw}")
        ps5_ip, esp_id_text = value.split(":", 1)
        ps5_ip = ps5_ip.strip()
        esp_id_text = esp_id_text.strip()
        if not ps5_ip or not esp_id_text:
            raise ValueError(f"無効な紐づけ指定です: {raw}")
        bindings.append((ps5_ip, int(esp_id_text)))
    return bindings


def resolve_bindings(
    cli_binding_groups: Sequence[Sequence[str]],
    interactive_bind: bool,
    auto_bind: bool,
    console: StartupConsole,
) -> list[tuple[str, int]]:
    # CLI で明示的な --bind 指定、または --interactive-bind 指定がある場合、自動バインドは無効化する
    raw_bindings = flatten_cli_values(cli_binding_groups)
    if raw_bindings or interactive_bind:
        auto_bind = False

    # auto_bind が有効な場合は自動バインドに委ねる（明示指定のバインドは不要）
    if auto_bind:
        return []

    if interactive_bind:
        raw_bindings.extend(console.prompt_bindings())
    return parse_bindings(raw_bindings)


def load_runtime_config(
    argv: Sequence[str] | None = None,
    console: StartupConsole | None = None,
) -> RuntimeLaunchConfig:
    startup_console = console or StartupConsole()
    parser = build_parser()
    args = parser.parse_args(argv)

    ip_address = startup_console.prompt_ip_address(args.ip_address)
    if not ip_address:
        raise ValueError("IPアドレスが空です。")
    # CLI で --bind が指定されている場合は自動バインドを無効化する
    cli_bind_values = flatten_cli_values(args.binding_groups)
    effective_auto_bind = args.auto_bind and not bool(cli_bind_values)

    bindings = resolve_bindings(
        args.binding_groups, args.interactive_bind, effective_auto_bind, startup_console
    )
    output_path = args.output or default_output_path()
    esp_ports = flatten_cli_values(args.esp_ports)

    return RuntimeLaunchConfig(
        ip_address=ip_address,
        log_trace_path=args.trace,
        output_path=output_path,
        record_enabled=args.record,
        esp_ports=esp_ports,
        bindings=bindings,
        auto_bind=effective_auto_bind,
    )
