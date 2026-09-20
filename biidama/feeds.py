"""検索エンジンと購読者への地図: sitemap.xml・rss.xml、それと「どこかのページへ」の行き先一覧 random.json。

どれも build の中で閉じる（届いたものを見る手入れが無い）。sitemap と RSS は絶対 URL が要るので site.url がある時だけ。
RSS の中身は「最近の更新」と同じ並び・同じ件数（更新日は台帳から。時刻は持たないので UTC の 0 時に揃える）。
"""

from __future__ import annotations

import datetime as dt
import json
from email.utils import format_datetime
from xml.sax.saxutils import escape

from .links import Node, encode_href
from .vault import Page

SITEMAP_NAME = "sitemap.xml"
RSS_NAME = "rss.xml"
RANDOM_NAME = "random.json"


def absolute_url(site_url: str, out_rel: str) -> str:
    return site_url + encode_href(out_rel)


def in_folders(rel: str, folders: list[str]) -> bool:
    """ページの rel が、指名されたフォルダのどれかの下にあるか（フォルダ自身の顔ページ `<folder>/index` も含む）。"""
    return any(rel.startswith(f + "/") for f in folders)


def make_sitemap(site_url: str, nodes: list[Node], updated: dict[str, dt.date | None]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for n in nodes:
        lines.append("<url>")
        lines.append(f"<loc>{escape(absolute_url(site_url, n.out_rel))}</loc>")
        d = updated.get(n.rel) if n.kind == "page" else None
        if d:
            lines.append(f"<lastmod>{d.isoformat()}</lastmod>")
        lines.append("</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def rfc822(d: dt.date) -> str:
    return format_datetime(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc))


def make_rss(site_name: str, site_url: str, pages: list[Page], dates: dict[str, dt.date], descriptions: dict[str, str]) -> str:
    """RSS 2.0。pages は更新日の新しい順（「最近の更新」と同じ列）。"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(site_name)}</title>",
        f"<link>{escape(site_url)}</link>",
        f"<description>{escape(site_name)} の最近の更新</description>",
        f'<atom:link href="{escape(absolute_url(site_url, RSS_NAME))}" rel="self" type="application/rss+xml"/>',
    ]
    if pages:
        lines.append(f"<lastBuildDate>{rfc822(dates[pages[0].rel])}</lastBuildDate>")
    for p in pages:
        url = absolute_url(site_url, p.out_rel)
        lines.append("<item>")
        lines.append(f"<title>{escape(p.title)}</title>")
        lines.append(f"<link>{escape(url)}</link>")
        lines.append(f'<guid isPermaLink="true">{escape(url)}</guid>')
        lines.append(f"<pubDate>{rfc822(dates[p.rel])}</pubDate>")
        desc = descriptions.get(p.rel, "")
        if desc:
            lines.append(f"<description>{escape(desc)}</description>")
        lines.append("</item>")
    lines += ["</channel>", "</rss>"]
    return "\n".join(lines) + "\n"


def make_random(pages: list[Page], folders: list[str]) -> str | None:
    """「どこかのページへ」の行き先（サイトルートからの相対パスの列）。指名フォルダに一枚も無ければ None。"""
    chosen = [encode_href(p.out_rel) for p in pages if in_folders(p.rel, folders)]
    if not chosen:
        return None
    return json.dumps(chosen, ensure_ascii=False) + "\n"
