"""コマンドライン: build / publish / prune。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import BuildError, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biidama", description="保管庫から公開ページだけを静的 HTML にして、送り先へ届ける")
    parser.add_argument("--version", action="version", version=f"biidama {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("-c", "--config", default="config.local.yml", help="設定ファイル（既定: config.local.yml）")

    b = sub.add_parser("build", help="out/ に HTML を出す")
    common(b)
    pub = sub.add_parser("publish", help="build して、変わったファイルだけ送り先へ上書き送信し、抜け殻を確認する")
    common(pub)
    pub.add_argument("--env", default=None, help="送り先を書いた .env（既定: 設定ファイルと同じ場所の .env）")
    pub.add_argument("--dry-run", action="store_true", help="何を送るかを見せるだけで送らない")
    pr = sub.add_parser("prune", help="台帳にあって出力に無いファイルを、確認の上で送り先から消す")
    common(pr)
    pr.add_argument("--env", default=None)
    pr.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    from .config import load_config

    try:
        cfg = load_config(args.config)
        if args.command == "build":
            from .build import build

            result = build(cfg)
            for w in result.warnings:
                print(f"注意: {w}", file=sys.stderr)
            if result.warnings:
                print(f"注意 {len(result.warnings)} 件（出力は済んでいます）", file=sys.stderr)
            return 0

        from .publish import load_env, prune, publish

        env_path = Path(args.env) if args.env else Path(args.config).resolve().parent / ".env"
        remote = None if (args.dry_run and not env_path.is_file()) else load_env(env_path)
        if args.command == "publish":
            publish(cfg, remote, dry_run=args.dry_run)
        else:
            prune(cfg, remote, dry_run=args.dry_run)
        return 0
    except BuildError as e:
        print(f"中止: {e}", file=sys.stderr)
        return 1
