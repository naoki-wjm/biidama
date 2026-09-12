"""サイトの束（タグページ・OGP・Pygments・読者の好みの土台）の確認。"""

from __future__ import annotations

from pathlib import Path

import pytest

from biidama import BuildError
from biidama.build import build, summarize
from biidama.config import Config, SiteConfig, load_config

PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"
TAGGED = "---\npublish: true\ncreated: 2026-01-0{d}\ntags:\n  - {tag}\n---\n"


def make_vault(tmp_path: Path, files: dict[str, str], url: str = "", icon: str = "", **site) -> Config:
    vault = tmp_path / "vault"
    for rel, text in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return Config(vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t", url=url, icon=icon, **site))


def run(tmp_path, files, url="", icon="", **site):
    cfg = make_vault(tmp_path, files, url, icon, **site)
    return cfg, build(cfg, log=lambda *_: None)


def read(cfg: Config, rel: str) -> str:
    return (cfg.out / rel).read_text(encoding="utf-8")


def test_tag_pages_and_links(tmp_path):
    files = {
        "index.md": PUB + "入口",
        "a.md": TAGGED.format(d=1, tag="創作") + "a",
        "b.md": TAGGED.format(d=2, tag="創作") + "b",
        "c.md": TAGGED.format(d=3, tag="雑記") + "c",
    }
    cfg, res = run(tmp_path, files)
    assert [t.tag for t in res.tags] == ["創作", "雑記"]  # 多い順
    tag_page = read(cfg, "タグ/創作.html")
    # 新しい順に並び、ページへ戻れる
    assert tag_page.index('href="../b.html"') < tag_page.index('href="../a.html"')
    assert "2 ページ" in tag_page
    # 一覧ページ、フッターからの導線、ページ側のタグはリンク
    tags_page = read(cfg, "タグ.html")
    assert 'href="タグ/創作.html">#創作</a> <span class="count">2</span>' in tags_page
    assert 'href="タグ.html">タグ一覧</a>' in read(cfg, "index.html")
    assert '<a class="tag" href="タグ/雑記.html">#雑記</a>' in read(cfg, "c.html")
    # manifest にも載る（publish が送る）
    outs = {p["out"] for p in __import__("json").loads(res.manifest_path.read_text(encoding="utf-8"))["pages"]}
    assert {"タグ.html", "タグ/創作.html", "タグ/雑記.html"} <= outs


def test_no_tags_means_no_tag_pages(tmp_path):
    cfg, res = run(tmp_path, {"index.md": PUB + "入口"})
    assert res.tags == [] and not (cfg.out / "タグ.html").exists()
    assert "タグ一覧" not in read(cfg, "index.html")


def test_tag_folder_is_reserved(tmp_path):
    with pytest.raises(BuildError, match="タグ"):
        run(tmp_path, {"index.md": PUB + "入口", "タグ/x.md": PUB + "x"})
    with pytest.raises(BuildError, match="タグ"):
        run(tmp_path, {"index.md": PUB + "入口", "タグ.md": PUB + "x"})


def test_wikilink_prefers_note_over_tag_page(tmp_path):
    # ハブ note「創作.md」とタグ「創作」が両方あっても、[[創作]] は note に行く
    files = {
        "index.md": PUB + "[[創作]]",
        "創作.md": TAGGED.format(d=1, tag="創作") + "hub",
    }
    cfg, _ = run(tmp_path, files)
    assert 'href="創作.html"' in read(cfg, "index.html")
    assert 'href="タグ/創作.html"' not in read(cfg, "index.html")


def test_ogp_and_description(tmp_path):
    files = {
        "index.md": PUB + "入口",
        "a.md": "---\npublish: true\ncreated: 2026-01-01\ndescription: 手書きの説明\n---\n本文",
        "b/c.md": PUB + "# 見出し\n\n最初の段落が **説明** になる。二つ目の段落。",
    }
    cfg, _ = run(tmp_path, files, url="https://example.com/site")
    a = read(cfg, "a.html")
    assert '<meta name="description" content="手書きの説明">' in a
    assert '<meta property="og:description" content="手書きの説明">' in a
    assert '<meta property="og:url" content="https://example.com/site/a.html">' in a
    assert '<meta property="og:type" content="article">' in a
    assert '<meta property="og:site_name" content="t">' in a
    c = read(cfg, "b/c.html")
    assert '<meta property="og:url" content="https://example.com/site/b/c.html">' in c
    assert 'content="見出し 最初の段落が 説明 になる。二つ目の段落。"' in c
    # url が無ければ og:url は書かない
    cfg2, _ = run(tmp_path / "2", {"index.md": PUB + "入口"})
    assert "og:url" not in read(cfg2, "index.html")


def test_summarize_cuts_and_unescapes():
    assert summarize("<p>a &amp; b</p>") == "a & b"
    assert summarize("<p>" + "あ" * 200 + "</p>", limit=10) == "あ" * 9 + "…"


def test_pygments_colors_known_language_only(tmp_path):
    files = {"index.md": PUB + "```python\nprint(1)\n```\n\n```\nplain\n```\n\n```nosuchlang\nx\n```\n"}
    cfg, _ = run(tmp_path, files)
    html = read(cfg, "index.html")
    assert '<div class="highlight"><span class="filename">Python</span><pre><span></span><code><span class="nb">print</span>' in html
    assert '<div class="highlight"><pre><span></span><code>plain' in html  # 言語なしは色も札も無し
    assert "Text Only" not in html
    assert html.count('<div class="highlight">') == 3  # 枠は全部同じ見た目


def test_head_has_reader_prefs_and_static(tmp_path):
    cfg, _ = run(tmp_path, {"index.md": PUB + "入口"})
    html = read(cfg, "index.html")
    assert '<script src="static/site.js?v=' in html and "defer" not in html.split("site.js")[1].split(">")[0]
    assert '<link rel="stylesheet" href="static/pygments.css?v=' in html
    assert '<div class="prefs" hidden></div>' in html
    assert "og:image" not in html and 'rel="icon"' not in html  # site.icon を書かなければ何も出ない


def test_theme_color_and_head_extra(tmp_path):
    line = '<meta name="fediverse:creator" content="@x@example.social">'
    cfg, _ = run(tmp_path, {"index.md": PUB + "入口", "a/b.md": PUB + "b"}, theme_color="#4aa0d2", head_extra=[line])
    html = read(cfg, "a/b.html")
    assert '<meta name="theme-color" content="#4aa0d2">' in html
    assert line in html and html.index(line) < html.index("</head>")  # そのまま、エスケープせずに head の中へ
    cfg2, _ = run(tmp_path / "2", {"index.md": PUB + "入口"})
    assert "theme-color" not in read(cfg2, "index.html")


def test_icon_must_exist_in_static(tmp_path):
    cfg, res = run(tmp_path, {"index.md": PUB + "入口"}, url="https://example.com/", icon="static/nothing.png")
    assert any("site.icon" in w for w in res.warnings)
    assert "og:image" not in read(cfg, "index.html")


# ---- 最近の更新 ----------------------------------------------------------------

DATED = "---\npublish: true\ncreated: 2026-01-01\nmodified: {m}\n---\n"


def test_recent_list_and_home(tmp_path):
    files = {
        "index.md": DATED.format(m="2026-09-09") + "入口",
        "a.md": DATED.format(m="2026-03-03") + "a",
        "b.md": DATED.format(m="2026-05-05") + "b",
        "c.md": DATED.format(m="2026-05-05") + "c",
        "d.md": "---\npublish: true\n---\nd",  # 日付が無いページは載らない
        "s/e.md": DATED.format(m="2026-08-08") + "e",
    }
    cfg, res = run(tmp_path, files, recent=3, recent_home=2)
    # 新しい順、同じ日は名前順、トップ自身は入らない、件数で切る
    assert [p.rel for p in res.recent.pages] == ["s/e", "b", "c"]
    lst = read(cfg, "最近の更新.html")
    assert "更新日の新しい順・3 ページ" in lst
    assert lst.index('href="s/e.html"') < lst.index('href="b.html"') < lst.index('href="c.html"')
    assert '<time datetime="2026-08-08">' in lst and "a.html" not in lst and "d.html" not in lst
    # トップの末尾には先頭 2 件と「もっと見る」。他のページには出ない
    home = read(cfg, "index.html")
    assert '<section class="recent">' in home and 'href="s/e.html"' in home and 'href="b.html"' in home and 'href="c.html"' not in home
    assert 'href="最近の更新.html">もっと見る</a>' in home
    assert '<section class="recent">' not in read(cfg, "a.html")
    # フッターの導線と manifest
    assert 'href="../最近の更新.html">最近の更新</a>' in read(cfg, "s/e.html")
    outs = {p["out"] for p in __import__("json").loads(res.manifest_path.read_text(encoding="utf-8"))["pages"]}
    assert "最近の更新.html" in outs


def test_recent_on_auto_home_index(tmp_path):
    """トップが index.md ではなく自動索引でも、末尾に出る。"""
    cfg, res = run(tmp_path, {"a.md": DATED.format(m="2026-03-03") + "a"}, recent=5, recent_home=5)
    home = read(cfg, "index.html")
    assert '<section class="recent">' in home and 'href="a.html"' in home


def test_recent_follows_ledger_dates(tmp_path):
    """並びは frontmatter の modified ではなく、台帳の更新日（本文ハッシュが一致すれば台帳の日付）。"""
    files = {"index.md": DATED.format(m="2026-01-01") + "入口", "a.md": DATED.format(m="2026-09-09") + "a", "b.md": DATED.format(m="2026-01-01") + "b"}
    cfg = make_vault(tmp_path, files, recent=5, recent_home=5)
    from biidama.vault import scan

    pages = {p.rel: p for p in scan(cfg, [])}
    cfg.state_dir.mkdir()
    ledger = {"pages": {"a.md": {"hash": pages["a"].body_hash(), "updated": "2026-02-02"}, "b.md": {"hash": pages["b"].body_hash(), "updated": "2026-06-06"}}}
    (cfg.state_dir / "ledger.json").write_text(__import__("json").dumps(ledger), encoding="utf-8")
    res = build(cfg, log=lambda *_: None)
    assert [p.rel for p in res.recent.pages] == ["b", "a"]


def test_recent_zero_disables(tmp_path):
    files = {"index.md": DATED.format(m="2026-01-01") + "入口", "a.md": DATED.format(m="2026-03-03") + "a"}
    cfg, res = run(tmp_path, files, recent=0, recent_home=0)
    assert res.recent is None and not (cfg.out / "最近の更新.html").exists()
    assert "最近の更新" not in read(cfg, "index.html")
    # 一覧ページは無しでトップにだけ出す（「もっと見る」は付かない）
    cfg, res = run(tmp_path, files, recent=0, recent_home=3)
    assert res.recent is None and not (cfg.out / "最近の更新.html").exists()
    home = read(cfg, "index.html")
    assert '<section class="recent">' in home and "もっと見る" not in home and "footer-recent" not in home


def test_recent_name_is_reserved(tmp_path):
    with pytest.raises(BuildError, match="最近の更新"):
        run(tmp_path, {"index.md": PUB + "入口", "最近の更新.md": PUB + "x"})


def test_recent_config_values(tmp_path):
    (tmp_path / "v").mkdir()
    cfgp = tmp_path / "c.yml"
    cfgp.write_text("vault: ./v\nsite:\n  recent: 7\n  recent_home: 0\n", encoding="utf-8")
    site = load_config(cfgp).site
    assert (site.recent, site.recent_home) == (7, 0)
    cfgp.write_text("vault: ./v\n", encoding="utf-8")
    site = load_config(cfgp).site
    assert (site.recent, site.recent_home) == (20, 5)
    cfgp.write_text("vault: ./v\nsite:\n  recent: -1\n", encoding="utf-8")
    with pytest.raises(BuildError, match="site.recent"):
        load_config(cfgp)
