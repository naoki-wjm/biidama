"""メディア（画像・音源・動画）: 保管庫の中のフォルダをそのまま出力へ複製し、![[絵.png]] の埋め込みを解決する。

  ![[絵.png]]            … 表示用の縮小版を出し、押すと元画像を lightbox で開く（同じページの画像は一つの組）
  ![[絵.png|300]]        … 幅 300（Obsidian と同じ）。![[絵.png|300x200]] は幅と高さ
  ![[絵.png|説明]]       … 数字でない部分は alt と lightbox の題
  ![[曲.mp3]] / ![[動.mp4]] … <audio controls> / <video controls>

解決は wikilink と同じ流儀（パスならパス、無ければ basename の一意表。複数一致は止める）。
縮小版は長辺を media.thumbnail px までに縮めた WebP を「絵.png.thumb.webp」の名で元画像の隣に置く（拡張子違いの同名画像があっても重ならない）。
Pillow は任意の追加（pip install .[thumbnail]）。無ければ一度だけ注意して元画像をそのまま表示する。
作った縮小版は state_dir/thumbs に元の中身のハッシュ名で溜め、元が変わらない限り作り直さない。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .. import BuildError
from ..config import Config

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"}
THUMB_EXTS = {".png", ".jpg", ".jpeg", ".webp"}  # gif は動くかもしれず svg は絵でないので縮小版を作らない
AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".wav", ".flac"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
THUMB_SUFFIX = ".thumb.webp"
SIZE_RE = re.compile(r"^(\d+)(?:x(\d+))?$")


@dataclass(frozen=True)
class MediaFile:
    rel: str  # 保管庫ルートからの相対パス（区切りは /）。出力先も同じ
    src: Path

    @property
    def ext(self) -> str:
        return os.path.splitext(self.rel)[1].lower()

    @property
    def kind(self) -> str:
        if self.ext in IMAGE_EXTS:
            return "image"
        if self.ext in AUDIO_EXTS:
            return "audio"
        if self.ext in VIDEO_EXTS:
            return "video"
        return "other"

    @property
    def thumb_rel(self) -> str:
        return self.rel + THUMB_SUFFIX


@dataclass(frozen=True)
class Embed:
    target: str
    alt: str
    width: str
    height: str


def parse_embed(inner: str) -> Embed:
    """![[ ]] の中身。| で区切り、数字（幅か 幅x高さ）は大きさ、それ以外は alt。"""
    parts = [p.strip() for p in inner.split("|")]
    target = parts[0]
    alt = width = height = ""
    for p in parts[1:]:
        m = SIZE_RE.match(p)
        if m:
            width, height = m.group(1), m.group(2) or ""
        elif p:
            alt = p
    return Embed(target, alt, width, height)


def pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


class MediaIndex:
    """メディアのフォルダの一覧表。media.dir が空なら files は空で、埋め込みは止まる。"""

    def __init__(self, cfg: Config, warnings: list[str]):
        self.cfg = cfg
        self.dir = cfg.media.dir
        self.root: Path | None = (cfg.vault / self.dir) if self.dir else None
        self.files: list[MediaFile] = []
        self.by_rel: dict[str, MediaFile] = {}
        self.by_base: dict[str, list[MediaFile]] = defaultdict(list)
        self.wanted: set[str] = set()  # 縮小版が要る画像（rel）。埋め込みを解決するたびに足す
        self.thumbs = cfg.media.thumbnail > 0
        if self.root is None:
            return
        if not self.root.is_dir():
            raise BuildError(f"設定 media.dir のフォルダが保管庫にありません: {self.dir}")
        if self.thumbs and not pillow_available():
            warnings.append("Pillow が無いので縮小版は作らず、元画像をそのまま表示します（pip install .[thumbnail] で入ります）")
            self.thumbs = False
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                src = Path(dirpath) / name
                rel = src.relative_to(cfg.vault).as_posix()
                if rel.lower().endswith(THUMB_SUFFIX):
                    raise BuildError(f"{THUMB_SUFFIX} で終わる名前は縮小版に使うのでメディアには置けません: {rel}")
                f = MediaFile(rel=rel, src=src)
                self.files.append(f)
                self.by_rel[rel] = f
                self.by_rel.setdefault(rel[len(self.dir) + 1 :], f)  # メディアのフォルダからの相対でも引ける
                self.by_base[name].append(f)

    def resolve(self, target: str) -> MediaFile | None:
        t = target.strip().strip("/")
        if not t:
            return None
        if "/" in t:
            return self.by_rel.get(t)
        hit = self.by_rel.get(t)
        if hit is not None:
            return hit
        candidates = self.by_base.get(t, [])
        if len(candidates) > 1:
            raise BuildError(
                f"![[{target}]] の候補が複数あります（パスで書いてください）: " + ", ".join(sorted(c.rel for c in candidates))
            )
        return candidates[0] if candidates else None

    def display_rel(self, f: MediaFile) -> str:
        """表示用に使うファイル（縮小版か元画像）の rel。縮小版を使う時は作る予定に足す。"""
        if self.thumbs and f.ext in THUMB_EXTS:
            self.wanted.add(f.rel)
            return f.thumb_rel
        return f.rel

    # ---- 出力 ---------------------------------------------------------------

    def copy_to(self, out: Path) -> int:
        """メディアのフォルダを出力へそのまま複製する（隠しファイルは除く）。複製した数を返す。"""
        if self.root is None:
            return 0
        for f in self.files:
            dst = out / f.rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f.src, dst)
        return len(self.files)

    def write_thumbnails(self, out: Path, log=print) -> int:
        """埋め込みで使った画像の縮小版を出力へ置く。溜め場に同じものがあれば作らない。作った数を返す。"""
        if not self.wanted:
            return 0
        cache = self.cfg.state_dir / "thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        made = 0
        for rel in sorted(self.wanted):
            f = self.by_rel[rel]
            data = f.src.read_bytes()
            key = hashlib.sha256(data + f"|{self.cfg.media.thumbnail}|{self.cfg.media.quality}".encode()).hexdigest()
            cached = cache / (key + ".webp")
            if not cached.is_file():
                make_thumbnail(f.src, cached, self.cfg.media.thumbnail, self.cfg.media.quality)
                made += 1
            dst = out / f.thumb_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, dst)
        if made:
            log(f"縮小版を {made} 枚作りました（使った画像 {len(self.wanted)} 枚）")
        return made


def make_thumbnail(src: Path, dst: Path, max_edge: int, quality: int) -> None:
    from PIL import Image, ImageOps

    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)  # スマホ写真の向きを画素に焼き込む
            mode = "RGBA" if ("A" in im.getbands() or im.mode == "P" and "transparency" in im.info) else "RGB"
            im = im.convert(mode)
            im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)  # 元より小さい絵は拡大しない
            tmp = dst.with_suffix(".part")
            im.save(tmp, "WEBP", quality=quality, method=4)
    except OSError as e:
        raise BuildError(f"画像が読めないので縮小版を作れません: {src}: {e}") from e
    os.replace(tmp, dst)
