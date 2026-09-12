---
publish: true
title: 入口
created: 2026-01-10
modified: 2026-02-01
---
# 入口

|見本《みほん》サイトの|入口《いりぐち》です。全角の｜親文字《おやもじ》と、縦棒なしの漢字《かんじ》連続《れんぞく》も読めます。

## リンクの形

- 裸: [[記事A]]
- 表示名: [[記事A|A の記事]]
- パス: [[雑記/記事A]]
- パス＋表示名: [[雑記/記事B|B の記事]]
- 見出し: [[記事A#二つ目]]
- 見出し＋表示名: [[記事A#二つ目|二つ目へ]]
- パス＋見出し＋表示名: [[雑記/記事A#二つ目|パスと見出し]]
- 同名見出しの2つ目は先頭一致になる: [[記事A#二つ目]]
- フォルダ索引: [[雑記]]
- ハブ note: [[小説]]
- 無いページ: [[存在しない]]
- 非公開のページ: [[下書き|下書き（非公開）]]
- 拡張子つき: [[記事A.md]]

## 自動リンク

https://example.com/path/ページ?q=1。
文中の https://example.com/a （括弧の前で止まる）と、既存のリンク [example](https://example.com/b) は二重にしない。

## そのまま通すもの

<a href="https://example.com/img/1.jpg" data-lightbox="g" data-title="一枚目"><img src="https://example.com/img/1.jpg" width="150" /></a> <a href="https://example.com/img/2.jpg" data-lightbox="g" data-title="二枚目"><img src="https://example.com/img/2.jpg" width="150" /></a>

<!-- コメントはそのまま残る -->

![代替文](https://example.com/img/3.jpg)

code span の中は触らない: `[[記事A]]` と `漢字《かな》` と `https://example.com/c`

#タグだけの行
#もう一つ 空白のある行

#見出しではない（空白なし）
