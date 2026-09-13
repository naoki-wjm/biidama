// biidama site.js — 読者の好み（テーマ・書体）と「上へ戻る」。依存なし。
// head で同期に読む（defer にしない）: 最初の描画の前に <html> へ data-theme / data-font を付けて、
// 白い画面が一瞬光るのを防ぐため。ボタンの組み立てだけは DOM ができてから。
// 記憶は localStorage（biidama-theme: "light" | "dark" | 無し＝端末に従う／biidama-font: "mincho" | 無し＝ゴシック）。
(function () {
  "use strict";
  var root = document.documentElement;
  var THEME_KEY = "biidama-theme";
  var FONT_KEY = "biidama-font";
  var THEMES = [
    { value: "", label: "端末に従う", short: "自動" },
    { value: "light", label: "ライト", short: "☀" },
    { value: "dark", label: "ダーク", short: "☾" },
  ];

  function read(key) {
    try {
      return localStorage.getItem(key) || "";
    } catch (e) {
      return "";
    }
  }
  function write(key, value) {
    try {
      if (value) localStorage.setItem(key, value);
      else localStorage.removeItem(key);
    } catch (e) {
      /* プライベートモード等。記憶できないだけで、このページの中では切り替わる */
    }
  }
  // いまの選択はページの中の変数で持つ。保存は最善努力（読めなくても書けなくても、押せば変わる）
  var theme = read(THEME_KEY);
  var font = read(FONT_KEY);
  function apply() {
    if (theme) root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    if (font) root.setAttribute("data-font", font);
    else root.removeAttribute("data-font");
  }
  apply();

  function build() {
    var box = document.querySelector(".prefs");
    if (!box) return;
    box.hidden = false;
    var themeBtn = document.createElement("button");
    themeBtn.type = "button";
    themeBtn.className = "pref-btn pref-theme";
    var fontBtn = document.createElement("button");
    fontBtn.type = "button";
    fontBtn.className = "pref-btn pref-font";

    function label() {
      var cur = THEMES[0];
      for (var i = 0; i < THEMES.length; i++) if (THEMES[i].value === theme) cur = THEMES[i];
      themeBtn.textContent = cur.short;
      themeBtn.title = "テーマ: " + cur.label + "（押すと切り替え）";
      themeBtn.setAttribute("aria-label", themeBtn.title);
      var mincho = font === "mincho";
      fontBtn.textContent = mincho ? "明" : "ゴ";
      fontBtn.title = "書体: " + (mincho ? "明朝" : "ゴシック") + "（押すと切り替え）";
      fontBtn.setAttribute("aria-label", fontBtn.title);
    }
    themeBtn.addEventListener("click", function () {
      var i = 0;
      for (var k = 0; k < THEMES.length; k++) if (THEMES[k].value === theme) i = k;
      theme = THEMES[(i + 1) % THEMES.length].value;
      write(THEME_KEY, theme);
      apply();
      label();
    });
    fontBtn.addEventListener("click", function () {
      font = font === "mincho" ? "" : "mincho";
      write(FONT_KEY, font);
      apply();
      label();
    });
    label();
    box.appendChild(themeBtn);
    box.appendChild(fontBtn);

    // 上へ戻る: ある程度スクロールした時だけ右下に出す
    var top = document.createElement("a");
    top.href = "#";
    top.className = "to-top";
    top.textContent = "▲";
    top.title = "ページの先頭へ";
    top.setAttribute("aria-label", "ページの先頭へ");
    top.hidden = true;
    top.addEventListener("click", function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    document.body.appendChild(top);
    var ticking = false;
    function check() {
      top.hidden = window.scrollY < 600;
      ticking = false;
    }
    window.addEventListener("scroll", function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(check);
      }
    }, { passive: true });
    check();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
