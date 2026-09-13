"""python-markdown の組み立て。Obsidian の原稿を壊さず通すための拡張をまとめる。

処理の順番（python-markdown の優先度は大きいほど先）:
  pre:    コード枠の退避（superfences 25）→ 行頭の全角スペースを目印に逃がす（22）→ html ブロック退避（20）
  block:  見出しの regex を「# の後に空白必須」に差し替え（#タグ の行を見出しにしない）／引用を合流させない
  tree:   Callout（25）→ inline（20）→ 見出し id と H1 落とし（15）
  inline: code span（190）→ エスケープ（180）→ 埋め込み（176）→ wikilink（175）
          → 参照・リンク・画像（170〜150）→ 生 HTML 退避（90）→ 裸 URL（88）→ ルビ（85）→ nl2br（5）
          埋め込み検出と wikilink は生 HTML 退避より先なので、タグや属性の中は inside_tag で自分で避ける
  post:   全角スペースの目印を戻す（5）。目印はページごとに原文に無い文字を選ぶ（40 の前処理で決める）
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
from .features.media import MediaIndex, parse_embed
from .links import LinkIndex, Node, parse_wikilink, relative_href, slugify_heading


@dataclass
class RenderContext:
    """ページごとに差し替える情報。Markdown 本体は使い回す。"""

    index: LinkIndex
    warnings: list[str]
    media: MediaIndex | None = None  # 無ければ ![[ ]] は止まる
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
    text = ESCAPE_RE.sub(lambda m: chr(int(m.group(1))), text)
    mark = getattr(md, "biidama_zenkaku_mark", None)
    return text.replace(mark, IDEOGRAPHIC_SPACE) if mark else text


def raw_html_before(md, data: str) -> list[str]:
    """data の中に退避されている生 HTML（inline 段階）を、出現順に元の文字列で返す。"""
    found: list[str] = []
    for m in INLINE_STASH_RE.finditer(data):
        node = md.treeprocessors["inline"].stashed_nodes.get(m.group(1))
        if isinstance(node, str):
            h = HTML_STASH_RE.fullmatch(node)
            if h:
                found.append(str(md.htmlStash.rawHtmlBlocks[int(h.group(1))]))
    return found


OPEN_A_RE = re.compile(r"<a[\s>]", re.I)
CLOSE_A_RE = re.compile(r"</a\s*>", re.I)


def inside_raw_anchor(md, data: str) -> bool:
    """この位置より前で、生 HTML の <a> が開いたまま閉じていないか。"""
    depth = 0
    for raw in raw_html_before(md, data):
        if OPEN_A_RE.match(raw):
            depth += 1
        elif CLOSE_A_RE.match(raw):
            depth = max(0, depth - 1)
    return depth > 0


# ---- inline ---------------------------------------------------------------

TAG_OPEN_RE = re.compile(r"<(?:[A-Za-z/!?])")


def inside_tag(data: str, pos: int) -> bool:
    """pos が生 HTML のタグ（またはコメント）の中か。

    wikilink と埋め込み検出は生 HTML の退避（90）より先に走らせる必要があるので
    （後だと Markdown のリンク・参照・ルビに食われる）、属性の中を自分で避ける。
    先頭から pos まで「タグの外／タグの中／属性値の引用符の中／コメントの中」を追う。
    属性値の中の > はタグの終わりではなく、コメントの終わりは --> だけ。
    （行の途中の生 HTML は python-markdown 自身が属性値の > をタグの終わりと見なすので、
    そこは本体の限界。行頭からのブロック HTML は本物の解析器で読まれるので無事）
    """
    in_tag = False
    in_comment = False
    quote = ""
    i = 0
    while i < pos:
        c = data[i]
        if in_comment:
            if data.startswith("-->", i):
                in_comment = False
                i += 3
                continue
        elif in_tag:
            if quote:
                if c == quote:
                    quote = ""
            elif c in ("'", '"'):
                quote = c
            elif c == ">":
                in_tag = False
        elif c == "<":
            if data.startswith("<!--", i):
                in_comment = True
                i += 4
                continue
            if TAG_OPEN_RE.match(data, i):
                in_tag = True
        i += 1
    return in_tag or in_comment


class EmbedInline(InlineProcessor):
    """![[埋め込み]]。メディアのフォルダの中の画像・音源・動画だけ受ける（ノートの埋め込みは未対応）。

    画像は表示用（縮小版があればそれ）を <img> にし、元画像への <a data-lightbox> で包む。
    組の名前はページ（同じページの画像を前後に送れる）。alt は lightbox の題にもなる。
    """

    def __init__(self, ctx: RenderContext, md):
        super().__init__(r"!\[\[([^\[\]]*)\]\]", md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        if inside_tag(data, m.start(0)):
            return None, None, None
        inner = unstash(self.md, m.group(1))
        page = self.ctx.page
        where = f"{page.rel}.md" if page else "?"
        media = self.ctx.media
        if media is None or media.root is None:
            raise BuildError(f"埋め込み ![[{inner}]] を使うには設定 media.dir（メディアのフォルダ）が要ります: {where}")
        spec = parse_embed(inner)
        f = media.resolve(spec.target)
        if f is None:
            raise BuildError(f"埋め込みの先がメディアのフォルダ（{media.dir}/）にありません: {where} → ![[{inner}]]")
        href = relative_href(page.out_rel, f.rel)
        if f.kind == "image":
            a = etree.Element("a")
            a.set("href", href)
            a.set("data-lightbox", page.rel)
            if spec.alt:
                a.set("data-title", spec.alt)
            img = etree.SubElement(a, "img")
            img.set("src", relative_href(page.out_rel, media.display_rel(f)))
            img.set("alt", spec.alt)
            if spec.width:
                img.set("width", spec.width)
            if spec.height:
                img.set("height", spec.height)
            img.set("loading", "lazy")
            return a, m.start(0), m.end(0)
        if f.kind == "audio":
            el = etree.Element("audio")
            el.set("controls", "controls")
            el.set("preload", "metadata")
            el.set("src", href)
            return el, m.start(0), m.end(0)
        if f.kind == "video":
            el = etree.Element("video")
            el.set("controls", "controls")
            el.set("playsinline", "playsinline")
            el.set("preload", "metadata")
            el.set("src", href)
            return el, m.start(0), m.end(0)
        raise BuildError(f"埋め込み ![[{inner}]] の種類（{f.ext}）は未対応です: {where}")


class WikiLinkInline(InlineProcessor):
    ANCESTOR_EXCLUDES = ("a",)

    def __init__(self, ctx: RenderContext, md):
        super().__init__(r"\[\[([^\[\]]+?)\]\]", md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        if inside_tag(data, m.start(0)):
            return None, None, None
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
        # 退避の目印（\x02 \x03）の手前で止める。生 HTML は先に退避済みなのでタグや属性は含まれない
        super().__init__(r"(?<![\w\"'=/])(https?://[^\s<>\"'）」『』【】\x02\x03]+)", md)

    def handleMatch(self, m, data):
        if inside_raw_anchor(self.md, data[: m.start(1)]):
            return None, None, None  # 生 HTML の <a> の中。二重リンクにしない
        url = m.group(1)
        end = m.end(1)
        while url and url[-1] in self.TRAIL:
            if url[-1] == ")" and url.count("(") >= url.count(")"):
                break  # 対応する開き括弧がある閉じ括弧は URL の一部
            url = url[:-1]
            end -= 1
        el = etree.Element("a")
        el.set("href", url)
        el.text = url
        return el, m.start(1), end


# ---- pre / post -------------------------------------------------------------

IDEOGRAPHIC_SPACE = "　"
# 引用記号とリスト記号の後も対象。4 スペース以上（字下げコード）は対象外
LEADING_ZENKAKU_RE = re.compile(r"^((?:[ \t]{0,3}>)*[ \t]{0,3}(?:(?:[-*+]|\d+[.)])[ \t]{1,3})?)　", re.M)
# 目印は私用領域（U+E000〜U+F8FF）から、原文に現れない文字をページごとに選ぶ。固定の一文字だと原文の同じ文字まで戻してしまう
PRIVATE_USE = range(0xE000, 0xF900)


class PickZenkakuMark(Preprocessor):
    """コード枠の退避より前（原文がそろっている段階）に、原文に無い目印を選んでおく。選べなければ止める。"""

    def run(self, lines):
        source = "\n".join(lines)
        used = {ch for ch in source if 0xE000 <= ord(ch) < 0xF900}
        mark = next((chr(c) for c in PRIVATE_USE if chr(c) not in used), None)
        if mark is None:
            raise BuildError("私用領域の文字が原文に多すぎて、行頭の全角スペースを守る目印を選べません")
        self.md.biidama_zenkaku_mark = mark
        return lines


class KeepLeadingZenkakuSpace(Preprocessor):
    """行頭（引用記号・リスト記号の後も含む）の全角スペースを目印に逃がす。

    python-markdown は段落の先頭を str.lstrip() で削り、Python は全角スペースも空白扱いなので
    小説の字下げが消える。コード枠は先に退避されているので届かない（4スペース字下げも除外）。
    """

    def run(self, lines):
        mark = self.md.biidama_zenkaku_mark
        return LEADING_ZENKAKU_RE.sub(lambda m: m.group(1) + mark, "\n".join(lines)).split("\n")


class RestoreZenkakuSpace(Postprocessor):
    def run(self, text):
        mark = getattr(self.md, "biidama_zenkaku_mark", None)
        return text.replace(mark, IDEOGRAPHIC_SPACE) if mark else text


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
        # Markdown のリンク・参照（170〜150）やルビ（85）に食われる前に認識する。生 HTML の中は inside_tag で避ける
        md.inlinePatterns.register(EmbedInline(self.ctx, md), "biidama_embed", 176)
        md.inlinePatterns.register(WikiLinkInline(self.ctx, md), "biidama_wikilink", 175)
        md.preprocessors.register(PickZenkakuMark(md), "biidama_zenkaku_mark", 40)
        md.inlinePatterns.register(AutoLinkInline(md), "biidama_autolink", 88)
        ruby.register(md)
        md.treeprocessors.register(CalloutTree(md), "biidama_callout", 25)
        md.treeprocessors.register(HeadingTree(self.ctx, md), "biidama_heading", 15)


def make_markdown(ctx: RenderContext) -> markdown.Markdown:
    return markdown.Markdown(
        # sane_lists: 種類の違うリスト（- と 1.）を一つに溶かさない（Obsidian と同じ）
        extensions=["tables", "nl2br", "sane_lists", "pymdownx.highlight", "pymdownx.superfences", BiidamaExtension(ctx)],
        extension_configs={
            # 色付けは Pygments（依存に固定）。色は static/pygments.css（ライト default・ダーク github-dark）。
            # 言語が無い・知らない言語のコード枠は色なしで、枠だけ同じ見た目
            "pymdownx.highlight": {"use_pygments": True, "css_class": "highlight", "guess_lang": False, "auto_title": True},  # auto_title: 言語名を枠の上に
            "pymdownx.superfences": {"css_class": "highlight", "custom_fences": []},
        },
        output_format="html",
    )


def render_body(md: markdown.Markdown, ctx: RenderContext, page: Node, title: str, body: str) -> str:
    ctx.page = page
    ctx.title = title
    ctx.seen_ids = set()
    md.reset()
    html = md.convert(body)
    # 言語の無いコード枠には札を付けない（auto_title は "Text Only" を付けてしまう）
    return html.replace('<div class="highlight"><span class="filename">Text Only</span>', '<div class="highlight">')
