"""build: 保管庫 → out/ の静的 HTML と、publish が後で読む manifest。"""

from __future__ import annotations

import datetime as dt
import hashlib
import html as html_mod
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import BuildError, __version__
from .config import Config
from .feeds import RANDOM_NAME, RSS_NAME, SITEMAP_NAME, in_folders, make_random, make_rss, make_sitemap
from .features.media import MediaIndex
from .features.series import compute_nav
from .folders import FolderIndex, make_folder_indexes
from .links import LinkIndex, Node, relative_href, root_prefix
from .mdext import RenderContext, make_markdown, render_body
from .recent import HOME_OUT, RECENT_NAME, RecentList, make_recent
from .tags import TAG_DIR, TagIndex, TagList, make_tag_indexes
from .vault import Page, scan

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR.parent / "templates"
STATIC_DIR = PACKAGE_DIR.parent / "static"


@dataclass
class BuildResult:
    pages: list[Page]
    folders: list[FolderIndex]
    tags: list[TagIndex] = field(default_factory=list)
    recent: RecentList | None = None
    warnings: list[str] = field(default_factory=list)
    manifest_path: Path | None = None
    updated: dict[str, dt.date | None] = field(default_factory=dict)  # rel → 表示した更新日（publish が台帳に写す）


def make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


RESERVED_PREFIXES = ("static/", TAG_DIR + "/")  # 出力側で使う名前。原稿のフォルダ名と衝突させない
RESERVED_FILES = (TAG_DIR + ".html", RECENT_NAME + ".html")


def check_out_collisions(nodes: list[Node], media_dir: str = "") -> None:
    """原稿由来のページ・フォルダ索引が、互いに・予約名と衝突しないか（出力を消す前に止める）。"""
    seen: dict[str, str] = {}
    prefixes = RESERVED_PREFIXES + ((media_dir.lower() + "/",) if media_dir else ())
    files = RESERVED_FILES + ((media_dir.lower() + ".html",) if media_dir else ())  # メディアと同名のノートも予約
    for n in nodes:
        key = n.out_rel.lower()  # Windows と多くのホスティングは大文字小文字を区別しない
        if key in seen:
            raise BuildError(f"2つのページが同じ出力先になります: {seen[key]} と {n.rel}")
        if key.startswith(prefixes) or key in files:
            raise BuildError(
                f"フォルダ名・ノート名 static・{TAG_DIR}・{RECENT_NAME}"
                + (f"・{media_dir}（メディアのフォルダ）" if media_dir else "")
                + f" は出力側で使うので原稿には使えません: {n.rel}"
            )
        seen[key] = n.rel


def check_outputs(outputs: list[tuple[str, str]], out: Path) -> None:
    """生成物すべて（タグページ・一覧も含む）の出力先が、互いに重ならず、出力フォルダの中に収まるか。
    タグ名は原稿の文字列がそのままパスになるので、ここで最後に確かめる。"""
    seen: dict[str, str] = {}
    root = out.resolve()
    for out_rel, _ in outputs:
        key = out_rel.lower()
        if key in seen:
            raise BuildError(f"2つの生成物が同じ出力先になります（大文字小文字の違いも同じ扱い）: {seen[key]} と {out_rel}")
        seen[key] = out_rel
        target = (root / out_rel).resolve()
        if not target.is_relative_to(root):
            raise BuildError(f"出力先が出力フォルダの外を指しています: {out_rel}")


def breadcrumbs(node: Node, folder_node: dict[str, Node]) -> list[dict]:
    """親フォルダの列。フォルダに顔ページがあればリンク、無ければ文字だけ。"""
    parts = node.rel.split("/")[:-1] if node.rel else []
    crumbs = []
    for i, name in enumerate(parts):
        f = "/".join(parts[: i + 1])
        target = folder_node.get(f)
        href = relative_href(node.out_rel, target.out_rel) if target and target.rel != node.rel else None
        crumbs.append({"title": name, "href": href})
    return crumbs


