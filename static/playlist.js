// biidama playlist — 依存なし。原稿は標準 HTML のまま（案C）:
//   <div class="playlist">
//     <audio controls src="曲.mp3" data-title="曲名" data-artist="作者"></audio>
//     ...
//   </div>
// Obsidian や JS の無い環境では各曲が普通の <audio> として鳴る。JS があれば <audio> 群を一つの操作盤
// （曲一覧・前後・シャッフル・リピート・シーク・音量）に組み替える。
// 移植元: 旅人ノ夢 js/playlist.js（vanilla）。操作盤の HTML は PHP ではなくここで組む。
// 移植時に直した所:
//   - 再生中かどうかは自前のフラグではなく <audio> の play/pause イベントから取る
//     （iPhone のロック画面やコントロールセンターで止めた後にボタン表示がずれ、二度押しになるのを防ぐ）
//   - 1曲リピートは <audio loop> に任せる（ended から play() し直すより確実で、継ぎ目も無い）
//   - 音量つまみは iOS では効かない（本体のボタン専用）ので、iOS では出さない
//     （volume を書いて読み返す判定は、最近の iOS が書いた値をそのまま返すので使えない）
(function () {
  "use strict";
  if (window.__biidamaPlaylist) return;
  window.__biidamaPlaylist = true;

  var SVG_SHUFFLE =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>' +
    '<polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>';
  var SVG_PREV =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="3" y="5" width="3" height="14"/><polygon points="21 5 9 12 21 19 21 5"/></svg>';
  var SVG_NEXT =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="18" y="5" width="3" height="14"/><polygon points="3 5 15 12 3 19 3 5"/></svg>';
  var SVG_PLAY =
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
  var SVG_PAUSE =
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
  var REPEAT_ARROWS =
    '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>' +
    '<polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>';
  var SVG_REPEAT =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    REPEAT_ARROWS + "</svg>";
  var SVG_REPEAT_ONE =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    REPEAT_ARROWS +
    '<text x="12" y="15" text-anchor="middle" fill="currentColor" stroke="none" font-size="9" font-weight="bold">1</text></svg>';
  var SVG_VOLUME =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor" stroke="none"/>' +
    '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>';

  // iPhone／iPad（iPadOS 13 以降は Mac を名乗るので、タッチ点の数で見分ける）
  var IS_IOS =
    /iP(hone|ad|od)/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  function formatTime(s) {
    if (!s || isNaN(s) || !isFinite(s)) return "0:00";
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  function basename(url) {
    var s = url.split(/[?#]/)[0].split("/").pop() || url;
    try {
      return decodeURIComponent(s);
    } catch (e) {
      return s;
    }
  }

  // 原稿の <audio> 群から曲データを拾う。title が無ければファイル名で代用する
  function collectTracks(source) {
    var tracks = [];
    var audios = source.querySelectorAll("audio");
    for (var i = 0; i < audios.length; i++) {
      var a = audios[i];
      var src = a.getAttribute("src");
      if (!src) {
        var s = a.querySelector("source[src]");
        src = s ? s.getAttribute("src") : "";
      }
      if (!src) continue;
      tracks.push({
        title: a.getAttribute("data-title") || basename(src),
        artist: a.getAttribute("data-artist") || "",
        src: src,
      });
    }
    return tracks;
  }

  function buildPlayer(tracks) {
    var el = document.createElement("div");
    el.className = "playlist-player";
    el.innerHTML =
      '<audio class="pl-audio" preload="metadata"></audio>' +
      '<div class="pl-header">♫ Playlist</div>' +
      '<div class="pl-nowplaying"><div class="pl-title"></div><div class="pl-artist"></div></div>' +
      '<div class="pl-seekbar-wrap">' +
      '<div class="pl-seekbar" role="slider" aria-label="再生位置"><div class="pl-seekbar-fill"></div></div>' +
      '<div class="pl-time"><span class="pl-time-current">0:00</span><span class="pl-time-duration">0:00</span></div>' +
      "</div>" +
      '<div class="pl-controls">' +
      '<button type="button" class="pl-btn pl-btn-shuffle" title="シャッフル: オフ" aria-pressed="false">' + SVG_SHUFFLE + "</button>" +
      '<button type="button" class="pl-btn pl-btn-prev" title="前の曲">' + SVG_PREV + "</button>" +
      '<button type="button" class="pl-btn pl-btn-play" title="再生">' + SVG_PLAY + "</button>" +
      '<button type="button" class="pl-btn pl-btn-next" title="次の曲">' + SVG_NEXT + "</button>" +
      '<button type="button" class="pl-btn pl-btn-repeat" title="リピート: オフ">' + SVG_REPEAT + "</button>" +
      "</div>" +
      '<div class="pl-volume">' + SVG_VOLUME +
      '<input type="range" class="pl-volume-slider" min="0" max="1" step="0.01" value="0.7" aria-label="音量"></div>' +
      '<div class="pl-error" aria-live="polite"></div>' +
      '<div class="pl-list"></div>';

    var audio = el.querySelector(".pl-audio");
    var titleEl = el.querySelector(".pl-title");
    var artistEl = el.querySelector(".pl-artist");
    var seekbar = el.querySelector(".pl-seekbar");
    var seekFill = el.querySelector(".pl-seekbar-fill");
    var timeCurrentEl = el.querySelector(".pl-time-current");
    var timeDurationEl = el.querySelector(".pl-time-duration");
    var btnPlay = el.querySelector(".pl-btn-play");
    var btnPrev = el.querySelector(".pl-btn-prev");
    var btnNext = el.querySelector(".pl-btn-next");
    var btnShuffle = el.querySelector(".pl-btn-shuffle");
    var btnRepeat = el.querySelector(".pl-btn-repeat");
    var volumeWrap = el.querySelector(".pl-volume");
    var volumeSlider = el.querySelector(".pl-volume-slider");
    var errorEl = el.querySelector(".pl-error");
    var listEl = el.querySelector(".pl-list");

    var currentIndex = 0;
    var shuffle = false;
    var repeat = "off"; // off / all / one
    var shuffleOrder = [];

    function isPlaying() {
      return !audio.paused && !audio.ended;
    }

    // シャッフル順は「今の曲を先頭に、残りを混ぜる」。曲一覧から直接選んだ時も同じ形で組み直す
    function makeShuffleOrder(startIndex) {
      var rest = [];
      for (var i = 0; i < tracks.length; i++) if (i !== startIndex) rest.push(i);
      for (var j = rest.length - 1; j > 0; j--) {
        var k = Math.floor(Math.random() * (j + 1));
        var t = rest[j];
        rest[j] = rest[k];
        rest[k] = t;
      }
      shuffleOrder = [startIndex].concat(rest);
    }

    // 次（direction=1）か前（-1）の曲番号。終端で止まる時は -1
    function neighbor(direction) {
      var order = shuffle ? shuffleOrder : null;
      var pos = order ? order.indexOf(currentIndex) : currentIndex;
      var nextPos = pos + direction;
      if (nextPos >= tracks.length) {
        if (repeat !== "all") return -1;
        nextPos = 0;
      } else if (nextPos < 0) {
        nextPos = tracks.length - 1;
      }
      return order ? order[nextPos] : nextPos;
    }

    function loadTrack(index, autoplay) {
      currentIndex = index;
      var track = tracks[index];
      audio.src = track.src;
      audio.load();
      titleEl.textContent = track.title;
      artistEl.textContent = track.artist;
      seekFill.style.width = "0%";
      timeCurrentEl.textContent = "0:00";
      timeDurationEl.textContent = "0:00";
      errorEl.textContent = "";
      updateList();
      if (autoplay) tryPlay();
    }

    function tryPlay() {
      var p = audio.play();
      if (p && p.catch) {
        p.catch(function () {
          errorEl.textContent = "再生できません";
        });
      }
    }

    function updateList() {
      var items = listEl.children;
      for (var i = 0; i < items.length; i++) {
        var current = i === currentIndex;
        items[i].classList.toggle("current", current);
        items[i].querySelector(".pl-item-num").textContent = current && isPlaying() ? "▶" : String(i + 1);
      }
    }

    function updatePlayButton() {
      var playing = isPlaying();
      btnPlay.innerHTML = playing ? SVG_PAUSE : SVG_PLAY;
      btnPlay.title = playing ? "一時停止" : "再生";
      updateList();
    }

    function updateRepeatButton() {
      btnRepeat.innerHTML = repeat === "one" ? SVG_REPEAT_ONE : SVG_REPEAT;
      btnRepeat.title = "リピート: " + (repeat === "off" ? "オフ" : repeat === "all" ? "全曲" : "1曲");
      btnRepeat.classList.toggle("active", repeat !== "off");
      audio.loop = repeat === "one";
    }

    // 曲一覧
    tracks.forEach(function (track, i) {
      var item = document.createElement("div");
      item.className = "pl-item";
      var num = document.createElement("span");
      num.className = "pl-item-num";
      num.textContent = String(i + 1);
      var info = document.createElement("div");
      info.className = "pl-item-info";
      var t = document.createElement("div");
      t.className = "pl-item-title";
      t.textContent = track.title;
      info.appendChild(t);
      if (track.artist) {
        var ar = document.createElement("div");
        ar.className = "pl-item-artist";
        ar.textContent = track.artist;
        info.appendChild(ar);
      }
      item.appendChild(num);
      item.appendChild(info);
      item.addEventListener("click", function () {
        if (shuffle) makeShuffleOrder(i);
        loadTrack(i, true);
      });
      listEl.appendChild(item);
    });

    // 操作
    btnPlay.addEventListener("click", function () {
      if (isPlaying()) audio.pause();
      else tryPlay();
    });
    btnPrev.addEventListener("click", function () {
      if (audio.currentTime > 3) {
        audio.currentTime = 0;
        return;
      }
      var prev = neighbor(-1);
      if (prev >= 0) loadTrack(prev, true);
    });
    btnNext.addEventListener("click", function () {
      var next = neighbor(1);
      if (next >= 0) loadTrack(next, true);
      else audio.pause();
    });
    btnShuffle.addEventListener("click", function () {
      shuffle = !shuffle;
      if (shuffle) makeShuffleOrder(currentIndex);
      btnShuffle.classList.toggle("active", shuffle);
      btnShuffle.setAttribute("aria-pressed", shuffle ? "true" : "false");
      btnShuffle.title = "シャッフル: " + (shuffle ? "オン" : "オフ");
    });
    btnRepeat.addEventListener("click", function () {
      repeat = repeat === "off" ? "all" : repeat === "all" ? "one" : "off";
      updateRepeatButton();
    });
    volumeSlider.addEventListener("input", function () {
      audio.volume = parseFloat(volumeSlider.value);
    });
    seekbar.addEventListener("click", function (e) {
      if (!audio.duration || !isFinite(audio.duration)) return;
      var rect = seekbar.getBoundingClientRect();
      var x = (e.clientX - rect.left) / rect.width;
      audio.currentTime = Math.max(0, Math.min(1, x)) * audio.duration;
    });

    // <audio> の状態を表示に映す（ボタン以外の経路で止まった時もここで揃う）
    audio.addEventListener("play", updatePlayButton);
    audio.addEventListener("pause", updatePlayButton);
    audio.addEventListener("timeupdate", function () {
      if (audio.duration && isFinite(audio.duration)) {
        seekFill.style.width = (audio.currentTime / audio.duration) * 100 + "%";
      }
      timeCurrentEl.textContent = formatTime(audio.currentTime);
    });
    audio.addEventListener("loadedmetadata", function () {
      timeDurationEl.textContent = formatTime(audio.duration);
    });
    audio.addEventListener("ended", function () {
      // 1曲リピートは loop 属性が受け持つのでここには来ない
      var next = neighbor(1);
      if (next >= 0) loadTrack(next, true);
      else updatePlayButton();
    });
    audio.addEventListener("error", function () {
      errorEl.textContent = "ファイルを読み込めません";
    });

    audio.volume = 0.7;
    if (IS_IOS) volumeWrap.hidden = true;

    updateRepeatButton();
    loadTrack(0, false);
    return el;
  }

  function init() {
    var sources = document.querySelectorAll("div.playlist");
    for (var i = 0; i < sources.length; i++) {
      var source = sources[i];
      if (source.__biidamaDone) continue;
      source.__biidamaDone = true;
      var tracks = collectTracks(source);
      if (tracks.length === 0) continue;
      var player = buildPlayer(tracks);
      source.parentNode.insertBefore(player, source);
      source.hidden = true; // 原稿の <audio> 群は残しておく（操作盤が壊れた時の逃げ道）
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
