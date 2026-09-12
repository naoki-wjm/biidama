"""前後ナビ。frontmatter の prev／next で「前のページ」「次のページ」を決める。

- 自分に書いた prev／next はそのまま採用する
- 書いていない側は、相手のページの記述から逆引きで補う（B が prev: A なら A の次は B）
- 両方書いてあって食い違う時は警告し、それぞれ自分に書いた方を残す
"""

from __future__ import annotations

from dataclasses import dataclass

from ..links import LinkIndex, Node, parse_wikilink
from ..vault import Page


@dataclass
class Nav:
    prev: Node | None = None
    next: Node | None = None


def next_target(raw: str) -> str:
    """prev／next の値（"[[X]]" か "X"）からリンク先の文字列を取り出す。"""
    s = raw.strip()
    if s.startswith("[[") and s.endswith("]]"):
        return parse_wikilink(s[2:-2]).target
    return s


def compute_nav(pages: list[Page], index: LinkIndex, warnings: list[str]) -> dict[str, Nav]:
    navs: dict[str, Nav] = {p.rel: Nav() for p in pages}
    by_rel = {p.rel: p for p in pages}
    # 明示された辺: (向き, 書いたページ, 相手)
    edges: list[tuple[str, Page, Node]] = []
    for p in sorted(pages, key=lambda x: x.rel):
        for key, raw in (("prev", p.prev_raw), ("next", p.next_raw)):
            if not raw:
                continue
            target = index.resolve(next_target(raw))
            if target is None:
                warnings.append(f"{key} の先が公開ページにありません: {p.rel}.md → {raw}")
                continue
            setattr(navs[p.rel], key, target)
            edges.append((key, p, target))

    # 逆引きで空きを埋める。相手に既に書いてあれば（同じでも違っても）触らない
    for key, p, target in edges:
        back_key = "next" if key == "prev" else "prev"
        back = navs.get(target.rel)
        if back is None:
            continue
        current = getattr(back, back_key)
        if current is None:
            setattr(back, back_key, p)
            continue
        if current.rel == p.rel:
            continue
        if _explicit(by_rel[target.rel], back_key):
            warnings.append(
                f"{p.rel} の {key} は {target.rel} ですが、{target.rel} の {back_key} は "
                f"{current.rel} です（それぞれ書いた方を残します）"
            )
        else:
            warnings.append(
                f"同じページを {key} に指すページが2つあります（{back_key} は先の方を採用）: "
                f"{current.rel} と {p.rel} → {target.rel}"
            )
    return navs


def _explicit(p: Page, key: str) -> bool:
    return bool(p.prev_raw if key == "prev" else p.next_raw)