def check_out_dir(cfg: Config) -> None:
    """出力先は build のたびに消して作り直すので、消してはいけない場所を指していたら止める。"""
    out = cfg.out.resolve()
    vault = cfg.vault.resolve()
    forbidden = {vault, Path.home().resolve(), Path(out.anchor)}
    if out in forbidden:
        raise BuildError(f"出力先に保管庫・ホーム・ドライブの根は指定できません: {out}")
    if vault == out or vault.is_relative_to(out):
        raise BuildError(f"出力先が保管庫を含んでいます（消えます）: {out}")
    if out.is_relative_to(vault):
        raise BuildError(f"出力先が保管庫の中です: {out}")
    state = cfg.state_dir.resolve()
    if state == out or state.is_relative_to(out):
        raise BuildError(f"台帳の置き場（state_dir）が出力先の中にあります。build のたびに消えます: {state}")
    if out.exists() and not out.is_dir():
        raise BuildError(f"出力先がフォルダではありません: {out}")
    if out.exists() and any(out.iterdir()) and not (out / ".biidama-out").exists():
        raise BuildError(
            f"出力先に biidama 以外のものが入っています。空にするか別の場所を指定してください: {out}"
        )


def static_versions() -> dict[str, str]:
    """static/ の各ファイル → 中身のハッシュ（先頭 8 桁）。URL に ?v= で付けて、変わった時だけ読み直させる。"""
    versions: dict[str, str] = {}
    if STATIC_DIR.is_dir():
        for p in sorted(STATIC_DIR.rglob("*")):
            if p.is_file():
                versions[p.relative_to(STATIC_DIR).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
    return versions


_TAG_RE = re.compile(r"<[^>]+>")
_FOOTNOTE_RE = re.compile(r'<sup id="fnref.*?</sup>|<div class="footnote">.*', re.S)  # 本文中の注の番号と、末尾の注の一覧
_WS_RE = re.compile(r"\s+")


def summarize(body_html: str, limit: int = 120) -> str:
    """OGP の description 用。本文 HTML からタグを剥がして先頭だけ（frontmatter に description があればそちらを使う）。
    脚注の番号と一覧は説明文に混ぜない。"""
    text = _WS_RE.sub(" ", html_mod.unescape(_TAG_RE.sub("", _FOOTNOTE_RE.sub("", body_html)))).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def load_ledger(cfg: Config) -> dict:
    """公開台帳（publish が書く。src → {"hash", "updated"}）。無ければ空。"""
    path = cfg.state_dir / "ledger.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BuildError(f"公開台帳が読めません: {path}: {e}") from e
    return data.get("pages", {}) if isinstance(data, dict) else {}


def updated_date(page: Page, ledger: dict, today: dt.date) -> dt.date | None:
    """更新日。台帳と本文ハッシュが一致すれば台帳の日付、違えば今日、台帳に無ければ modified（無ければ created）。"""
    entry = ledger.get(page.rel + ".md")
    if entry:
        if entry.get("hash") == page.body_hash():
            d = dt.date.fromisoformat(entry["updated"]) if entry.get("updated") else None
            return d or page.modified or page.created
        return today
    return page.modified or page.created


def render_file(src: Path, warnings: list[str] | None = None) -> str:
    """一枚の Markdown を公開判定なしで本文 HTML にする（試験用。CLI からは使わない）。

    リンクの解決先は無いので wikilink はすべて未解決の注意になる。
    """
    src = Path(src)
    text = src.read_text(encoding="utf-8")
    from .vault import split_frontmatter

    fm, body, broken = split_frontmatter(text)
    if broken:
        raise BuildError(f"frontmatter が読めません: {src}")
    page = Page(src=src, rel=src.stem, frontmatter=fm, body=body)
    ctx = RenderContext(index=LinkIndex([]), warnings=warnings if warnings is not None else [])
    return render_body(make_markdown(ctx), ctx, page, page.title, page.body)


def build(cfg: Config, *, log=print) -> BuildResult:
    warnings: list[str] = []
    pages = scan(cfg, warnings)
    if not pages:
        raise BuildError("公開ページ（publish: true）が一枚もありません")

    folders, folder_node = make_folder_indexes(pages)
    tag_indexes, tag_list = make_tag_indexes(pages)
    nodes: list[Node] = [*pages, *folders]
    check_out_collisions(nodes, cfg.media.dir)
    index = LinkIndex(nodes)  # タグページは wikilink の解決先にしない
    media = MediaIndex(cfg, warnings)  # ![[ ]] の解決先。media.dir が空なら埋め込みは止まる
    tag_node: dict[str, TagIndex] = {t.tag: t for t in tag_indexes}
    navs = compute_nav(pages, index, warnings)

    env = make_env()
    page_tpl = env.get_template("page.html")
    folder_tpl = env.get_template("folder.html")
    tag_tpl = env.get_template("tag.html")
    tags_tpl = env.get_template("tags.html")
    recent_tpl = env.get_template("recent.html")
    site_url = cfg.site.url.rstrip("/") + "/" if cfg.site.url else ""
    assets = static_versions()
    icon = cfg.site.icon
    if icon and not (icon.startswith("static/") and icon[len("static/"):] in assets):
        warnings.append(f"site.icon の画像が static/ にありません（アイコン無しで進めます）: {icon}")
        icon = ""
    site = {
        "name": cfg.site.name,
        "url": site_url,
        "icon": icon,  # ファビコン・OGP 画像・ヘッダーの印
        "icon_v": assets.get(icon[len("static/"):], "") if icon else "",
        "theme_color": cfg.site.theme_color,
        "head_extra": cfg.site.head_extra,
        "has_tags": tag_list is not None,
    }

    ctx = RenderContext(index=index, warnings=warnings, media=media)
    md = make_markdown(ctx)
    ledger = load_ledger(cfg)
    today = dt.date.today()
    updated: dict[str, dt.date | None] = {p.rel: updated_date(p, ledger, today) for p in pages}
    # 最近の更新: 一覧ページ（site.recent 件）とトップの末尾（site.recent_home 件）。どちらも 0 なら無し
    recent = make_recent(pages, updated, max(cfg.site.recent, cfg.site.recent_home))
    # 一覧ページは site.recent 件に切り詰める（トップ側の件数が一覧に漏れないように）
    recent_page = RecentList(pages=recent.head(cfg.site.recent), dates=recent.dates) if recent and cfg.site.recent > 0 else None
    site["has_recent"] = recent_page is not None
    site["has_rss"] = recent_page is not None and bool(site_url)  # RSS は「最近の更新」の列を絶対 URL で流す
    random_json = make_random(pages, cfg.site.random)
    site["has_random"] = random_json is not None

    check_out_dir(cfg)

    def link(from_node: Node, to: Node | None) -> str | None:
        return relative_href(from_node.out_rel, to.out_rel) if to else None

    def common(node: Node, description: str = "", og_type: str = "website") -> dict:
        """どの雛型にも渡すもの（OGP の材料を含む）。"""
        return {
            "site": site,
            "assets": assets,
            "root": root_prefix(node.out_rel),
            "page": node,
            "page_url": site_url + node.out_rel if site_url else "",
            "description": description,
            "og_type": og_type,
        }

    def tag_links(node: Node, names: list[str]) -> list[dict]:
        return [{"name": t, "href": link(node, tag_node.get(t))} for t in names]

    def recent_items(node: Node, ps: list[Page]) -> list[dict]:
        return [{"title": p.title, "href": link(node, p), "updated": recent.dates[p.rel].isoformat()} for p in ps]

    def home_recent(node: Node) -> dict:
        """トップページだけに渡す「最近の更新」の材料。他のページには空。"""
        if node.out_rel != HOME_OUT or recent is None:
            return {"recent": [], "recent_more": None}
        return {"recent": recent_items(node, recent.head(cfg.site.recent_home)), "recent_more": link(node, recent_page)}

    def backlink_items(node: Page) -> list[dict]:
        """「このページに触れているページ」。site.backlinks のフォルダにあるページだけ、題の順で。
        パンくずに出る親フォルダの顔ページ（目次からのリンク）は数えない（同じ行き先を二度出さない）。"""
        if not in_folders(node.rel, cfg.site.backlinks):
            return []
        parts = node.rel.split("/")[:-1]
        parents = {n.rel for i in range(len(parts)) if (n := folder_node.get("/".join(parts[: i + 1])))}
        sources = sorted((page_by_rel[r] for r in ctx.backlinks.get(node.rel, ()) if r not in parents), key=lambda s: (s.title, s.rel))
        return [{"title": s.title, "href": link(node, s)} for s in sources]

    # 失敗しうる変換をすべて先に済ませ、成功した時だけ旧出力を消して書き出す
    # 本文は先に全部変換する（逆引きは全ページの wikilink を見てから決まる）
    page_by_rel = {p.rel: p for p in pages}
    bodies = {p.rel: render_body(md, ctx, p, p.title, p.body) for p in pages}
    descriptions = {p.rel: str(p.frontmatter.get("description") or "").strip() or summarize(bodies[p.rel]) for p in pages}
    outputs: list[tuple[str, str]] = []
    for p in pages:
        nav = navs[p.rel]
        html = page_tpl.render(
            **common(p, descriptions[p.rel], "article"),
            body=bodies[p.rel],
            backlinks=backlink_items(p),
            created=p.created.isoformat() if p.created else "",
            updated=updated[p.rel].isoformat() if updated[p.rel] and updated[p.rel] != p.created else "",
            tags=tag_links(p, p.tags),
            crumbs=breadcrumbs(p, folder_node),
            prev={"title": nav.prev.title, "href": link(p, nav.prev)} if nav.prev else None,
            next={"title": nav.next.title, "href": link(p, nav.next)} if nav.next else None,
            **home_recent(p),
        )
        outputs.append((p.out_rel, html))

    for f in folders:
        html = folder_tpl.render(
            **common(f, f"{f.title} のページ一覧"),
            crumbs=breadcrumbs(f, folder_node),
            pages=[{"title": p.title, "href": link(f, p), "created": p.created} for p in f.pages],
            sections=[
                {
                    "title": s.title,
                    "href": link(f, s.node) if s.node else None,
                    "pages": [{"title": p.title, "href": link(f, p), "created": p.created} for p in s.pages],
                }
                for s in f.subfolders
            ],
            **home_recent(f),
        )
        outputs.append((f.out_rel, html))

    for t in tag_indexes:
        html = tag_tpl.render(
            **common(t, f"#{t.tag} のページ {len(t.pages)} 枚"),
            crumbs=[{"title": tag_list.title, "href": link(t, tag_list)}],
            pages=[{"title": p.title, "href": link(t, p), "created": p.created} for p in t.pages],
        )
        outputs.append((t.out_rel, html))
    if tag_list is not None:
        html = tags_tpl.render(
            **common(tag_list, f"タグ {len(tag_indexes)} 種"),
            crumbs=[],
            tags=[{"name": t.tag, "href": link(tag_list, t), "count": len(t.pages)} for t in tag_indexes],
        )
        outputs.append((tag_list.out_rel, html))
    if recent_page is not None:
        html = recent_tpl.render(
            **common(recent_page, f"更新日の新しい順に {len(recent_page.pages)} ページ"),
            crumbs=[],
            pages=recent_items(recent_page, recent_page.pages),
        )
        outputs.append((recent_page.out_rel, html))
    if site_url:
        generated: list[Node] = [*tag_indexes, *([tag_list] if tag_list else []), *([recent_page] if recent_page else [])]
        outputs.append((SITEMAP_NAME, make_sitemap(site_url, [*nodes, *generated], updated)))
    if site["has_rss"]:
        outputs.append((RSS_NAME, make_rss(cfg.site.name, site_url, recent_page.pages, recent_page.dates, descriptions)))
    if random_json is not None:
        outputs.append((RANDOM_NAME, random_json))

    # 失敗しうるものはここまでに全部済ませる: 生成物の衝突・範囲の検査、縮小版の生成（壊れた画像はここで止まる）
    check_outputs(outputs, cfg.out)
    media.prepare_thumbnails(log=log)

    try:
        if cfg.out.exists():
            shutil.rmtree(cfg.out)
        cfg.out.mkdir(parents=True)
    except OSError as e:
        raise BuildError(f"出力先を作り直せません（別のプログラムが開いていませんか）: {cfg.out}: {e}") from e
    (cfg.out / ".biidama-out").write_text("biidama build の出力先の目印。次の build でこのフォルダは消して作り直されます。\n", encoding="utf-8")
    for out_rel, html in outputs:
        write_text(cfg.out / out_rel, html)
    if STATIC_DIR.is_dir():
        shutil.copytree(STATIC_DIR, cfg.out / "static")
    media_count = media.copy_to(cfg.out)
    media.write_thumbnails(cfg.out)

    manifest = {
        "biidama": __version__,
        "built": dt.datetime.now().isoformat(timespec="seconds"),
        "pages": [
            {"src": p.rel + ".md", "out": p.out_rel, "title": p.title, "hash": p.body_hash()}
            for p in pages
        ]
        + [{"src": None, "out": f.out_rel, "title": f.title, "hash": None} for f in folders]
        + [{"src": None, "out": t.out_rel, "title": t.title, "hash": None} for t in tag_indexes]
        + ([{"src": None, "out": tag_list.out_rel, "title": tag_list.title, "hash": None}] if tag_list else [])
        + ([{"src": None, "out": recent_page.out_rel, "title": recent_page.title, "hash": None}] if recent_page else []),
    }
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cfg.state_dir / "manifest.json"
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1))

    log(f"ページ {len(pages)} 枚、フォルダ索引 {len(folders)} 枚、タグ {len(tag_indexes)} 種、メディア {media_count} 点 → {cfg.out}")
    return BuildResult(pages=pages, folders=folders, tags=tag_indexes, recent=recent_page, warnings=warnings, manifest_path=manifest_path, updated=updated)
