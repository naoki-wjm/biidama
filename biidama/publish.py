"""publish: build → 前回の台帳と比べる → 変わったファイルだけ送る → 台帳を書く。prune: 抜け殻を確認の上で消す。

送り方は「変わったファイルを tar に束ねて ssh 一本で流し込む」。scp をファイルごとに呼ぶより速く、
Windows の scp が日本語ファイル名で転ぶ問題も避けられる（tar の中の名前は UTF-8）。
遠隔側は上書きだけ。消すのは prune の確認を経たものだけで、台帳に無いファイル（手で置いた .htaccess など）には触らない。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import shlex
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import BuildError, __version__
from .build import BuildResult, build
from .config import Config

OUT_MARKER = ".biidama-out"


@dataclass
class Remote:
    host: str  # ssh の接続先（~/.ssh/config の別名でもよい）
    remote_dir: str  # 遠隔側の置き場（例: web/site/）
    user: str = ""
    port: str = ""
    key: str = ""

    def ssh_command(self) -> list[str]:
        cmd = ["ssh", "-o", "BatchMode=yes"]
        if self.port:
            cmd += ["-p", self.port]
        if self.key:
            cmd += ["-i", self.key]
        cmd.append(f"{self.user}@{self.host}" if self.user else self.host)
        return cmd


def load_env(path: Path) -> Remote:
    """.env（KEY=VALUE 行）から送り先を読む。"""
    if not path.is_file():
        raise BuildError(f".env が見つかりません（.env.example を写して送り先を書いてください）: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip().strip('"').strip("'")
    host = values.get("BIIDAMA_HOST", "")
    remote_dir = values.get("BIIDAMA_REMOTE_DIR", "")
    if not host or not remote_dir:
        raise BuildError(f".env に BIIDAMA_HOST と BIIDAMA_REMOTE_DIR が要ります: {path}")
    return Remote(
        host=host,
        remote_dir=remote_dir.rstrip("/") + "/",
        user=values.get("BIIDAMA_USER", ""),
        port=values.get("BIIDAMA_PORT", ""),
        key=values.get("BIIDAMA_KEY", ""),
    )


# ---- 台帳 ----------------------------------------------------------------

def ledger_path(cfg: Config) -> Path:
    return cfg.state_dir / "ledger.json"


def read_ledger(cfg: Config) -> dict:
    path = ledger_path(cfg)
    if not path.is_file():
        return {"pages": {}, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BuildError(f"公開台帳が読めません: {path}: {e}") from e
    data.setdefault("pages", {})
    data.setdefault("files", {})
    return data


def write_ledger(cfg: Config, data: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    data["biidama"] = __version__
    data["written"] = dt.datetime.now().isoformat(timespec="seconds")
    ledger_path(cfg).write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")


def file_hashes(out: Path) -> dict[str, str]:
    """出力フォルダの全ファイル（目印を除く）→ 中身のハッシュ。"""
    result: dict[str, str] = {}
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        if rel == OUT_MARKER:
            continue
        result[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


# ---- 送る・消す ------------------------------------------------------------

Runner = Callable[[list[str], bytes | None], subprocess.CompletedProcess]


def run_ssh(cmd: list[str], stdin: bytes | None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True)


def pack(out: Path, files: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            tar.add(out / rel, arcname=rel)
    return buf.getvalue()


def send(remote: Remote, out: Path, files: list[str], runner: Runner) -> None:
    """変わったファイルを tar に束ねて ssh 一本で流し込む（遠隔側は上書きのみ）。"""
    if not files:
        return
    d = shlex.quote(remote.remote_dir)
    cmd = remote.ssh_command() + [f"mkdir -p {d} && tar -xf - -C {d}"]
    result = runner(cmd, pack(out, files))
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise BuildError(f"送信に失敗しました（台帳は更新していません）: {err}")


def delete_remote(remote: Remote, files: list[str], runner: Runner) -> None:
    if not files:
        return
    paths = " ".join(shlex.quote(remote.remote_dir + f) for f in files)
    cmd = remote.ssh_command() + [f"rm -f -- {paths}"]
    result = runner(cmd, None)
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise BuildError(f"遠隔の削除に失敗しました: {err}")


# ---- publish / prune -----------------------------------------------------------

@dataclass
class PublishResult:
    build: BuildResult
    sent: list[str] = field(default_factory=list)
    unchanged: int = 0
    orphans: list[str] = field(default_factory=list)  # 台帳にあって今回の出力に無いもの
    deleted: list[str] = field(default_factory=list)
    dry_run: bool = False


def default_ask(question: str) -> bool:
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def publish(
    cfg: Config,
    remote: Remote | None,
    *,
    dry_run: bool = False,
    runner: Runner = run_ssh,
    ask: Callable[[str], bool] = default_ask,
    log=print,
) -> PublishResult:
    """build → 差分 → 送信 → 台帳 → 抜け殻の確認。"""
    ledger = read_ledger(cfg)
    res = build(cfg, log=log)
    for w in res.warnings:
        log(f"注意: {w}")

    current = file_hashes(cfg.out)
    previous: dict[str, str] = ledger["files"]
    changed = [f for f, h in current.items() if previous.get(f) != h]
    orphans = sorted(f for f in previous if f not in current)
    result = PublishResult(build=res, sent=changed, unchanged=len(current) - len(changed), orphans=orphans, dry_run=dry_run)

    log(f"送るもの {len(changed)} 件、変わっていないもの {result.unchanged} 件、抜け殻 {len(orphans)} 件")
    for f in changed:
        log(f"  → {f}")
    for f in orphans:
        log(f"  抜け殻: {f}")
    if dry_run:
        log("（--dry-run なので送っていません）")
        return result
    if remote is None:
        raise BuildError("送り先が無いので送れません")

    send(remote, cfg.out, changed, runner)
    log(f"送りました: {remote.host}:{remote.remote_dir}（{len(changed)} 件）")

    # 台帳: 送れたので今回の出力を正とする。抜け殻は消すまで残す
    pages = {}
    for p in res.pages:
        u = res.updated.get(p.rel)
        pages[p.rel + ".md"] = {"hash": p.body_hash(), "out": p.out_rel, "updated": u.isoformat() if u else None}
    files = dict(previous)
    files.update(current)
    ledger.update({"pages": pages, "files": files, "published": dt.datetime.now().isoformat(timespec="seconds")})
    write_ledger(cfg, ledger)

    if orphans:
        result.deleted = prune(cfg, remote, runner=runner, ask=ask, log=log, _ledger=ledger, _orphans=orphans)
    return result


def prune(
    cfg: Config,
    remote: Remote | None,
    *,
    dry_run: bool = False,
    runner: Runner = run_ssh,
    ask: Callable[[str], bool] = default_ask,
    log=print,
    _ledger: dict | None = None,
    _orphans: list[str] | None = None,
) -> list[str]:
    """台帳にあって今回の出力に無いファイルを一覧し、確認の上で遠隔から消す。台帳に無いものには触らない。"""
    ledger = _ledger if _ledger is not None else read_ledger(cfg)
    if _orphans is None:
        if not cfg.out.is_dir():
            raise BuildError("出力が無いので比べられません。先に build か publish をしてください")
        current = file_hashes(cfg.out)
        orphans = sorted(f for f in ledger["files"] if f not in current)
    else:
        orphans = _orphans
    if not orphans:
        log("抜け殻はありません")
        return []
    log(f"台帳にあって今回の出力に無いファイル {len(orphans)} 件:")
    for f in orphans:
        log(f"  {f}")
    if dry_run:
        log("（--dry-run なので消していません）")
        return []
    if remote is None:
        raise BuildError("送り先が無いので消せません")
    if not ask(f"この {len(orphans)} 件を {remote.host}:{remote.remote_dir} から消しますか？ [y/N] "):
        log("消しませんでした（台帳にも残しておきます）")
        return []
    delete_remote(remote, orphans, runner)
    for f in orphans:
        ledger["files"].pop(f, None)
    write_ledger(cfg, ledger)
    log(f"消しました: {len(orphans)} 件")
    return orphans
