"""「最近の更新」の一覧。

各ページの更新日（build が台帳と本文ハッシュから決めたもの）で新しい順に並べる。
出力先は 最近の更新.html（原稿側ではこの名前は予約）。トップページの末尾にも先頭の数件を出す。
台帳には最新の一日しか無いので、これは「履歴」ではなく「いま新しい順」。手書きの履歴は持たない。
wikilink の解決先には入れない（タグページと同じ扱い）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .vault import Page

RECENT_NAME = "最近の更新"
HOME_OUT = "index.html"  # トップページ。一覧を載せる側なので一覧には入れない


@dataclass
class RecentList:
    pages: list[Page] = field(default_factory=list)  # 更新日の新しい順
    dates: dict[str, dt.date] = field(default_factory=dict)  # rel → 更新日
    kind: str = "recent"
    rel: str = RECENT_NAME
    title: str = "最近の更新"

    @property
    def out_rel(self) -> str:
        return self.rel + ".html"

    def head(self, n: int) -> list[Page]:
        return self.pages[:n] if n > 0 else []


def make_recent(pages: list[Page], updated: dict[str, dt.date | None], count: int) -> RecentList | None:
    """更新日のあるページを新しい順に count 件。count が 0 以下なら None。"""
    if count <= 0:
        return None
    dated = [(d, p) for p in pages if (d := updated.get(p.rel)) and p.out_rel != HOME_OUT]
    # 新しい順。同じ日なら名前順（同日に置いた連載の 01→10 が素直に並ぶ）
    dated.sort(key=lambda dp: (-dp[0].toordinal(), dp[1].stem))
    chosen = dated[:count]
    return RecentList(pages=[p for _, p in chosen], dates={p.rel: d for d, p in chosen})
