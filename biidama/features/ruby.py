"""青空文庫形式のルビ → <ruby>。

  |親文字《かな》 ／ ｜親文字《かな》 … 縦棒つき（親文字は何でもよい）
  漢字《かな》                     … 縦棒なし（直前の漢字の連続が親文字）

インライン処理として登録し、code span と生 HTML の退避（優先度 90）より後に走らせる。
"""

from __future__ import annotations

import xml.etree.ElementTree as etree

from markdown.inlinepatterns import InlineProcessor

KANJI = "一-龯々〆ヶ〇㐀-䶿豈-﫿"
RUBY_RE = rf"[|｜]([^|｜《》\n]+)《([^《》\n]+)》|([{KANJI}]+)《([^《》\n]+)》"
PRIORITY = 85


class RubyInline(InlineProcessor):
    def handleMatch(self, m, data):
        base = m.group(1) or m.group(3)
        rt = m.group(2) or m.group(4)
        el = etree.Element("ruby")
        el.text = base
        etree.SubElement(el, "rp").text = "("
        etree.SubElement(el, "rt").text = rt
        etree.SubElement(el, "rp").text = ")"
        return el, m.start(0), m.end(0)


def register(md) -> None:
    md.inlinePatterns.register(RubyInline(RUBY_RE, md), "aozora_ruby", PRIORITY)
