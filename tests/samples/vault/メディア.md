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
