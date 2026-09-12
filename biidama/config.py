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


@dataclass
class Config:
    vault: Path
    out: Path
    state_dir: Path
    exclude: list[str] = field(default_factory=list)
    site: SiteConfig = field(default_factory=SiteConfig)


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
    site = SiteConfig(
        name=str(site_raw.get("name", "biidama")),
        url=str(site_raw.get("url", "")),
        icon=str(site_raw.get("icon") or "").strip().lstrip("/"),
    )
    return Config(vault=vault, out=out, state_dir=state_dir, exclude=exclude, site=site)
