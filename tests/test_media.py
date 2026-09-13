"""メディア（保管庫のフォルダの複製・![[ ]] の埋め込み・縮小版）の確認。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from biidama import BuildError
from biidama.build import build
from biidama.config import Config, MediaConfig, SiteConfig, load_config, load_media
from biidama.features import media as media_mod
from biidama.features.media import Embed, parse_embed

PUB = "---\npublish: true\ncreated: 2026-01-01\n---\n"


def make_vault(tmp_path: Path, files: dict[str, str | bytes], media: MediaConfig | None = None) -> Config:
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
    return Config(
        vault=vault, out=tmp_path / "out", state_dir=tmp_path / "state", site=SiteConfig(name="t"),
        media=media if media is not None else MediaConfig(dir="メディア", thumbnail=200, quality=80),
    )


def run(tmp_path, files, media=None):
    cfg = make_vault(tmp_path, files, media)
    return cfg, build(cfg, log=lambda *_: None)


def read(cfg: Config, rel: str) -> str:
    return (cfg.out / rel).read_text(encoding="utf-8")


# ---- 読み方 ------------------------------------------------------------------

def test_parse_embed():
    assert parse_embed("絵.png") == Embed("絵.png", "", "", "")
    assert parse_embed("絵.png|300") == Embed("絵.png", "", "300", "")
    assert parse_embed("絵.png|300x200") == Embed("絵.png", "", "300", "200")
    assert parse_embed("絵.png|説明") == Embed("絵.png", "説明", "", "")
    assert parse_embed("絵.png|説明|120") == Embed("絵.png", "説明", "120", "")
    assert parse_embed("絵.png|x120") == Embed("絵.png", "", "", "120")
    assert parse_embed("絵.png|x") == Embed("絵.png", "x", "", "")


def test_config_media_forms(tmp_path):
    assert load_media(None) == MediaConfig()
    assert load_media("素材") == MediaConfig(dir="素材")
    assert load_media({"dir": "/素材/", "thumbnail": 0}) == MediaConfig(dir="素材", thumbnail=0)
    with pytest.raises(BuildError, match="media.thumbnail"):
        load_media({"dir": "x", "thumbnail": -1})
    with pytest.raises(BuildError, match="media.quality"):
        load_media({"dir": "x", "quality": 101})
    with pytest.raises(BuildError, match="media"):
        load_media(["x"])
    cfg_path = tmp_path / "c.yml"
    (tmp_path / "v").mkdir()
    cfg_path.write_text("vault: ./v\nmedia: メディア\n", encoding="utf-8")
    assert load_config(cfg_path).media.dir == "メディア"


# ---- 埋め込み ------------------------------------------------------------------

def test_image_embed_with_thumbnail_and_lightbox(tmp_path):
    cfg, res = run(tmp_path, {"index.md": PUB + "![[絵.png|150]]", "メディア/a/絵.png": "@png"})
    html = read(cfg, "index.html")
    assert '<a data-lightbox="index" href="メディア/a/絵.png"><img alt="" loading="lazy" src="メディア/a/絵.png.thumb.webp" width="150"></a>' in html
    assert (cfg.out / "メディア/a/絵.png").is_file()
    with Image.open(cfg.out / "メディア/a/絵.png.thumb.webp") as im:
        assert im.size == (200, 100)
    assert res.warnings == []


def test_thumbnail_cache_is_reused(tmp_path):
    files = {"index.md": PUB + "![[絵.png]]", "メディア/絵.png": "@png"}
    cfg = make_vault(tmp_path, files)
    build(cfg, log=lambda *_: None)
    cached = list((cfg.state_dir / "thumbs").glob("*.webp"))
    assert len(cached) == 1
    stamp = cached[0].stat().st_mtime_ns
    messages: list[str] = []
    build(cfg, log=messages.append)
    assert cached[0].stat().st_mtime_ns == stamp
    assert not any("縮小版を" in m for m in messages)
    assert (cfg.out / "メディア/絵.png.thumb.webp").is_file()


def test_thumbnail_off_uses_original(tmp_path):
    cfg, _ = run(tmp_path, {"index.md": PUB + "![[絵.png]]", "メディア/絵.png": "@png"}, MediaConfig(dir="メディア", thumbnail=0))
    assert 'src="メディア/絵.png"' in read(cfg, "index.html")
    assert not (cfg.out / "メディア/絵.png.thumb.webp").exists()


def test_without_pillow_warns_and_uses_original(tmp_path, monkeypatch):
    monkeypatch.setattr(media_mod, "pillow_available", lambda: False)
    cfg, res = run(tmp_path, {"index.md": PUB + "![[絵.png]]", "メディア/絵.png": "@png"})
    assert 'src="メディア/絵.png"' in read(cfg, "index.html")
    assert any("Pillow" in w for w in res.warnings)


def test_gif_and_svg_get_no_thumbnail(tmp_path):
    files = {"index.md": PUB + "![[動く.gif]] ![[図.svg]]", "メディア/動く.gif": b"GIF89a", "メディア/図.svg": "<svg/>"}
    cfg, _ = run(tmp_path, files)
    html = read(cfg, "index.html")
    assert 'src="メディア/動く.gif"' in html and 'src="メディア/図.svg"' in html


def test_audio_and_video_embed(tmp_path):
    files = {"index.md": PUB + "![[曲.mp3]]\n\n![[動.mp4]]", "メディア/曲.mp3": b"ID3", "メディア/動.mp4": b"ftyp"}
    cfg, _ = run(tmp_path, files)
    html = read(cfg, "index.html")
    assert '<audio controls preload="metadata" src="メディア/曲.mp3"></audio>' in html
    assert '<video controls playsinline preload="metadata" src="メディア/動.mp4"></video>' in html


def test_embed_resolves_by_vault_path_and_media_path(tmp_path):
    files = {"index.md": PUB + "![[メディア/a/絵.png]] ![[a/絵.png]]", "メディア/a/絵.png": "@png"}
    cfg, _ = run(tmp_path, files)
    assert read(cfg, "index.html").count('href="メディア/a/絵.png"') == 2


# ---- 止まる所 ------------------------------------------------------------------

def test_embed_without_media_dir_stops(tmp_path):
    with pytest.raises(BuildError, match="media.dir"):
        run(tmp_path, {"index.md": PUB + "![[絵.png]]"}, MediaConfig())


def test_missing_media_dir_stops(tmp_path):
    with pytest.raises(BuildError, match="保管庫にありません"):
        run(tmp_path, {"index.md": PUB + "x"})


def test_embed_target_not_in_media_stops(tmp_path):
    files = {"index.md": PUB + "![[無い.png]]", "メディア/絵.png": "@png", "他/無い.png": "@png"}
    with pytest.raises(BuildError, match="メディアのフォルダ"):
        run(tmp_path, files)


def test_embed_basename_ambiguity_stops(tmp_path):
    files = {"index.md": PUB + "![[絵.png]]", "メディア/a/絵.png": "@png", "メディア/b/絵.png": "@png"}
    with pytest.raises(BuildError, match="候補が複数"):
        run(tmp_path, files)


def test_note_embed_stops(tmp_path):
    files = {"index.md": PUB + "![[他]]", "他.md": PUB + "y", "メディア/絵.png": "@png"}
    with pytest.raises(BuildError, match="メディアのフォルダ"):
        run(tmp_path, files)


def test_unknown_kind_stops(tmp_path):
    files = {"index.md": PUB + "![[書類.pdf]]", "メディア/書類.pdf": b"%PDF"}
    with pytest.raises(BuildError, match="未対応"):
        run(tmp_path, files)


def test_same_stem_different_ext_both_get_thumbnails(tmp_path):
    files = {"index.md": PUB + "![[絵.png]] ![[絵.jpg]]", "メディア/絵.png": "@png", "メディア/絵.jpg": "@png"}
    cfg, _ = run(tmp_path, files)
    assert (cfg.out / "メディア/絵.png.thumb.webp").is_file() and (cfg.out / "メディア/絵.jpg.thumb.webp").is_file()


def test_thumb_suffix_in_vault_stops(tmp_path):
    files = {"index.md": PUB + "x", "メディア/絵.png.thumb.webp": b"RIFF"}
    with pytest.raises(BuildError, match="thumb.webp"):
        run(tmp_path, files)


def test_note_inside_media_dir_stops(tmp_path):
    files = {"index.md": PUB + "x", "メディア/説明.md": PUB + "y", "メディア/絵.png": "@png"}
    with pytest.raises(BuildError, match="メディアのフォルダ"):
        run(tmp_path, files)


def test_embed_inside_raw_html_is_left_alone(tmp_path):
    files = {"index.md": PUB + '<span title="![[絵.png]]">x</span>', "メディア/絵.png": "@png"}
    cfg, _ = run(tmp_path, files)
    assert 'title="![[絵.png]]"' in read(cfg, "index.html")
    assert not (cfg.out / "メディア/絵.png.thumb.webp").exists()
