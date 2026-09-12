"""Codex 第1回査読（2026-09-12）の指摘ごとの再現と、直したことの確認。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from biidama import BuildError
from biidama.build import build, check_out_dir, render_file
from biidama.config import Config, SiteConfig

PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"


def make_cfg(tmp_path: Path, files: dict[str, str], out="out", state="state") -> Config:
    vault = tmp_path / "vault"
    for rel, text in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return Config(vault=vault, out=tmp_path / out, state_dir=tmp_path / state, site=SiteConfig(name="t"))


def render(tmp_path: Path, body: str) -> str:
    src = tmp_path / "x.md"
    src.write_text("---\ncreated: 2026-01-01\n---\n" + body, encoding="utf-8")
    return render_file(src)


# 1. 台帳の置き場が出力先の中
def test_state_dir_inside_out_stops(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "x"}, out="out", state="out/state")
    with pytest.raises(BuildError, match="state_dir"):
        check_out_dir(cfg)


# 2. 裸 URL と退避の目印・生 <a>
def test_autolink_stops_before_raw_html(tmp_path):
    html = render(tmp_path, "https://example.com/a<br>next")
    assert '<a href="https://example.com/a">https://example.com/a</a><br>next' in html
    assert "\x02" not in html and "\x03" not in html


def test_autolink_skips_inside_raw_anchor(tmp_path):
    html = render(tmp_path, '<a href="https://example.com">https://example.com</a> と https://example.com/b')
    assert html.count("<a ") == 2  # 生の a が 1 つ、自動リンクが 1 つ
    assert '<a href="https://example.com">https://example.com</a>' in html
    assert '<a href="https://example.com/b">https://example.com/b</a>' in html


# 3. 生 HTML の属性の中の wikilink・埋め込み
def test_wikilink_in_attribute_untouched(tmp_path):
    html = render(tmp_path, '<span title="[[x]]" data-t="![[y]]">text</span> と [[z]]')
    assert '<span title="[[x]]" data-t="![[y]]">text</span>' in html
    assert '<span class="unresolved-link">z</span>' in html


# 4. frontmatter の閉じ忘れ
def test_missing_closing_frontmatter_stops_when_public(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "x.md": "---\npublish: true\nbody"})
    with pytest.raises(BuildError, match="閉じ忘れ"):
        build(cfg, log=lambda *_: None)


def test_missing_closing_frontmatter_warns_when_private(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "x.md": "---\ntags: a\nbody"})
    res = build(cfg, log=lambda *_: None)
    assert any("x.md" in w for w in res.warnings)


def test_broken_yaml_with_commented_publish_stops(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "x.md": "---\npublish: true # yes\ntags: [a\n---\nbody"})
    with pytest.raises(BuildError, match="frontmatter"):
        build(cfg, log=lambda *_: None)


def test_publish_only_in_body_code_does_not_stop(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "x.md": "---\ntags: [a\n---\n```\npublish: true\n```"})
    res = build(cfg, log=lambda *_: None)
    assert any("x.md" in w for w in res.warnings)


# 5. static フォルダの予約
def test_static_folder_reserved(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "static/a.md": PUB + "a"})
    with pytest.raises(BuildError, match="static"):
        build(cfg, log=lambda *_: None)
    assert not (tmp_path / "out").exists()  # 旧出力を消す前に止まる


# 6. 失敗した build は旧出力と manifest に触らない
def test_failed_build_keeps_previous_output(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "最初"})
    build(cfg, log=lambda *_: None)
    old_html = (cfg.out / "index.html").read_text(encoding="utf-8")
    old_manifest = (cfg.state_dir / "manifest.json").read_text(encoding="utf-8")
    (cfg.vault / "index.md").write_text(PUB + "![[x]]", encoding="utf-8")
    with pytest.raises(BuildError):
        build(cfg, log=lambda *_: None)
    assert (cfg.out / "index.html").read_text(encoding="utf-8") == old_html
    assert (cfg.state_dir / "manifest.json").read_text(encoding="utf-8") == old_manifest
    assert json.loads(old_manifest)["pages"][0]["src"] == "index.md"


# 7. URL 末尾の括弧
def test_autolink_balanced_parentheses(tmp_path):
    html = render(tmp_path, "https://example.com/a_(b) と（https://example.com/x）と (https://example.com/y) と https://example.com/z。")
    assert '<a href="https://example.com/a_(b)">https://example.com/a_(b)</a>' in html
    assert '<a href="https://example.com/x">https://example.com/x</a>）' in html
    assert '(<a href="https://example.com/y">https://example.com/y</a>)' in html
    assert '<a href="https://example.com/z">https://example.com/z</a>。' in html


# 8. 全角スペース: リストでも残り、生 HTML の実体参照は触らない
def test_zenkaku_in_list_and_raw_html(tmp_path):
    html = render(tmp_path, "- 　項目\n\n1. 　番号\n\n　段落\n\n<script>const s = \"&#x3000;\";</script>")
    assert "<li>　項目</li>" in html
    assert "<li>　番号</li>" in html
    assert "<p>　段落</p>" in html
    assert 'const s = "&#x3000;";' in html
    assert "" not in html


# 9. 除外フォルダには入らない
def test_walk_prunes_excluded(tmp_path, monkeypatch):
    from biidama import vault as vault_mod

    files = {"index.md": PUB + "x", "除外/深い/a.md": PUB + "a", "残す/b.md": PUB + "b"}
    cfg = make_cfg(tmp_path, files)
    cfg.exclude = ["除外"]
    visited: list[str] = []
    real_walk = vault_mod.os.walk

    def spy(top, *a, **k):
        for dirpath, dirnames, filenames in real_walk(top, *a, **k):
            visited.append(Path(dirpath).relative_to(cfg.vault).as_posix())
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(vault_mod.os, "walk", spy)
    res = build(cfg, log=lambda *_: None)
    assert [p.rel for p in res.pages] == ["index", "残す/b"]
    assert not any(v.startswith("除外") for v in visited)


# ---- 修正確認（codex-2）の追加指摘 A〜D ----


def build_pages(tmp_path, files):
    cfg = make_cfg(tmp_path, files)
    return cfg, build(cfg, log=lambda *_: None)


# A. alias の中のルビ
def test_wikilink_alias_with_ruby(tmp_path):
    cfg, res = build_pages(tmp_path, {"index.md": PUB + "[[x|漢字《かな》]] と [[x|表示]]", "x.md": PUB + "x"})
    html = (cfg.out / "index.html").read_text(encoding="utf-8")
    assert '<a class="internal" href="x.html"><ruby>漢字<rp>(</rp><rt>かな</rt><rp>)</rp></ruby></a>' in html
    assert '<a class="internal" href="x.html">表示</a>' in html
    assert res.warnings == []


# B. 参照リンク定義やリンク構文に食われる前に埋め込みを検出する
def test_embed_detected_before_reference_links(tmp_path):
    with pytest.raises(BuildError, match="埋め込み"):
        build_pages(tmp_path, {"index.md": PUB + "![[x]]\n\n[x]: https://example.com/"})
    with pytest.raises(BuildError, match="埋め込み"):
        build_pages(tmp_path, {"index.md": PUB + "![[x]](https://example.com/)"})


def test_wikilink_and_embed_in_tags_and_comments_untouched(tmp_path):
    html = render(tmp_path, '<span title="[[x]]" data-t="![[y]]">text</span>\n<!-- [[c]] ![[d]] -->\n[[z]]')
    assert '<span title="[[x]]" data-t="![[y]]">text</span>' in html
    assert "<!-- [[c]] ![[d]] -->" in html
    assert '<span class="unresolved-link">z</span>' in html


# C. 原文に私用領域の文字があっても、目印と衝突させない
def test_private_use_char_in_source_preserved(tmp_path):
    body = "　段落にがある\n\n`code` と <span data-x=\"\">生</span>\n\n```\nfence\n```\n"
    html = render(tmp_path, body)
    assert "<p>　段落にがある</p>" in html
    assert "<code>code</code>" in html
    assert 'data-x=""' in html
    assert "fence" in html
    assert "　段落" in html  # 字下げも守られている


# D. 大文字の .MD
def test_uppercase_md_extension(tmp_path):
    cfg, res = build_pages(tmp_path, {"index.md": PUB + "[[UPPER]]", "UPPER.MD": PUB + "u"})
    assert sorted(p.rel for p in res.pages) == ["UPPER", "index"]
    assert (cfg.out / "UPPER.html").exists()
    assert res.warnings == []


# 前回試験の補い: state_dir と out が同一、長い frontmatter
def test_state_dir_equals_out_stops(tmp_path):
    cfg = make_cfg(tmp_path, {"index.md": PUB + "x"}, out="same", state="same")
    with pytest.raises(BuildError, match="state_dir"):
        check_out_dir(cfg)


def test_long_broken_frontmatter_stops(tmp_path):
    long = "description: " + "あ" * 3000 + "\npublish: true\ntags: [a\n"
    cfg = make_cfg(tmp_path, {"index.md": PUB + "ok", "x.md": "---\n" + long + "---\nbody"})
    with pytest.raises(BuildError, match="frontmatter"):
        build(cfg, log=lambda *_: None)
