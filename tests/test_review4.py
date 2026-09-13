"""第4回査読（2026-09-13）の指摘の再現。直したことを固定する。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from biidama import BuildError
from biidama.build import build
from biidama.config import Config, MediaConfig, SiteConfig, load_media

PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"


def make_vault(tmp_path: Path, files: dict[str, str | bytes], media: MediaConfig | None = None, **site) -> Config:
    vault = tmp_path / "vault"
    for rel, content in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        elif content == "@png":
            Image.new("RGB", (600, 300), (10, 20, 30)).save(p)
        else:
            p.write_text(content, encoding="utf-8")
    return Config(vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t", **site), media=media or MediaConfig())


def run(tmp_path, files, **kw):
    cfg = make_vault(tmp_path, files, **kw)
    return cfg, build(cfg, log=lambda *_: None)


# ---- 1. タグ名の .. が出力先を抜ける ---------------------------------------------------------

@pytest.mark.parametrize("tag", ["../index", "../../escaped", ".", "a/../b", "a//b", "a\\b", "c:d"])
def test_dangerous_tag_name_stops(tmp_path, tag):
    files = {"index.md": f"---\npublish: true\ncreated: 2026-01-01\ntags: ['{tag}']\n---\nx"}
    cfg = make_vault(tmp_path, files)
    cfg.out.mkdir()
    (cfg.out / ".biidama-out").write_text("x")
    (cfg.out / "index.html").write_text("旧出力", encoding="utf-8")
    with pytest.raises(BuildError, match="タグ名"):
        build(cfg, log=lambda *_: None)
    assert (cfg.out / "index.html").read_text(encoding="utf-8") == "旧出力"  # 旧出力に触れていない
    assert not (tmp_path / "escaped.html").exists()


def test_hierarchical_tag_still_works(tmp_path):
    cfg, _ = run(tmp_path, {"index.md": "---\npublish: true\ncreated: 2026-01-01\ntags: [a/b]\n---\nx"})
    assert (cfg.out / "タグ/a/b.html").is_file()


# ---- 2. タグページ同士の衝突 ----------------------------------------------------------------

def test_tag_case_collision_stops(tmp_path):
    files = {
        "index.md": "---\npublish: true\ncreated: 2026-01-01\ntags: [Foo]\n---\nx",
        "b.md": "---\npublish: true\ncreated: 2026-01-02\ntags: [foo]\n---\ny",
    }
    with pytest.raises(BuildError, match="同じ出力先"):
        run(tmp_path, files)


# ---- 3. media.dir の境界 ----------------------------------------------------------------------

@pytest.mark.parametrize("d", [".", "..", "../other", "/abs", "C:/x", "a/../b", "a/./b"])
def test_media_dir_outside_vault_rejected_in_config(d):
    with pytest.raises(BuildError, match="media.dir"):
        load_media({"dir": d})


def test_media_dir_pointing_at_vault_itself_stops(tmp_path):
    # 設定の文字列は通っても、実体が保管庫そのものなら止める（例: 保管庫直下の "x/.." のような記号ではなく symlink 等）
    files = {"index.md": PUB + "x", "private.md": "非公開", "メディア/絵.png": "@png"}
    cfg = make_vault(tmp_path, files, media=MediaConfig(dir="メディア"))
    cfg.media.dir = "."  # load_media を迂回して直接書き換えた場合でも MediaIndex が止める
    with pytest.raises(BuildError, match="保管庫の中のフォルダ"):
        build(cfg, log=lambda *_: None)
    assert not (cfg.out / "private.md").exists()


# ---- 4. 壊れた画像で止まった時に旧出力を失わない ---------------------------------------------------

def test_broken_image_keeps_old_output(tmp_path):
    files = {"index.md": PUB + "x", "メディア/絵.png": "@png"}
    cfg = make_vault(tmp_path, files, media=MediaConfig(dir="メディア", thumbnail=100))
    build(cfg, log=lambda *_: None)
    old_html = (cfg.out / "index.html").read_text(encoding="utf-8")
    (cfg.vault / "index.md").write_text(PUB + "![[絵.png]]", encoding="utf-8")
    (cfg.vault / "メディア/絵.png").write_bytes(b"not a png")
    with pytest.raises(BuildError, match="縮小版を作れません"):
        build(cfg, log=lambda *_: None)
    assert (cfg.out / "index.html").read_text(encoding="utf-8") == old_html
    assert not list((cfg.state_dir / "thumbs").glob("*.part"))  # 書きかけを残さない


# ---- 6. recent_home が recent より多い時 ----------------------------------------------------------

def test_recent_page_is_capped_by_recent(tmp_path):
    files = {"index.md": PUB + "入口"}
    for i in range(1, 4):
        files[f"p{i}.md"] = f"---\npublish: true\ncreated: 2026-01-0{i}\n---\n{i}"
    cfg, _ = run(tmp_path, files, recent=1, recent_home=3)
    page = (cfg.out / "最近の更新.html").read_text(encoding="utf-8")
    home = (cfg.out / "index.html").read_text(encoding="utf-8")
    assert page.count("<li>") == 1
    assert home.count("<li>") == 3


# ---- 補足: メディアと同名のノートも予約 --------------------------------------------------------------

def test_note_named_like_media_dir_is_reserved(tmp_path):
    files = {"index.md": PUB + "x", "メディア.md": PUB + "y", "メディア/絵.png": "@png"}
    with pytest.raises(BuildError, match="原稿には使えません"):
        run(tmp_path, files, media=MediaConfig(dir="メディア"))
