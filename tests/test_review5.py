"""第5回査読（2026-09-20）の指摘の再現。直したことを固定する。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import pytest

from biidama import BuildError
from biidama.build import build
from biidama.config import Config, SiteConfig, load_config

PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"


def run(tmp_path: Path, files: dict[str, str], **site):
    vault = tmp_path / "vault"
    for rel, text in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    cfg = Config(vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t", **site))
    return cfg, build(cfg, log=lambda *_: None)


def read(cfg: Config, rel: str) -> str:
    return (cfg.out / rel).read_text(encoding="utf-8")


RAW_A = (
    '外 <a href="https://example.com/">中の [[b|表示名]]</a> と外の [[b]]。\n\n'
    '`[[b]]` は code。<a href="https://example.com/">![[絵.png]]</a>'
)


def test_wikilink_inside_raw_anchor_is_text_not_backlink(tmp_path):
    """B-1: 生 HTML の <a> の中の [[ ]] はリンクにせず（二重リンクにしない）、逆引きにも数えない。"""
    files = {"index.md": PUB + "入口", "雑記/b.md": PUB + "b", "雑記/a.md": PUB + RAW_A}
    cfg, res = run(tmp_path, files, backlinks=["雑記"])
    page = read(cfg, "雑記/a.html")
    assert '<a href="https://example.com/">中の 表示名</a>' in page
    assert page.count('class="internal"') == 1  # 外の [[b]] だけ
    assert "<code>[[b]]</code>" in page
    assert "![[絵.png]]" in page  # 埋め込みは触らず文字のまま（媒体の設定が無くても止まらない）
    assert any("生 HTML の <a> の中の [[b|表示名]]" in w for w in res.warnings)
    assert any("生 HTML の <a> の中の埋め込み ![[絵.png]]" in w for w in res.warnings)
    page_b = read(cfg, "雑記/b.html")
    i = page_b.index('class="backlinks"')
    assert page_b.count("<li>", i, page_b.index("</section>", i)) == 1  # a から一件（生 a の中の分は数えない）


def test_sitemap_and_rss_urls_are_percent_encoded(tmp_path):
    """B-3: 外に配る URL は UTF-8 の percent-encoding。XML として読めて、復号すると元のパスに戻る。"""
    files = {"index.md": PUB + "入口", "雑記/a & b.md": PUB + '本文 <記号> & 引用符"'}
    cfg, _ = run(tmp_path, files, url="https://example.com/")
    root = ET.fromstring(read(cfg, "sitemap.xml"))
    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert "https://example.com/%E9%9B%91%E8%A8%98/a%20%26%20b.html" in locs
    assert all(loc.isascii() for loc in locs)
    assert {unquote(loc[len("https://example.com/"):]) for loc in locs} >= {"雑記/a & b.html", "雑記.html", "index.html"}
    rss = ET.fromstring(read(cfg, "rss.xml"))
    item = rss.find("channel/item")
    assert item.findtext("link") == "https://example.com/%E9%9B%91%E8%A8%98/a%20%26%20b.html"
    assert item.findtext("title") == "a & b"
    assert item.findtext("description") == '本文 <記号> & 引用符"'  # XML の逃がしを戻すと元の文


def test_site_folders_reject_empty_and_dots(tmp_path):
    (tmp_path / "v").mkdir()
    for bad in ["['/']", "['..']", "['雑記/../x']", "['雑記//x']", "false"]:
        c = tmp_path / "c.yml"
        c.write_text(f"vault: v\nsite:\n  backlinks: {bad}\n", encoding="utf-8")
        with pytest.raises(BuildError):
            load_config(c)
    c = tmp_path / "ok.yml"
    c.write_text("vault: v\nsite:\n  random: ['/雑記/', 'LLM wiki/pages']\n", encoding="utf-8")
    assert load_config(c).site.random == ["雑記", "LLM wiki/pages"]
