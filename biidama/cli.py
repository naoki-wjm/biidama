"""コマンドライン。今は build だけ。publish / prune は manifest を読む形で後から足す。"""

from __future__ import annotations

import argparse
import sys

from . import BuildError, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biidama", description="保管庫から公開ページだけを静的 HTML にする")
    parser.add_argument("--version", action="version", version=f"biidama {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="out/ に HTML を出す")
    b.add_argument("-c", "--config", default="config.local.yml", help="設定ファイル（既定: config.local.yml）")
    args = parser.parse_args(argv)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    if args.command == "build":
        from .build import build
        from .config import load_config

        try:
            result = build(load_config(args.config))
        except BuildError as e:
            print(f"ビルド中止: {e}", file=sys.stderr)
            return 1
        for w in result.warnings:
            print(f"注意: {w}", file=sys.stderr)
        if result.warnings:
            print(f"注意 {len(result.warnings)} 件（出力は済んでいます）", file=sys.stderr)
        return 0
    return 2
