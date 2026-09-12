"""タグページの自動生成。

frontmatter の tags を集め、タグごとに「そのタグの公開ページ一覧」（created 降順）と、
全タグの一覧を作る。出力先は タグ/<タグ名>.html と タグ.html（原稿側ではこの名前は予約）。
wikilink の解決先には入れない（[[創作]] がハブ note ではなくタグページに化けないように）。
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from .vault import Page

TAG_DIR = "タグ"


@dataclass
class TagIndex:
    tag: str
    kind: str = "tag"
    pages: list[Page] = field(default_factory=list)

    @property
    def rel(self) -> str:
        return f"{TAG_DIR}/{self.tag}"

    @property
    def title(self) -> str:
        return f"#{self.tag}"

    @property
    def out_rel(self) -> str:
        return self.rel + ".html"

    @property
    def created(self) -> dt.date | None:
        dates = [p.created for p in self.pages if p.created]
        return max(dates) if dates else None


@dataclass
class TagList:
    tags: list[TagIndex] = field(default_factory=list)
    kind: str = "tags"
    rel: str = TAG_DIR
    title: str = "タグ一覧"

    @property
    def out_rel(self) -> str:
        return self.rel + ".html"


def make_tag_indexes(pages: list[Page]) -> tuple[list[TagIndex], TagList | None]:
    """(タグごとの索引, 全タグの一覧)。タグが一つも無ければ (空, None)。"""
    by_tag: dict[str, list[Page]] = defaultdict(list)
    for p in pages:
        for t in dict.fromkeys(p.tags):  # 同じタグが二度書いてあっても一度だけ
            by_tag[t].append(p)
    if not by_tag:
        return [], None
    def order(ps: list[Page]) -> list[Page]:
        # 新しい順。同じ日付なら名前順（同日に置いた連載の 01→10 が素直に並ぶ）
        return sorted(ps, key=lambda p: ((p.created or dt.date.min).toordinal() * -1, p.stem))

    indexes = [TagIndex(tag=t, pages=order(ps)) for t, ps in by_tag.items()]
    # 一覧は多い順、同数なら名前順
    indexes.sort(key=lambda ti: (-len(ti.pages), ti.tag))
    return indexes, TagList(tags=indexes)
