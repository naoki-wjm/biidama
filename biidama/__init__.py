"""biidama — Obsidian の保管庫から公開ページだけを静的 HTML にする生成器。"""

__version__ = "0.1.0"


class BuildError(Exception):
    """ビルドを止める誤り。黙って崩さないために投げる。"""
