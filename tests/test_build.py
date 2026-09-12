"""黄金テスト: tests/samples/vault を build して expected/ と突き合わせる。

期待出力を更新するときは  BIIDAMA_UPDATE=1 python -m pytest tests/test_build.py
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from biidama.build import build
from biidama.config import load_config

SAMPLES = Path(__file__).parent / "samples"
EXPECTED = SAMPLES / "expected"


def html_files(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.html"))
    }


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    cfg = load_config(SAMPLES / "config.yml")
    cfg.out = out / "html"
    cfg.state_dir = out / "state"
    res = build(cfg, log=lambda *_: None)
    return cfg, res


def test_golden(result):
    cfg, _ = result
    actual = html_files(cfg.out)
    if os.environ.get("BIIDAMA_UPDATE"):
        if EXPECTED.exists():
            shutil.rmtree(EXPECTED)
        for rel, text in actual.items():
            dst = EXPECTED / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8", newline="\n")
        pytest.skip("期待出力を更新しました")
    expected = html_files(EXPECTED)
    assert sorted(actual) == sorted(expected), "出力ファイルの一覧が違います"
    for rel in expected:
        assert actual[rel] == expected[rel], f"出力が違います: {rel}"


def test_warnings(result):
    _, res = result
    texts = "\n".join(res.warnings)
    assert "[[存在しない]]" in texts
    assert "[[下書き|下書き（非公開）]]" in texts
    assert len(res.warnings) == 2, res.warnings


def test_manifest(result):
    cfg, res = result
    import json

    m = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    srcs = {p["src"] for p in m["pages"] if p["src"]}
    assert "index.md" in srcs and "小説/第1話.md" in srcs
    assert "雑記/下書き.md" not in srcs
    generated = {p["out"] for p in m["pages"] if p["src"] is None}
    assert {"雑記.html", "タグ.html", "最近の更新.html"} <= generated
    assert all(o in ("雑記.html", "最近の更新.html") or o.startswith("タグ") for o in generated)
    for p in m["pages"]:
        if p["src"]:
            assert len(p["hash"]) == 64
