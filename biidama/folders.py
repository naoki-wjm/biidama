"""フォルダ索引の自動生成。

規則: 子孫に公開ページを持つフォルダは索引を持つ。ただし同名ノート（雑録.md）か
中の index.md が公開されていればそちらがページなので生成しない。
中身は直下のページ（created 降順）と、下位フォルダ1階層ぶんの見出し＋直下ページ。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .links import Node
from .vault import Page


@dataclass
class FolderIndex:
    rel: str  # フォルダの相対パス（ルートは ""）
    kind: str = "folder"
    created: dt.date | None = None
    pages: list[Page] = field(default_factory=list)  # 直下の公開ページ
    subfolders: list["FolderSection"] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.rel.rsplit("/", 1)[-1] if self.rel else "index"

    @property
    def out_rel(self) -> str:
        return (self.rel + ".html") if self.rel else "index.html"


@dataclass
class FolderSection:
    rel: str
    node: Node | None  # 下位フォルダのページ（ハブ note か索引）。無ければ None
    pages: list[Page]

    @property
    def title(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


def _sort_key(p: Page):
    return (p.created or dt.date.min, p.stem)


def sort_newest(pages: list[Page]) -> list[Page]:
    return sorted(pages, key=_sort_key, reverse=True)


def parent_folders(rel: str) -> list[str]:
    """"a/b/c" → ["", "a", "a/b"]"""
    parts = rel.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(len(parts) + 1)]


def make_folder_indexes(pages: list[Page]) -> tuple[list[FolderIndex], dict[str, Node]]:
    """索引を作り、(索引の一覧, フォルダ→そのページ の対応表) を返す。"""
    by_rel = {p.rel: p for p in pages}
    direct: dict[str, list[Page]] = {}
    all_folders: set[str] = set()
    for p in pages:
        direct.setdefault(p.folder, []).append(p)
        all_folders.update(parent_folders(p.rel))

    def newest(folder: str) -> dt.date | None:
        prefix = folder + "/" if folder else ""
        dates = [p.created for p in pages if p.rel.startswith(prefix) and p.created]
        return max(dates) if dates else None

    # フォルダの顔になるページ: 同名ノート > 中の index > 自動索引
    folder_node: dict[str, Node] = {}
    indexes: list[FolderIndex] = []
    for f in sorted(all_folders):
        hub = by_rel.get(f) if f else by_rel.get("index")
        if hub is None and f:
            hub = by_rel.get(f + "/index")
        if hub is not None:
            folder_node[f] = hub
        else:
            fi = FolderIndex(rel=f, created=newest(f))
            folder_node[f] = fi
            indexes.append(fi)

    for fi in indexes:
        fi.pages = sort_newest([p for p in direct.get(fi.rel, []) if p.rel != fi.rel])
        prefix = fi.rel + "/" if fi.rel else ""
        subs = sorted(
            {f for f in all_folders if f.startswith(prefix) and f != fi.rel and "/" not in f[len(prefix):]},
            key=lambda f: (newest(f) or dt.date.min, f),
            reverse=True,
        )
        for sub in subs:
            node = folder_node.get(sub)
            sub_pages = [p for p in direct.get(sub, []) if node is None or p.rel != node.rel]
            fi.subfolders.append(FolderSection(rel=sub, node=node, pages=sort_newest(sub_pages)))
    return indexes, folder_node
