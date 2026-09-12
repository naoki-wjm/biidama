"""前後ナビ。frontmatter の next から「次のページ」を、逆引きで「前のページ」を決める。"""

from __future__ import annotations

from dataclasses import dataclass

from ..links import LinkIndex, Node, parse_wikilink
from ..vault import Page


@dataclass
class Nav:
    prev: Node | None = None
    next: Node | None = None


def next_target(raw: str) -> str:
    """next の値（"[[X]]" か "X"）からリンク先の文字列を取り出す。"""
    s = raw.strip()
    if s.startswith("[[") and s.endswith("]]"):
        return parse_wikilink(s[2:-2]).target
    return s


def compute_nav(pages: list[Page], index: LinkIndex, warnings: list[str]) -> dict[str, Nav]:
    navs: dict[str, Nav] = {p.rel: Nav() for p in pages}
    for p in sorted(pages, key=lambda x: x.rel):
        raw = p.next_raw
        if not raw:
            continue
        target = index.resolve(next_target(raw))
        if target is None:
            warnings.append(f"next の先が公開ページにありません: {p.rel}.md → {raw}")
            continue
        navs[p.rel].next = target
        back = navs.get(target.rel)
        if back is None:
            continue
        if back.prev is not None:
            warnings.append(
                f"同じページを next に指すページが2つあります（前のページは先の方を採用）: "
                f"{back.prev.rel} と {p.rel} → {target.rel}"
            )
            continue
        back.prev = p
    return navs
