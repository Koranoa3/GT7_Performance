from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from granturismo.intake import Listener

from gt7_console import LiveConsole
from gt7_writer import TelemetryCsvWriter


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
    console = LiveConsole()
    console.log(f"接続先PS5: {ip_address}")
    console.log(f"CSV出力先: {output_path}")
    console.log("終了するには Ctrl+C を押してください。")

    rows_written = 0
    try:
        with TelemetryCsvWriter(output_path) as writer:
            with Listener(ip_address) as listener:
                console.log("PS5への接続を開始しました。テレメトリ受信を待機しています...")
                while True:
                    packet = listener.get()
                    if packet is None:
                        continue
                    writer.write_packet(packet)
                    rows_written += 1
                    console.status_from_packet(packet)
                    if rows_written == 1 or rows_written % 100 == 0:
                        console.log(f"{rows_written}行を記録しました。")
    except KeyboardInterrupt:
        console.finish()
        console.log("")
        console.log("記録を停止しました。")
    except Exception as exc:
        console.finish()
        print(f"実行中にエラーが発生しました: {exc}", file=sys.stderr)
        return 1

    console.finish()
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