"""wikilink の解決と、出力パス・href の計算。"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from . import BuildError


class Node(Protocol):
    """リンク先になれるもの（ページとフォルダ索引）。"""

    rel: str
    kind: str

    @property
    def out_rel(self) -> str: ...

    @property
    def title(self) -> str: ...


@dataclass(frozen=True)
class WikiLink:
    target: str  # パスまたは basename（空なら同一ページ）
    heading: str  # "#見出し" の見出し部分（無ければ ""）
    alias: str  # "|表示" の表示部分（無ければ ""）

    @property
    def display(self) -> str:
        if self.alias:
            return self.alias
        return self.target + ("#" + self.heading if self.heading else "")


def parse_wikilink(inner: str) -> WikiLink:
    """[[ ]] の中身を (target, heading, alias) に分ける。"""
    body, _, alias = inner.partition("|")
    target, _, heading = body.partition("#")
    return WikiLink(target.strip(), heading.strip(), alias.strip())


def slugify_heading(text: str) -> str:
    """見出し文字列をそのまま id にする（空白だけ - に）。"""
    return re.sub(r"\s+", "-", text.strip())


def encode_href(path: str) -> str:
    """href 用に最低限だけ符号化する（日本語はそのまま、空白と記号だけ）。"""
    return (
        path.replace("%", "%25")
        .replace(" ", "%20")
        .replace("#", "%23")
        .replace("?", "%3F")
        .replace('"', "%22")
    )


def relative_href(from_out_rel: str, to_out_rel: str, anchor: str = "") -> str:
    start = posixpath.dirname(from_out_rel)
    rel = posixpath.relpath(to_out_rel, start) if start else to_out_rel
    href = encode_href(rel)
    if anchor:
        href += "#" + encode_href(slugify_heading(anchor))
    return href


def root_prefix(out_rel: str) -> str:
    """そのページからサイトルートへ戻る相対プレフィックス（"", "../", ...）。"""
    return "../" * out_rel.count("/")


class LinkIndex:
    """公開ページとフォルダ索引の一覧表。候補は公開されるものだけ。"""

    def __init__(self, nodes: list[Node]):
        self.by_path: dict[str, Node] = {}
        self.by_base: dict[str, list[Node]] = defaultdict(list)
        for n in nodes:
            self.by_path[n.rel] = n
            self.by_base[n.rel.rsplit("/", 1)[-1]].append(n)
        # フォルダの中の index は、そのフォルダ名でも引けるようにする（LLM wiki/index → LLM wiki）
        for n in nodes:
            if n.kind == "page" and n.rel.endswith("/index"):
                folder = n.rel[: -len("/index")]
                self.by_path.setdefault(folder, n)

    def resolve(self, target: str) -> Node | None:
        """明示パスならパスで、無ければ basename で。複数一致は止める。"""
        t = target.strip().strip("/")
        if t.endswith(".md"):
            t = t[:-3]
        if not t:
            return None
        if "/" in t:
            return self.by_path.get(t)
        hit = self.by_path.get(t)
        if hit is not None:
            return hit
        candidates = self.by_base.get(t, [])
        if len(candidates) > 1:
            raise BuildError(
                f"[[{target}]] の候補が複数あります（パスで書いてください）: "
                + ", ".join(sorted(c.rel for c in candidates))
            )
        return candidates[0] if candidates else None
