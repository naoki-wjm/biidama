"""保管庫を歩いて、公開ページ（publish: true）だけを拾う。"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import BuildError
from .config import Config

FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
PUBLISH_LINE_RE = re.compile(r"^publish:\s*true\s*$", re.M)


@dataclass
class Page:
    """公開ページ一枚。rel は保管庫ルートからの相対パス（区切りは /、拡張子なし）。"""

    src: Path
    rel: str
    frontmatter: dict
    body: str
    kind: str = "page"

    @property
    def stem(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else ""

    @property
    def out_rel(self) -> str:
        return self.rel + ".html"

    @property
    def title(self) -> str:
        t = self.frontmatter.get("title")
        return str(t).strip() if t not in (None, "") else self.stem

    @property
    def tags(self) -> list[str]:
        t = self.frontmatter.get("tags")
        if t is None:
            return []
        if isinstance(t, str):
            return [t]
        return [str(x) for x in t]

    @property
    def next_raw(self) -> str | None:
        n = self.frontmatter.get("next")
        return str(n) if n not in (None, "") else None

    created: dt.date | None = field(default=None)
    modified: dt.date | None = field(default=None)

    def body_hash(self) -> str:
        """本文だけのハッシュ。frontmatter と行末空白は含めない（更新日の判定用）。"""
        normalized = "\n".join(line.rstrip() for line in self.body.splitlines()).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_frontmatter(text: str) -> tuple[dict | None, str, bool]:
    """(frontmatter, 本文, 破損か) を返す。frontmatter が無ければ ({}, 全文, False)。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.lstrip("﻿"), False
    body = text[m.end():]
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, body, True
    if data is None:
        return {}, body, False
    if not isinstance(data, dict):
        return None, body, True
    return data, body, False


def normalize_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def load_page(src: Path, rel: str, warnings: list[str]) -> Page | None:
    """一枚読んで、公開ページなら Page を返す。非公開なら None。"""
    text = src.read_text(encoding="utf-8")
    fm, body, broken = split_frontmatter(text)
    if broken:
        if PUBLISH_LINE_RE.search(text[:2000]):
            raise BuildError(f"公開ページの frontmatter が読めません: {rel}.md")
        warnings.append(f"frontmatter が読めないので飛ばしました（非公開扱い）: {rel}.md")
        return None
    if fm.get("publish") is not True:
        return None
    page = Page(src=src, rel=rel, frontmatter=fm, body=body)
    page.created = normalize_date(fm.get("created"))
    page.modified = normalize_date(fm.get("modified"))
    if page.created is None:
        warnings.append(f"created が無い（または読めない）ので並び順の末尾に置きます: {rel}.md")
    return page


def scan(cfg: Config, warnings: list[str]) -> list[Page]:
    """保管庫を歩き、除外フォルダを飛ばして公開ページを集める。"""
    excluded = tuple(cfg.exclude)
    pages: list[Page] = []
    for src in sorted(cfg.vault.rglob("*.md")):
        rel_path = src.relative_to(cfg.vault).as_posix()
        parts = rel_path.split("/")
        if any(p.startswith(".") for p in parts[:-1]):
            continue
        if any(rel_path == ex or rel_path.startswith(ex + "/") for ex in excluded):
            continue
        rel = rel_path[:-3]
        page = load_page(src, rel, warnings)
        if page is not None:
            pages.append(page)
    return pages
