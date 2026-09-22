---
publish: true
created: 2026-01-20
---
メディアの生 HTML。

<audio controls src="https://example.com/m/01.mp3"></audio>

<video playsinline preload="metadata" poster="https://example.com/m/p.png" controls src="https://example.com/m/v.mp4"></video>

<iframe id="youtube" src="https://www.youtube.com/embed/xxxx" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>

<div class="playlist">
<audio controls src="https://example.com/m/01.mp3" data-title="一曲目" data-artist="作者"></audio>
<audio controls src="https://example.com/m/02.mp3"></audio>
</div>

<details>
<summary>手書きの details</summary>
<p>中身は生 HTML のまま通る。</p>
</details>

ひと目で段の三部品（wiki 記事の先頭用）。

<div class="cards">
<div class="card"><b>白茶</b><br>摘んで干すだけ。</div>
<div class="card"><h4>緑茶</h4>蒸すか炒るかで酸化を止める。</div>
</div>

<div class="flow">
<div class="step">摘む</div>
<div class="step">萎凋</div>
<div class="step">乾かす</div>
</div>

<figure>
<svg viewBox="0 0 120 40" width="120" height="40" style="max-width:100%;height:auto" role="img" aria-label="左から右へ"><line x1="10" y1="20" x2="110" y2="20" stroke="currentColor" stroke-width="2"/></svg>
<figcaption>線は読者の画面色に追従する</figcaption>
</figure>
