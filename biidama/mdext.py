"""python-markdown の組み立て。Obsidian の原稿を壊さず通すための拡張をまとめる。

処理の順番（python-markdown の優先度は大きいほど先）:
  pre:    行頭の全角スペースを実体参照に逃がす（22。コード退避 25 の後）→ post で戻す
  block:  見出しの regex を「# の後に空白必須」に差し替え（#タグ の行を見出しにしない）
  tree:   Callout（25）→ inline（20）→ 見出し id と H1 落とし（15）
  inline: 埋め込み検出（176）→ wikilink（175）→ code span（190 で退避済み）
          → 生 HTML 退避（90）→ ルビ（85）→ 裸 URL（88）→ nl2br（5）
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as etree
from dataclasses import dataclass, field

import markdown
from markdown.blockprocessors import BlockQuoteProcessor
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.postprocessors import Postprocessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor

from . import BuildError
from .features import ruby
from .links import LinkIndex, Node, parse_wikilink, relative_href, slugify_heading


@dataclass
class RenderContext:
    """ページごとに差し替える情報。Markdown 本体は使い回す。"""

    index: LinkIndex
    warnings: list[str]
    page: Node | None = None
    title: str = ""
    seen_ids: set[str] = field(default_factory=set)


INLINE_STASH_RE = re.compile(r"\x02klzzwxh:(\d+)\x03")  # inline 処理中の退避（\| や code span）
HTML_STASH_RE = re.compile(r"\x02wzxhzdk:(\d+)\x03")  # 生 HTML の退避
ESCAPE_RE = re.compile(r"\x02(\d+)\x03")  # \| などのエスケープ文字
TAG_RE = re.compile(r"<[^>]+>")


def unstash(md, text: str) -> str:
    """退避の目印を元の文字に戻す。タグは落として中の文字だけにする。"""

    def inline_node(m):
        node = md.treeprocessors["inline"].stashed_nodes.get(m.group(1))
        if node is None:
            return ""
        return node if isinstance(node, str) else "".join(node.itertext())

    text = INLINE_STASH_RE.sub(inline_node, text)
    text = HTML_STASH_RE.sub(lambda m: TAG_RE.sub("", str(md.htmlStash.rawHtmlBlocks[int(m.group(1))])), text)
    return ESCAPE_RE.sub(lambda m: chr(int(m.group(1))), text)


# ---- inline ---------------------------------------------------------------

class EmbedGuard(InlineProcessor):
    """![[埋め込み]] は未対応。黙って崩さず止める。"""

    def __init__(self, ctx: RenderContext, md):
        super().__init__(r"!\[\[([^\[\]]*)\]\]", md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        raise BuildError(f"埋め込み ![[{m.group(1)}]] は未対応です: {self.ctx.page.rel}.md")


class WikiLinkInline(InlineProcessor):
    ANCESTOR_EXCLUDES = ("a",)

    def __init__(self, ctx: RenderContext, md):
        super().__init__(r"\[\[([^\[\]]+?)\]\]", md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        inner = unstash(self.md, m.group(1))
        link = parse_wikilink(inner)
        page = self.ctx.page
        where = f"{page.rel}.md" if page else "?"
        if link.heading.startswith("^"):
            raise BuildError(f"ブロック参照 [[{inner}]] は未対応です: {where}")
        if not link.target:
            raise BuildError(f"同一ページ内リンク [[{inner}]] は未対応です: {where}")
        target = self.ctx.index.resolve(link.target)
        if target is None:
            self.ctx.warnings.append(f"リンク先が公開ページにありません: {where} → [[{inner}]]")
            el = etree.Element("span")
            el.set("class", "unresolved-link")
            el.text = link.display
            return el, m.start(0), m.end(0)
        el = etree.Element("a")
        el.set("href", relative_href(page.out_rel, target.out_rel, link.heading))
        el.set("class", "internal")
        el.text = link.display
        return el, m.start(0), m.end(0)


class AutoLinkInline(InlineProcessor):
    """裸の URL をリンクにする。"""

    ANCESTOR_EXCLUDES = ("a",)
    TRAIL = ".,;:!?)]}。、」』】）"

    def __init__(self, md):
        super().__init__(r"(?<![\w\"'=/(])(https?://[^\s<>\"'）」『』【】]+)", md)

    def handleMatch(self, m, data):
        url = m.group(1)
        end = m.end(1)
        while url and url[-1] in self.TRAIL:
            url = url[:-1]
            end -= 1
        el = etree.Element("a")
        el.set("href", url)
        el.text = url
        return el, m.start(1), end


# ---- pre / post -------------------------------------------------------------

IDEOGRAPHIC_SPACE = "　"
LEADING_ZENKAKU_RE = re.compile(r"^((?:[ \t]{0,3}>)*[ \t]{0,3})　", re.M)
ZENKAKU_MARK = "&#x3000;"


class KeepLeadingZenkakuSpace(Preprocessor):
    """行頭（引用記号の後も含む）の全角スペースを実体参照に逃がす。

    python-markdown は段落の先頭を str.lstrip() で削り、Python は全角スペースも空白扱いなので
    小説の字下げが消える。コード枠は先に退避されているので届かない（4スペース字下げも除外）。
    """

    def run(self, lines):
        return LEADING_ZENKAKU_RE.sub(lambda m: m.group(1) + ZENKAKU_MARK, "\n".join(lines)).split("\n")


class RestoreZenkakuSpace(Postprocessor):
    def run(self, text):
        return text.replace(ZENKAKU_MARK, IDEOGRAPHIC_SPACE)


# ---- tree -----------------------------------------------------------------

class CalloutTree(Treeprocessor):
    """Obsidian の Callout。blockquote の先頭行 [!type] を見て変換する。

    折りたたみ（[!type]- ／ [!type]+）は <details><summary>、通常は blockquote に class。
    inline 処理より前に走るので、題や本文のルビ・強調は後から普通に処理される。
    """

    MARK = re.compile(r"^\[!([A-Za-z0-9_-]+)\]([+-]?)[ \t]*(.*)$")

    def run(self, root):
        for parent in list(root.iter()):
            for bq in list(parent):
                if bq.tag != "blockquote" or len(bq) == 0:
                    continue
                first = bq[0]
                if first.tag != "p" or not first.text:
                    continue
                head, _, rest = first.text.lstrip().partition("\n")
                m = self.MARK.match(head.strip())
                if not m:
                    continue
                kind = m.group(1).lower()
                fold = m.group(2)
                title = m.group(3).strip() or m.group(1).capitalize()
                first.text = rest
                if not rest and len(first) == 0 and not (first.tail or "").strip():
                    bq.remove(first)
                bq.set("class", f"callout callout-{kind}")
                if fold:
                    bq.tag = "details"
                    if fold == "+":
                        bq.set("open", "open")
                    summary = etree.Element("summary")
                    summary.text = title
                    bq.insert(0, summary)
                else:
                    t = etree.Element("p")
                    t.set("class", "callout-title")
                    t.text = title
                    bq.insert(0, t)


class HeadingTree(Treeprocessor):
    """本文先頭の H1 がタイトルと同文なら落とし、見出しに id を付ける。

    inline 処理の後に走るので、見出しの中の wikilink・強調・ルビは解決済み。
    id にはルビの読み（rt）や括弧（rp）を含めず、退避された code span は中の文字だけ使う。
    """

    def __init__(self, ctx: RenderContext, md):
        super().__init__(md)
        self.ctx = ctx

    def text_of(self, el) -> str:
        parts: list[str] = []

        def walk(e):
            if e.tag in ("rt", "rp"):
                return
            if e.text:
                parts.append(e.text)
            for child in e:
                walk(child)
                if child.tail:
                    parts.append(child.tail)

        walk(el)
        return unstash(self.md, "".join(parts))

    def run(self, root):
        if len(root) and root[0].tag == "h1":
            if self.text_of(root[0]).strip() == self.ctx.title.strip():
                root.remove(root[0])
        seen = self.ctx.seen_ids
        for el in root.iter():
            if el.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                base = slugify_heading(self.text_of(el)) or "section"
                slug, n = base, 0
                while slug in seen:
                    n += 1
                    slug = f"{base}-{n}"
                seen.add(slug)
                el.set("id", slug)


# ---- extension -------------------------------------------------------------

HASH_HEADER_RE = re.compile(
    r"(?:^|\n)(?P<level>#{1,6})[ \t]+(?P<header>(?:\\.|[^\\])*?)#*(?:\n|$)"
)


class SeparateBlockQuotes(BlockQuoteProcessor):
    """空行で区切った引用は別の引用にする（python-markdown は直前の引用に合流させてしまう。
    Obsidian／CommonMark では別物なので、Callout が二つ並ぶと一つに溶ける事故を防ぐ）。"""

    def run(self, parent, blocks):
        block = blocks.pop(0)
        m = self.RE.search(block)
        if m:
            before = block[: m.start()]
            self.parser.parseBlocks(parent, [before])
            block = "\n".join(self.clean(line) for line in block[m.start():].split("\n"))
        quote = etree.SubElement(parent, "blockquote")
        self.parser.state.set("blockquote")
        self.parser.parseChunk(quote, block)
        self.parser.state.reset()


class BiidamaExtension(Extension):
    def __init__(self, ctx: RenderContext):
        super().__init__()
        self.ctx = ctx

    def extendMarkdown(self, md):
        # #タグ の行を見出しにしない（CommonMark と同じく # の後に空白を要求）
        md.parser.blockprocessors["hashheader"].RE = HASH_HEADER_RE
        md.parser.blockprocessors.register(SeparateBlockQuotes(md.parser), "quote", 20)
        # superfences のコード退避（25）の後、html ブロック退避（20）の前
        md.preprocessors.register(KeepLeadingZenkakuSpace(md), "biidama_zenkaku", 22)
        md.postprocessors.register(RestoreZenkakuSpace(md), "biidama_zenkaku_restore", 5)
        md.inlinePatterns.register(EmbedGuard(self.ctx, md), "biidama_embed_guard", 176)
        md.inlinePatterns.register(WikiLinkInline(self.ctx, md), "biidama_wikilink", 175)
        md.inlinePatterns.register(AutoLinkInline(md), "biidama_autolink", 88)
        ruby.register(md)
        md.treeprocessors.register(CalloutTree(md), "biidama_callout", 25)
        md.treeprocessors.register(HeadingTree(self.ctx, md), "biidama_heading", 15)


def make_markdown(ctx: RenderContext) -> markdown.Markdown:
    return markdown.Markdown(
        # sane_lists: 種類の違うリスト（- と 1.）を一つに溶かさない（Obsidian と同じ）
        extensions=["tables", "nl2br", "sane_lists", "pymdownx.highlight", "pymdownx.superfences", BiidamaExtension(ctx)],
        extension_configs={
            # 色付けはしない（pytest 経由で Pygments が入っていても出力を変えない）。
            # 言語名は class="language-xxx" に残すので、後から足せる
            "pymdownx.highlight": {"use_pygments": False, "css_class": ""},
            "pymdownx.superfences": {"css_class": "", "custom_fences": []},
        },
        output_format="html",
    )


def render_body(md: markdown.Markdown, ctx: RenderContext, page: Node, title: str, body: str) -> str:
    ctx.page = page
    ctx.title = title
    ctx.seen_ids = set()
    md.reset()
    return md.convert(body)
