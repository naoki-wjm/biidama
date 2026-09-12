"""実原稿の写し（fixtures/、リポには入れない）を通す試験。写しが無ければ飛ばす。

fixtures/vault/     … 保管庫から複製した試験片（Phase A〜D）
fixtures/config.yml … その設定
fixtures/expected/  … 期待 HTML。BIIDAMA_UPDATE=1 で更新
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from biidama.build import build, render_file
from biidama.config import load_config

FIXTURES = Path(__file__).parent.parent / "fixtures"
EXPECTED = FIXTURES / "expected"

pytestmark = pytest.mark.skipif(not (FIXTURES / "config.yml").is_file(), reason="fixtures/ が無い")


def html_files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.html"))}


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("fx")
    cfg = load_config(FIXTURES / "config.yml")
    cfg.out = out / "html"
    cfg.state_dir = out / "state"
    return cfg, build(cfg, log=lambda *_: None)


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
    if not EXPECTED.exists():
        pytest.skip("fixtures/expected/ が無い")
    expected = html_files(EXPECTED)
    assert sorted(actual) == sorted(expected)
    for rel in expected:
        assert actual[rel] == expected[rel], f"出力が違います: {rel}"


def test_karakuri_chain(result):
    """Phase D: 『絡繰異聞』の鎖がハブの並びどおり一本に繋がる。"""
    cfg, res = result
    chapters = [p for p in res.pages if p.rel.startswith("創作/絡繰異聞/")]
    if not chapters:
        pytest.skip("絡繰異聞が写しに無い")
    hub = (cfg.out / "創作/絡繰異聞.html").read_text(encoding="utf-8")
    import re

    order = re.findall(r'href="絡繰異聞/([^"]+)\.html"', hub)
    assert len(order) == len(chapters)
    for i, name in enumerate(order):
        html = (cfg.out / "創作/絡繰異聞" / (name + ".html")).read_text(encoding="utf-8")
        assert ("rel=\"prev\"" in html) == (i > 0), name
        assert ("rel=\"next\"" in html) == (i < len(order) - 1), name
        if i < len(order) - 1:
            assert f'href="{order[i + 1]}.html" rel="next"' in html, name
    total_ruby = sum((cfg.out / "創作/絡繰異聞" / (n + ".html")).read_text(encoding="utf-8").count("<ruby>") for n in order)
    assert total_ruby > 5000


def test_trpg_fold(result):
    """Phase B: 折りたたみ Callout が details で閉じている。"""
    cfg, _ = result
    f = cfg.out / "TRPG/SW2.5/2026-03-08（ダニエル卓）.html"
    if not f.is_file():
        pytest.skip("ダニエル卓が写しに無い")
    html = f.read_text(encoding="utf-8")
    assert '<details class="callout callout-warning">\n<summary>以下、ネタバレあるかも</summary>' in html
    assert "<details open" not in html
    sheet = (cfg.out / "TRPG/SW2.5/リシェルエナ.html").read_text(encoding="utf-8")
    assert "<p>#カントリーフェスタ卓" in sheet  # タグの行は見出しにしない


def test_scribble_raw_html():
    """Phase C: 公開指定の無い走り書きを直接通し、生 HTML が残る。"""
    src = FIXTURES / "vault/any/走り書き用.md"
    if not src.is_file():
        pytest.skip("走り書き用が写しに無い")
    html = render_file(src)
    for needle in ("<audio controls", "<video playsinline", '<iframe id="youtube"', 'data-lightbox="bousai"', 'data-title="防災ポーチ"'):
        assert needle in html, needle
