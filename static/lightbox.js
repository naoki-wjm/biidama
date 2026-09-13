// biidama lightbox — 依存なし。lightbox2 互換の記法を拾う:
//   <a href="大きい画像" data-lightbox="グループ名" data-title="キャプション"><img src="小さい画像"></a>
// JS が無くても普通のリンクとして画像が開く。JS があればその場で拡大表示し、同じグループ内を前後に送れる。
// 移植元: quartz-plugins/image-lightbox（コードさん製）。クリック委譲なので後から足された要素にも効く。
(function () {
  "use strict";
  if (window.__biidamaLightbox) return;
  window.__biidamaLightbox = true;

  function openLightbox(items, startIndex) {
    var index = startIndex;
    var overlay = document.createElement("div");
    overlay.className = "wjm-lightbox";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML =
      '<button class="wjm-lightbox-close" aria-label="閉じる">×</button>' +
      '<button class="wjm-lightbox-prev" aria-label="前の画像">‹</button>' +
      "<figure><img alt=\"\"><figcaption></figcaption></figure>" +
      '<button class="wjm-lightbox-next" aria-label="次の画像">›</button>';

    var img = overlay.querySelector("img");
    var caption = overlay.querySelector("figcaption");
    var closeBtn = overlay.querySelector(".wjm-lightbox-close");
    var prevBtn = overlay.querySelector(".wjm-lightbox-prev");
    var nextBtn = overlay.querySelector(".wjm-lightbox-next");
    var multiple = items.length > 1;
    prevBtn.style.display = multiple ? "" : "none";
    nextBtn.style.display = multiple ? "" : "none";

    function render() {
      var item = items[index];
      if (!item) return;
      img.src = item.href;
      img.alt = item.alt || item.title;
      caption.textContent = item.title;
      caption.style.display = item.title ? "" : "none";
    }
    function step(delta) {
      index = (index + delta + items.length) % items.length;
      render();
    }
    function close() {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) {
      if (e.key === "Escape") close();
      else if (multiple && e.key === "ArrowLeft") step(-1);
      else if (multiple && e.key === "ArrowRight") step(1);
    }

    overlay.addEventListener("click", function (e) {
      var t = e.target;
      if (t === img || (t.closest && t.closest("button"))) return;
      close();
    });
    closeBtn.addEventListener("click", close);
    prevBtn.addEventListener("click", function () { step(-1); });
    nextBtn.addEventListener("click", function () { step(1); });
    document.addEventListener("keydown", onKey);

    document.body.appendChild(overlay);
    render();
  }

  document.addEventListener("click", function (e) {
    var target = e.target;
    var anchor = target.closest ? target.closest("a[data-lightbox]") : null;
    if (!anchor) return;
    e.preventDefault();
    var group = anchor.getAttribute("data-lightbox") || "";
    var selector = 'a[data-lightbox="' + (window.CSS && CSS.escape ? CSS.escape(group) : group) + '"]';
    var anchors = Array.prototype.slice.call(document.querySelectorAll(selector));
    var items = anchors.map(function (a) {
      // data-alt は開いた絵の alt（絵の中の文字の写しなど。lightbox2 と同じ扱い）。無ければ題を alt に
      return { href: a.href, title: a.getAttribute("data-title") || "", alt: a.getAttribute("data-alt") || "" };
    });
    openLightbox(items, Math.max(0, anchors.indexOf(anchor)));
  });
})();
