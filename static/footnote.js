// biidama footnote.js — 脚注の番号を押すと、その場に注の中身を浮かべる。依存なし。
// 対象は Markdown の脚注（[^1] と [^1]: 中身）が出す形:
//   本文の番号  <sup id="fnref:1"><a class="footnote-ref" href="#fn:1">1</a></sup>
//   末尾の一覧  <div class="footnote"><ol><li id="fn:1">…<a class="footnote-backref">↩</a></li></ol></div>
// JS が無ければ番号はただのページ内リンク（末尾の一覧へ飛び、↩ で本文へ戻る）。
// 閉じ方: 同じ番号をもう一度押す・箱の外を押す・Esc・画面の幅が変わった時。
(function () {
  "use strict";
  var pop = null; // いま出ている箱
  var owner = null; // その箱を出した番号

  function close() {
    if (!pop) return;
    pop.parentNode.removeChild(pop);
    owner.setAttribute("aria-expanded", "false");
    pop = owner = null;
  }

  function open(ref, note) {
    close();
    pop = document.createElement("div");
    pop.className = "footnote-pop";
    pop.setAttribute("role", "note");
    for (var i = 0; i < note.childNodes.length; i++) pop.appendChild(note.childNodes[i].cloneNode(true));
    // 「↩ 戻る」は箱の中では要らない。その手前に置かれている改行しない空白も落とす
    var backs = pop.querySelectorAll(".footnote-backref");
    for (var k = 0; k < backs.length; k++) {
      var prev = backs[k].previousSibling;
      if (prev && prev.nodeType === 3) prev.nodeValue = prev.nodeValue.replace(/ $/, "");
      backs[k].parentNode.removeChild(backs[k]);
    }
    document.body.appendChild(pop);

    // 番号のすぐ下、左端を番号に合わせる。画面からはみ出すなら内側へ寄せ、下に入らなければ上へ
    var gap = 6;
    var edge = 8;
    var r = ref.getBoundingClientRect();
    var left = Math.max(edge, Math.min(r.left, document.documentElement.clientWidth - pop.offsetWidth - edge));
    var top = r.bottom + gap;
    if (top + pop.offsetHeight > window.innerHeight && r.top - gap - pop.offsetHeight > 0) top = r.top - gap - pop.offsetHeight;
    pop.style.left = left + window.pageXOffset + "px";
    pop.style.top = top + window.pageYOffset + "px";

    owner = ref;
    ref.setAttribute("aria-expanded", "true");
  }

  function refOf(target) {
    return target && target.closest ? target.closest("a.footnote-ref") : null;
  }

  document.addEventListener("click", function (e) {
    if (e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; // 別タブで開く等はブラウザに任せる
    var ref = refOf(e.target);
    if (!ref) return;
    var note = null;
    try {
      note = document.getElementById(decodeURIComponent((ref.getAttribute("href") || "").slice(1)));
    } catch (err) {
      /* 壊れた % 表記。ふつうのリンクとして動かす */
    }
    if (!note) return;
    e.preventDefault();
    if (owner === ref) close();
    else open(ref, note);
  });

  // 箱の外を押したら閉じる。click ではなく pointerdown で見る
  // （iPhone は、押せるもの以外を押した時の click を document まで届けない）。番号の上は上の click に任せる
  document.addEventListener("pointerdown", function (e) {
    if (pop && !pop.contains(e.target) && !refOf(e.target)) close();
  });

  document.addEventListener("keydown", function (e) {
    if (pop && (e.key === "Escape" || e.key === "Esc")) {
      var ref = owner;
      close();
      ref.focus();
    }
  });

  window.addEventListener("resize", close);
})();
