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
from .features.series import compute_nav
from .folders import FolderIndex, make_folder_indexes
from .links import LinkIndex, Node, relative_href, root_prefix
from .mdext import RenderContext, make_markdown, render_body
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
RESERVED_FILES = (TAG_DIR + ".html",)


def check_out_collisions(nodes: list[Node]) -> None:
    seen: dict[str, str] = {}
    for n in nodes:
        key = n.out_rel.lower()  # Windows と多くのホスティングは大文字小文字を区別しない
        if key in seen:
            raise BuildError(f"2つのページが同じ出力先になります: {seen[key]} と {n.rel}")
        if key.startswith(RESERVED_PREFIXES) or key in RESERVED_FILES:
            raise BuildError(f"フォルダ名・ノート名 static と {TAG_DIR} は出力側で使うので原稿には使えません: {n.rel}")
        seen[key] = n.rel


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
_WS_RE = re.compile(r"\s+")


def summarize(body_html: str, limit: int = 120) -> str:
    """OGP の description 用。本文 HTML からタグを剥がして先頭だけ（frontmatter に description があればそちらを使う）。"""
    text = _WS_RE.sub(" ", html_mod.unescape(_TAG_RE.sub("", body_html))).strip()
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
    check_out_collisions(nodes)
    index = LinkIndex(nodes)  # タグページは wikilink の解決先にしない
    tag_node: dict[str, TagIndex] = {t.tag: t for t in tag_indexes}
    navs = compute_nav(pages, index, warnings)

    env = make_env()
    page_tpl = env.get_template("page.html")
    folder_tpl = env.get_template("folder.html")
    tag_tpl = env.get_template("tag.html")
    tags_tpl = env.get_template("tags.html")
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
        "has_tags": tag_list is not None,
    }

    ctx = RenderContext(index=index, warnings=warnings)
    md = make_markdown(ctx)
    ledger = load_ledger(cfg)
    today = dt.date.today()

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

    # 失敗しうる変換をすべて先に済ませ、成功した時だけ旧出力を消して書き出す
    outputs: list[tuple[str, str]] = []
    updated: dict[str, dt.date | None] = {}
    for p in pages:
        body_html = render_body(md, ctx, p, p.title, p.body)
        nav = navs[p.rel]
        updated[p.rel] = updated_date(p, ledger, today)
        desc = str(p.frontmatter.get("description") or "").strip() or summarize(body_html)
        html = page_tpl.render(
            **common(p, desc, "article"),
            body=body_html,
            created=p.created.isoformat() if p.created else "",
            updated=updated[p.rel].isoformat() if updated[p.rel] and updated[p.rel] != p.created else "",
            tags=tag_links(p, p.tags),
            crumbs=breadcrumbs(p, folder_node),
            prev={"title": nav.prev.title, "href": link(p, nav.prev)} if nav.prev else None,
            next={"title": nav.next.title, "href": link(p, nav.next)} if nav.next else None,
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

    manifest = {
        "biidama": __version__,
        "built": dt.datetime.now().isoformat(timespec="seconds"),
        "pages": [
            {"src": p.rel + ".md", "out": p.out_rel, "title": p.title, "hash": p.body_hash()}
            for p in pages
        ]
        + [{"src": None, "out": f.out_rel, "title": f.title, "hash": None} for f in folders]
        + [{"src": None, "out": t.out_rel, "title": t.title, "hash": None} for t in tag_indexes]
        + ([{"src": None, "out": tag_list.out_rel, "title": tag_list.title, "hash": None}] if tag_list else []),
    }
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cfg.state_dir / "manifest.json"
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1))

    log(f"ページ {len(pages)} 枚、フォルダ索引 {len(folders)} 枚、タグ {len(tag_indexes)} 種 → {cfg.out}")
    return BuildResult(pages=pages, folders=folders, tags=tag_indexes, warnings=warnings, manifest_path=manifest_path, updated=updated)
