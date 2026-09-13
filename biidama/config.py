"""設定ファイル（config.local.yml）の読み込み。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import BuildError


@dataclass
class SiteConfig:
    name: str = "biidama"
    url: str = ""
    icon: str = ""  # static/ の中の画像。ファビコン・OGP 画像・ヘッダーの印に使う（空なら何も出さない）
    theme_color: str = ""  # <meta name="theme-color">（ブラウザの枠の色）。空なら出さない
    head_extra: list[str] = field(default_factory=list)  # head にそのまま入れる行（作者宣言など、道具に書きたくないもの）
    recent: int = 20  # 「最近の更新」一覧（最近の更新.html）の件数。0 なら作らない
    recent_home: int = 5  # トップページの末尾に出す件数。0 なら出さない


@dataclass
class MediaConfig:
    """保管庫の中のメディア（画像・音源）のフォルダ。そのまま出力へ複製し、![[絵.png]] の解決先にする。"""

    dir: str = ""  # 保管庫ルートからの相対パス。空ならメディアの複製と埋め込みは無し（![[ ]] は止まる）
    thumbnail: int = 1200  # 表示用の縮小版の長辺の上限（px）。0 なら作らず元画像をそのまま表示
    quality: int = 80  # 縮小版（WebP）の品質


@dataclass
class Config:
    vault: Path
    out: Path
    state_dir: Path
    exclude: list[str] = field(default_factory=list)
    site: SiteConfig = field(default_factory=SiteConfig)
    media: MediaConfig = field(default_factory=MediaConfig)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.is_file():
        raise BuildError(f"設定ファイルが見つかりません: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError as e:
        raise BuildError(f"設定ファイルの YAML が読めません: {path}: {e}") from e
    if not isinstance(data, dict) or "vault" not in data:
        raise BuildError(f"設定ファイルに vault がありません: {path}")

    base = path.parent
    vault = (base / str(data["vault"])).resolve()
    if not vault.is_dir():
        raise BuildError(f"保管庫のフォルダが見つかりません: {vault}")
    out = (base / str(data.get("out", "out"))).resolve()
    state_dir = (base / str(data.get("state_dir", ".biidama"))).resolve()

    exclude = [str(x).strip("/").replace("\\", "/") for x in (data.get("exclude") or [])]
    site_raw = data.get("site") or {}

    def count(key: str, default: int) -> int:
        v = site_raw.get(key, default)
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise BuildError(f"設定 site.{key} は 0 以上の整数で書いてください: {v!r}")
        return v

    site = SiteConfig(
        name=str(site_raw.get("name", "biidama")),
        url=str(site_raw.get("url", "")),
        icon=str(site_raw.get("icon") or "").strip().lstrip("/"),
        theme_color=str(site_raw.get("theme_color") or "").strip(),
        head_extra=[str(x) for x in (site_raw.get("head_extra") or []) if str(x).strip()],
        recent=count("recent", 20),
        recent_home=count("recent_home", 5),
    )
    media = load_media(data.get("media"))
    return Config(vault=vault, out=out, state_dir=state_dir, exclude=exclude, site=site, media=media)


def load_media(raw) -> MediaConfig:
    if raw is None:
        return MediaConfig()
    if isinstance(raw, str):  # media: メディア だけの短い書き方
        raw = {"dir": raw}
    if not isinstance(raw, dict):
        raise BuildError(f"設定 media はフォルダ名か dir/thumbnail/quality の組で書いてください: {raw!r}")
    d = str(raw.get("dir") or "").strip().strip("/").replace("\\", "/")

    def number(key: str, default: int, low: int, high: int) -> int:
        v = raw.get(key, default)
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, int) or not (low <= v <= high):
            raise BuildError(f"設定 media.{key} は {low}〜{high} の整数で書いてください: {v!r}")
        return v

    return MediaConfig(dir=d, thumbnail=number("thumbnail", 1200, 0, 10000), quality=number("quality", 80, 1, 100))
