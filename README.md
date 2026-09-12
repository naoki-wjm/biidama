# biidama（ビー玉）

Obsidian の保管庫（黒曜石）から、公開と決めたページだけを透明なガラス玉として一つ出す、自分用の静的サイト生成器です。

- 原本は Obsidian でそのまま読める標準 Markdown と標準 HTML（と青空文庫形式のルビ）。公開側で CSS・JavaScript・生成処理により「強化」します
- `publish: true` と書いたページだけを出します。書かなければ非公開です
- 公開は人が押します（`biidama publish`）。Git の自動コミットとは無関係に、手元でビルドして、変わったファイルだけを送り先へ上書き送信します
- 更新日は frontmatter ではなく、公開時の本文の差分で決めます
- 本体は最小限。ルビ・前後ナビ・Lightbox・プレイリスト・YouTube は機能ごとに分けてあり、本体の更新に巻き込まれません
- 完成したら凍結します。依存は少なく、版は固定。更新するのはバグを踏んだ時と、欲しい機能が生えた時だけです

## 状態

2026-09 時点で `build`（保管庫 → 静的 HTML）と `publish`（変わったファイルだけ送信）・`prune`（抜け殻の掃除）が動きます。lightbox（`<a data-lightbox="組" data-title="題"><img></a>` の lightbox2 互換記法）・playlist（`<div class="playlist">` の中に `<audio controls src data-title data-artist>` を並べる）・タグページ（`タグ.html` と `タグ/<名前>.html` を自動生成。原稿側で `タグ` の名前は予約）・OGP（frontmatter の `description`、無ければ本文の先頭。設定の `site.icon` に `static/` の中の画像を書けば OGP 画像・ファビコン・ヘッダーの印にも使う。絵はリポに入れない。`site.theme_color` でブラウザの枠の色、`site.head_extra` で作者宣言などの行を head にそのまま入れられる）・コード枠の色付け（Pygments）・読者のテーマ／書体切替と「上へ戻る」（`static/site.js`）・「最近の更新」の一覧（`最近の更新.html`。台帳の更新日で新しい順。トップページの末尾にも数件出す。件数は設定の `site.recent` と `site.recent_home`、0 で無し）が入っています。

## 使い方

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -e .
cp config.example.yml config.local.yml   # 保管庫の場所・除外フォルダ・サイト名を書く
biidama build -c config.local.yml        # out/ に HTML が出る
cp .env.example .env                     # 送り先（ssh の接続先と遠隔のフォルダ）を書く
biidama publish -c config.local.yml --dry-run   # 何を送るか見るだけ
biidama publish -c config.local.yml             # 変わったファイルだけ送る
```

- 出力の URL は保管庫の相対パスそのまま＋ `.html`（`雑録/○○.html`）
- 同名ノートの無いフォルダには索引ページを自動で作ります（`雑記.html` など）
- `タグ`・`最近の更新`・`static` は出力側で使う名前なので、原稿のフォルダ名・ノート名には使えません（同名があれば止まります）
- 止まるのは、公開ページの frontmatter が壊れている・2ページが同じ出力先になる・basename が複数一致する・`![[埋め込み]]` や `#^ブロック参照` に出会った時。リンク切れや非公開ページへのリンクは注意を出して続けます
- `.biidama/manifest.json` に「ページ一覧・出力先・本文ハッシュ」を書き出します

### publish と prune

- `publish` は build したあと、前回の台帳（`.biidama/ledger.json`）と中身のハッシュを比べ、**変わったファイルだけ**を tar に束ねて ssh 一本で送り先へ上書きします。scp をファイルごとに呼ばない（速い・日本語ファイル名でも転ばない）
- 送れた時だけ台帳を書きます。更新日は台帳と本文ハッシュで決まります（一致→台帳の日付、変わった→今日、初回→`modified`）
- 送ったあと、台帳にあって今回の出力に無いファイル（消したページ・改名の抜け殻）を一覧し、**その場で `y/n` を聞いてから**消します。`n` なら残り、台帳にも残ります。単独の `prune` も同じことをします
- 台帳に無いファイル（手で置いた `.htaccess` など）には触りません

### 原稿側の約束

- 公開するページに `publish: true`
- 前のページは `prev: "[[前のページ]]"`（次のページは逆引き）。`next: "[[次のページ]]"` も同じように受けます。両方書いて食い違う時は警告して、それぞれ書いた方を残します
- ルビは `|親《かな》`・`｜親《かな》`・`漢字《かな》`
- Callout は Obsidian の `> [!note]`。折りたたみ `> [!warning]-` は `<details>` になります
- 表の中の wikilink の縦棒は `\|`（Obsidian と同じ）

## 構成

```
biidama/          … 本体（config・vault・links・mdext・folders・build・publish・cli）
biidama/tags.py   … タグページの自動生成
biidama/recent.py … 「最近の更新」の一覧（台帳の更新日で並べる）
biidama/features/ … 分離した機能（ruby・series）
templates/        … jinja2 雛型（base・page・folder・tag・tags・recent・_recent＝トップ末尾の部品）
static/           … 公開側の CSS（style.css・pygments.css）と site.js・lightbox.js・playlist.js。そのまま out/static/ に複製
tests/samples/    … 合成の試験片と期待 HTML（黄金テスト）
tests/            … 止まるべき所で止まることの確認
```

依存は 5 本。版は固定です（`requirements.txt`・`pyproject.toml`）。

- markdown … Markdown → HTML の本体
- jinja2 … 雛型
- pyyaml … 設定と frontmatter
- pymdown-extensions … 引用の中のコード枠（SuperFences）と、コード枠の色付けの受け口（highlight）
- pygments … コード枠の色付け（色は `static/pygments.css`）

試験には pytest を使います（`pip install -e .[test]`）。

### コード枠の色を作り直す

`static/pygments.css` は Pygments から作った生成物です。色を変えたい時だけ作り直します:

```
python -c "from pygments.formatters import HtmlFormatter as F; print(F(style='default').get_style_defs('.highlight'))"
```

ライトは `default`、ダークは `github-dark` を `:root[data-theme="dark"] .highlight` と `@media (prefers-color-scheme: dark)` の `:root:not([data-theme="light"]) .highlight` の前置きで並べています（`.hll` と枠自体の背景は落とす）。

### 開発

```
.venv/Scripts/python -m pytest              # 試験
BIIDAMA_UPDATE=1 .venv/Scripts/python -m pytest   # 期待 HTML を作り直す（差分を目で見てから）
```

`fixtures/`（.gitignore 済み）に実原稿の写しと設定を置くと、それも試験に使います。

## 自分用です

自分のサイトのために作っています。Issue は読みますが、対応の約束はしません。フォークはご自由に（MIT）。

## 作っている顔ぶれ

設計と実装は Claude Code（Anthropic）と一緒に進めています。要求の整理と感想戦には Claude.ai と ChatGPT の窓も加わりました。書いたコードの査読は Codex（OpenAI）にも頼みます。どれを採ってどれを捨てるかは、人間（和条門尚樹）が決めます。

## 由来

黒曜石（Obsidian）は火山のガラス、ビー玉は透明なガラス玉です。ラムネの瓶のビー玉を押し込んで開けるのが、公開ボタンの絵です。
