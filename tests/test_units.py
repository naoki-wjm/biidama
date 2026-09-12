"""止めるべきところで止まり、続けてよいところで続くことの確認。"""

from __future__ import annotations

from pathlib import Path

import pytest

from biidama import BuildError
from biidama.build import build, check_out_collisions, render_file
from biidama.config import Config, SiteConfig
from biidama.links import LinkIndex, parse_wikilink, relative_href, slugify_heading
from biidama.vault import split_frontmatter


def make_vault(tmp_path: Path, files: dict[str, str]) -> Config:
    vault = tmp_path / "vault"
    for rel, text in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return Config(vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t"))


PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"


def run(tmp_path, files):
    return build(make_vault(tmp_path, files), log=lambda *_: None)


def test_basename_ambiguity_stops(tmp_path):
    files = {"a/x.md": PUB + "a", "b/x.md": PUB + "b", "index.md": PUB + "[[x]]"}
    with pytest.raises(BuildError, match="候補が複数"):
        run(tmp_path, files)


def test_basename_ambiguity_resolved_by_path(tmp_path):
    files = {"a/x.md": PUB + "a", "b/x.md": PUB + "b", "index.md": PUB + "[[a/x]]"}
    res = run(tmp_path, files)
    assert res.warnings == []


def test_embed_stops(tmp_path):
    with pytest.raises(BuildError, match="埋め込み"):
        run(tmp_path, {"index.md": PUB + "![[画像.png]]"})


def test_block_ref_stops(tmp_path):
    with pytest.raises(BuildError, match="ブロック参照"):
        run(tmp_path, {"index.md": PUB + "[[index#^abc]]"})


def test_broken_frontmatter_public_stops(tmp_path):
    with pytest.raises(BuildError, match="frontmatter"):
        run(tmp_path, {"index.md": PUB + "ok", "x.md": "---\npublish: true\ntags: [a\n---\nbody"})


def test_broken_frontmatter_private_warns(tmp_path):
    res = run(tmp_path, {"index.md": PUB + "ok", "x.md": "---\ntags: [a\n---\nbody"})
    assert any("x.md" in w for w in res.warnings)


def test_publish_must_be_yaml_true(tmp_path):
    res = run(tmp_path, {"index.md": PUB + "ok", "x.md": "---\npublish: 'true'\n---\nbody"})
    assert [p.rel for p in res.pages] == ["index"]


def test_next_chain_and_warnings(tmp_path):
    files = {
        "a.md": PUB + "1",
        "b.md": "---\npublish: true\ncreated: 2026-01-02\nnext: \"[[c]]\"\n---\n2",
        "c.md": "---\npublish: true\ncreated: 2026-01-03\nnext: \"[[存在しない]]\"\n---\n3",
        "d.md": "---\npublish: true\ncreated: 2026-01-04\nnext: \"[[c]]\"\n---\n4",
    }
    res = run(tmp_path, files)
    joined = "\n".join(res.warnings)
    assert "next の先が公開ページにありません: c.md" in joined
    assert "同じページを next に指すページが2つ" in joined
    html = (res.pages[0].src.parent.parent / "out" / "c.html").read_text(encoding="utf-8")
    assert 'rel="prev"' in html and "b.html" in html  # 先の方（b）が前のページ


def test_out_collision_stops():
    class N:
        def __init__(self, rel):
            self.rel = rel
            self.out_rel = rel + ".html"

    with pytest.raises(BuildError, match="同じ出力先"):
        check_out_collisions([N("Foo"), N("foo")])


def test_folder_index_rules(tmp_path):
    files = {
        "index.md": PUB + "[[雑記]] [[小説]] [[wiki]]",
        "雑記/2026年1月/a.md": PUB + "a",
        "小説.md": PUB + "hub",
        "小説/1.md": PUB + "1",
        "wiki/index.md": PUB + "wiki top",
        "wiki/pages/p.md": PUB + "p",
    }
    res = run(tmp_path, files)
    outs = {f.out_rel for f in res.folders}
    assert outs == {"雑記.html", "雑記/2026年1月.html", "wiki/pages.html"}
    assert res.warnings == []
    index = (res.pages[0].src.parent.parent / "out" / "index.html").read_text(encoding="utf-8")
    assert 'href="雑記.html"' in index and 'href="小説.html"' in index and 'href="wiki/index.html"' in index


def test_render_file_keeps_raw_html(tmp_path):
    src = tmp_path / "走り書き.md"
    src.write_text(
        "---\ncreated: 2026-01-01\n---\n"
        '<audio controls src="https://x/1.mp3"></audio>\n\n'
        '<a href="https://x/1.jpg" data-lightbox="g" data-title="題"><img src="https://x/1.jpg" width="150" /></a>\n\n'
        "https://example.com/x） と https://example.com/y。\n",
        encoding="utf-8",
    )
    html = render_file(src)
    assert '<audio controls src="https://x/1.mp3"></audio>' in html
    assert 'data-lightbox="g" data-title="題"' in html
    assert '<a href="https://example.com/x">https://example.com/x</a>）' in html
    assert '<a href="https://example.com/y">https://example.com/y</a>。' in html


def test_h1_dedupe_uses_filename(tmp_path):
    res = run(tmp_path, {"index.md": PUB + "ok", "題名.md": PUB + "# 題名\n\n本文\n\n# 別の見出し"})
    html = (res.pages[0].src.parent.parent / "out" / "題名.html").read_text(encoding="utf-8")
    assert html.count("<h1") == 2  # page-title と「別の見出し」だけ
    assert 'id="別の見出し"' in html


def test_helpers():
    link = parse_wikilink("雑記/記事A#二つ目|表示")
    assert (link.target, link.heading, link.alias) == ("雑記/記事A", "二つ目", "表示")
    assert slugify_heading("  CORS（Cross-Origin Resource Sharing）の壁 ") == "CORS（Cross-Origin-Resource-Sharing）の壁"
    assert relative_href("a/b/c.html", "a/d.html", "見 出し") == "../d.html#見-出し"
    assert relative_href("index.html", "LLM wiki/index.html") == "LLM%20wiki/index.html"
    fm, body, broken = split_frontmatter("﻿---\npublish: true\n---\n本文")
    assert fm == {"publish": True} and body == "本文" and not broken
    assert split_frontmatter("本文だけ") == ({}, "本文だけ", False)


def test_index_prefers_path_then_basename():
    class N:
        kind = "page"

        def __init__(self, rel):
            self.rel = rel
            self.out_rel = rel + ".html"
            self.title = rel

    idx = LinkIndex([N("index"), N("LLM wiki/index"), N("a/b")])
    assert idx.resolve("index").rel == "index"
    assert idx.resolve("LLM wiki").rel == "LLM wiki/index"
    assert idx.resolve("b").rel == "a/b"
    assert idx.resolve("a/b.md").rel == "a/b"
    assert idx.resolve("nothing") is None


def test_updated_date_rules(tmp_path):
    import datetime as dt

    from biidama.build import updated_date

    src = tmp_path / "x.md"
    src.write_text("---\npublish: true\ncreated: 2026-01-01\nmodified: 2026-02-01\n---\n本文", encoding="utf-8")
    from biidama.vault import load_page

    page = load_page(src, "x", [])
    today = dt.date(2026, 9, 12)
    assert updated_date(page, {}, today) == dt.date(2026, 2, 1)  # 台帳なし → modified
    same = {"x.md": {"hash": page.body_hash(), "updated": "2026-03-03"}}
    assert updated_date(page, same, today) == dt.date(2026, 3, 3)  # 一致 → 台帳の日付
    changed = {"x.md": {"hash": "0" * 64, "updated": "2026-03-03"}}
    assert updated_date(page, changed, today) == today  # 本文が変わった → 今日
