"""publish / prune: 送らずに（ssh を差し替えて）差分・台帳・抜け殻の流れを確かめる。"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from biidama import BuildError
from biidama.config import Config, SiteConfig
from biidama.publish import Remote, file_hashes, load_env, prune, publish, read_ledger

PUB = "---\npublish: true\ncreated: 2026-01-01\nmodified: 2026-02-02\n---\n"


class FakeSSH:
    """ssh の代わり。受け取ったコマンドと tar の中身を覚える。"""

    def __init__(self, fail=False):
        self.calls: list[tuple[list[str], set[str]]] = []
        self.fail = fail

    def __call__(self, cmd, stdin):
        names: set[str] = set()
        if stdin:
            with tarfile.open(fileobj=io.BytesIO(stdin)) as tar:
                names = {m.name for m in tar.getmembers() if m.isfile()}
        self.calls.append((cmd, names))
        return subprocess.CompletedProcess(cmd, 1 if self.fail else 0, b"", b"ng" if self.fail else b"")


def make_cfg(tmp_path: Path, files: dict[str, str]) -> Config:
    vault = tmp_path / "vault"
    for rel, text in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return Config(vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t"))


REMOTE = Remote(host="example", remote_dir="web/site/")
from biidama.build import STATIC_DIR  # noqa: E402

STATIC = sorted("static/" + p.name for p in STATIC_DIR.iterdir() if p.is_file())  # 手元にある静的ファイル（icon.png の有無は環境次第）
quiet = lambda *_: None


def test_first_publish_sends_everything_and_writes_ledger(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口", "a/x.md": PUB + "x"})
    ssh = FakeSSH()
    res = publish(cfg, REMOTE, runner=ssh, log=quiet)
    assert sorted(res.sent) == ["a.html", "a/x.html", "index.html", *STATIC]
    assert len(ssh.calls) == 1
    cmd, names = ssh.calls[0]
    assert cmd[:3] == ["ssh", "-o", "BatchMode=yes"] and cmd[-2] == "example"
    assert "mkdir -p web/site/ && tar -xf - -C web/site/" == cmd[-1]
    assert names == set(res.sent)
    ledger = read_ledger(cfg)
    assert set(ledger["files"]) == set(res.sent)
    assert ledger["pages"]["a/x.md"]["updated"] == "2026-02-02"  # 初回は modified を種に
    assert len(ledger["pages"]["a/x.md"]["hash"]) == 64


def test_second_publish_sends_only_changes(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口", "a/x.md": PUB + "x"})
    publish(cfg, REMOTE, runner=FakeSSH(), log=quiet)
    (cfg.vault / "a/x.md").write_text(PUB + "x を書き換えた", encoding="utf-8")
    ssh = FakeSSH()
    res = publish(cfg, REMOTE, runner=ssh, log=quiet)
    assert res.sent == ["a/x.html"] and res.unchanged == 2 + len(STATIC)
    assert ssh.calls[0][1] == {"a/x.html"}
    # 本文が変わったので更新日は今日、変わっていないページは台帳の日付のまま
    import datetime as dt

    ledger = read_ledger(cfg)
    assert ledger["pages"]["a/x.md"]["updated"] == dt.date.today().isoformat()
    assert ledger["pages"]["index.md"]["updated"] == "2026-02-02"
    html = (cfg.out / "a/x.html").read_text(encoding="utf-8")
    assert f'更新 <time datetime="{dt.date.today().isoformat()}">' in html


def test_dry_run_sends_nothing_and_keeps_ledger(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口"})
    ssh = FakeSSH()
    res = publish(cfg, None, dry_run=True, runner=ssh, log=quiet)
    assert res.dry_run and ssh.calls == [] and not (cfg.state_dir / "ledger.json").exists()
    assert sorted(res.sent) == ["index.html", *STATIC]


def test_failed_send_keeps_ledger(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口"})
    with pytest.raises(BuildError, match="送信に失敗"):
        publish(cfg, REMOTE, runner=FakeSSH(fail=True), log=quiet)
    assert not (cfg.state_dir / "ledger.json").exists()


def test_orphans_are_listed_then_deleted_only_on_yes(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口", "a/x.md": PUB + "x"})
    publish(cfg, REMOTE, runner=FakeSSH(), log=quiet)
    (cfg.vault / "a/x.md").unlink()  # ページを消す → a/x.html と索引 a.html が抜け殻に
    ssh = FakeSSH()
    res = publish(cfg, REMOTE, runner=ssh, ask=lambda q: False, log=quiet)
    assert res.orphans == ["a.html", "a/x.html"] and res.deleted == []
    assert res.sent == [] and ssh.calls == []  # 変わったファイルも無く、削除の ssh も呼ばれていない
    assert set(read_ledger(cfg)["files"]) >= {"a.html", "a/x.html"}  # 台帳には残る

    ssh = FakeSSH()
    deleted = prune(cfg, REMOTE, runner=ssh, ask=lambda q: True, log=quiet)
    assert deleted == ["a.html", "a/x.html"]
    assert ssh.calls[0][0][-1] == "rm -f -- web/site/a.html web/site/a/x.html"
    assert "a.html" not in read_ledger(cfg)["files"]


def test_prune_never_touches_unknown_files(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口"})
    publish(cfg, REMOTE, runner=FakeSSH(), log=quiet)
    ssh = FakeSSH()
    assert prune(cfg, REMOTE, runner=ssh, ask=lambda q: True, log=quiet) == []
    assert ssh.calls == []  # 台帳に無い .htaccess などは知らないので候補にすら出ない


def test_load_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# 見本\nBIIDAMA_HOST=dreams\nBIIDAMA_REMOTE_DIR=web/site\nBIIDAMA_PORT=\"2222\"\n", encoding="utf-8")
    r = load_env(p)
    assert (r.host, r.remote_dir, r.port, r.user) == ("dreams", "web/site/", "2222", "")
    assert r.ssh_command() == ["ssh", "-o", "BatchMode=yes", "-p", "2222", "dreams"]
    p.write_text("BIIDAMA_HOST=dreams\n", encoding="utf-8")
    with pytest.raises(BuildError, match="BIIDAMA_REMOTE_DIR"):
        load_env(p)
    with pytest.raises(BuildError, match="見つかりません"):
        load_env(tmp_path / "nothing")


def test_file_hashes_skip_marker(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "入口"})
    publish(cfg, REMOTE, runner=FakeSSH(), log=quiet)
    assert ".biidama-out" not in file_hashes(cfg.out)
