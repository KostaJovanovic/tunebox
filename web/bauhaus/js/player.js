/* The player bar at the bottom, and the now playing canvas (big cover). On a phone the bar is a mini
   bar: a tap or swipe up opens the canvas, which has every control; a sideways swipe skips.
   On a desktop the bar keeps its controls, and the canvas can show lyrics beside the cover. */
import { $, esc, fmt, secs, cssUrl } from "../../shared/dom.js";
import { state, ctl } from "../../shared/playback.js";
import { fetchLyrics, syncedHtml, plainHtml } from "../../shared/lyrics.js";
import { store } from "../../shared/device.js";
import { house, feat } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import * as icon from "./icons.js";
import { follower } from "./lyrics.js";
import { setVol, volumeTouched } from "./settings.js";

export const phone = () => innerWidth <= 760;           /* the phone layout (phone.css) */
const playIcon = s => s.paused || !s.current ? icon.PLAY : icon.PAUSE;
/* the artist and album link to their pages */
const subtitle = c => c ? [c.artist && `<button class="artlink" data-act="goto" data-to="artist">${esc(c.artist)}</button>`,
  c.album && `<button class="artlink" data-act="goto" data-to="album">${esc(c.album)}</button>`].filter(Boolean).join(" · ") : "Search for something to play";
const setHtml = (el, html) => { if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; } };
const upcoming = s => Math.max(0, (s.queue || []).length - 1);
const countBadge = (el, n) => { el.hidden = !n; el.textContent = n > 99 ? "99+" : n; };

/* ---------- the bar ---------- */
let seeking = false;
export function paintBar(s) {
  const c = s.current;
  $("#pTitle").textContent = c ? c.title : "Nothing playing";
  setHtml($("#pSub"), subtitle(c));
  if (c && $("#pImg").dataset.src !== c.thumb) { $("#pImg").src = c.thumb; $("#pImg").dataset.src = c.thumb; }
  $("#pBtn").innerHTML = playIcon(s);
  $("#pStatus").textContent = s.loading ? "Loading" : (s.error || (s.ramping ? "Waking up" : ""));
  $("#prog").classList.toggle("loading", !!s.loading);
  const dur = s.duration || secs(c?.duration);   /* restored paused after a restart: mpv has no length yet */
  $("#tPos").textContent = fmt(s.position); $("#tDur").textContent = fmt(dur);
  if (!seeking) {
    $("#seek").max = Math.max(1, dur); $("#seek").value = s.position;
    $("#fill").style.width = dur ? `${Math.min(100, (s.position / dur) * 100)}%` : "0";
  }
  countBadge($("#qCount"), upcoming(s));
  document.title = c ? `${s.paused ? "❚❚" : "▶"} ${c.title} · ${house.name}` : house.name;
}

$("#seek").addEventListener("input", () => {
  seeking = true; $("#tPos").textContent = fmt($("#seek").value);
  $("#fill").style.width = `${($("#seek").value / $("#seek").max) * 100}%`;
});
$("#seek").addEventListener("change", async () => { await ctl("seek", +$("#seek").value); seeking = false; });

/* the song opens the canvas; on a phone the whole bar does, a sideways swipe skips and a swipe up opens it */
let barSwipe = null, barSwiped = 0;
const bar = $(".player .in"), now = $(".player .now");
bar.addEventListener("click", e => {
  if (Date.now() - barSwiped < 400 || e.target.closest(".artlink")) return;
  if (e.target.closest(".now") || (phone() && !e.target.closest("button, input, .vol"))) toggleCanvas(phone() ? true : undefined);
});
bar.addEventListener("pointerdown", e => {
  if (!phone() || e.button > 0 || (e.target.closest("button, input, .vol") && !e.target.closest(".now"))) return;
  barSwipe = { x: e.clientX, y: e.clientY, id: e.pointerId, dx: 0, dy: 0 };
});
addEventListener("pointermove", e => {
  if (!barSwipe || e.pointerId !== barSwipe.id) return;
  barSwipe.dx = e.clientX - barSwipe.x; barSwipe.dy = e.clientY - barSwipe.y;
  if (Math.abs(barSwipe.dx) > 8 && Math.abs(barSwipe.dx) > Math.abs(barSwipe.dy)) {
    now.classList.add("swiping"); now.style.transform = `translateX(${barSwipe.dx * .6}px)`;
  }
});
function endBarSwipe(e, cancel) {
  if (!barSwipe || e.pointerId !== barSwipe.id) return;
  const { dx, dy } = barSwipe; barSwipe = null;
  now.classList.remove("swiping"); now.style.transform = "";
  if (cancel) return;
  if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy)) { barSwiped = Date.now(); if (navigator.vibrate) navigator.vibrate(10); ctl(dx < 0 ? "next" : "prev"); }
  else if (dy < -40 && Math.abs(dy) > Math.abs(dx)) { barSwiped = Date.now(); toggleCanvas(true); }
}
addEventListener("pointerup", e => endBarSwipe(e));
addEventListener("pointercancel", e => endBarSwipe(e, true));

/* ---------- the canvas ---------- */
const cv = $("#canvas");
export const canvasOpen = () => cv.classList.contains("open");

/* on a desktop it sits above the bar */
function placeCanvas() { cv.style.bottom = phone() ? "" : $(".player").offsetHeight + "px"; }
addEventListener("resize", placeCanvas);

export function toggleCanvas(open = !canvasOpen()) {
  if (open === canvasOpen()) return;
  cv.classList.toggle("open", open); cv.setAttribute("aria-hidden", !open);
  document.body.classList.toggle("canvas-open", open);
  if (open) { placeCanvas(); paintCanvas(true); history.pushState({ canvas: 1 }, ""); }   /* Back (Android) closes it */
  else if (history.state?.canvas) history.back();
  syncLyrBtn();
}
addEventListener("popstate", () => { if (canvasOpen()) { cv.classList.remove("open"); document.body.classList.remove("canvas-open"); } });

let lyrOn = store.get("tb_clyr", "0") === "1", cSeeking = false, lyrVid = null;
const lyrBox = $("#cLyr"), follow = follower(lyrBox, 0.4, true);

export function toggleCanvasLyrics(open = !lyrOn) { if (!feat("lyrics")) return; lyrOn = open; store.set("tb_clyr", lyrOn ? "1" : "0"); paintCanvas(true); syncLyrBtn(); }

/* On a desktop with the canvas open, every Lyrics button (the canvas's and the bar's, and L) shows the
   canvas's own lyrics beside the cover; otherwise they open the Lyrics drawer */
export const canvasLyrics = () => canvasOpen() && !phone();
export function syncLyrBtn() { $("#lyrBtn").classList.toggle("on", canvasLyrics() ? lyrOn : $("#lyrics").classList.contains("open")); }

export function paintCanvas(force) {
  if (!canvasOpen()) return;
  const s = state, c = s.current;
  if ((c?.thumb || "") !== $("#cImg").dataset.src) {
    $("#cImg").dataset.src = c?.thumb || "";
    if (c?.thumb) $("#cImg").src = c.thumb; else $("#cImg").removeAttribute("src");
    $("#cBg").style.backgroundImage = c?.thumb ? cssUrl(c.thumb) : "";
  }
  $("#cTitle").textContent = c ? c.title : "Nothing playing";
  setHtml($("#cSub"), subtitle(c));
  const dur = s.duration || secs(c?.duration);
  $("#cPos").textContent = fmt(s.position); $("#cDur").textContent = fmt(dur);
  if (!cSeeking) {
    $("#cSeek").max = Math.max(1, dur); $("#cSeek").value = s.position || 0;
    $("#cSeek").style.setProperty("--p", dur ? `${Math.min(100, (s.position || 0) / dur * 100)}%` : "0%");
  }
  $("#cBtn").innerHTML = playIcon(s);
  if (!volumeTouched()) $("#cVol").value = s.volume ?? 0;
  countBadge($("#cCount"), upcoming(s));
  const lyr = lyrOn && feat("lyrics");
  cv.classList.toggle("lyr-on", lyr); $("#cLyrToggle").classList.toggle("on", lyr);
  if (lyr && !phone() && (c?.videoId || null) !== lyrVid) loadCanvasLyrics();
  if (force) follow.tick(true);
}

async function loadCanvasLyrics() {
  const c = state.current;
  lyrVid = c?.videoId || null; follow.set(null);
  lyrBox.className = "clyr";
  if (!c) { lyrBox.innerHTML = '<p class="note">Nothing playing</p>'; return; }
  lyrBox.innerHTML = '<p class="note">Finding lyrics…</p>';
  const d = await fetchLyrics(c);
  if (lyrVid !== c.videoId) return;
  if (d.instrumental) lyrBox.innerHTML = '<p class="note">Instrumental</p>';
  else if (d.none) lyrBox.innerHTML = '<p class="note">No lyrics found for this song.</p>';
  else if (d.synced) { follow.set(d.synced); lyrBox.innerHTML = syncedHtml(d.synced); follow.tick(true); }
  else { lyrBox.className = "clyr plain"; lyrBox.innerHTML = plainHtml(d.plain); }
}
setInterval(() => { if (canvasOpen() && lyrOn) follow.tick(); }, 200);

$("#cSeek").addEventListener("input", () => {
  cSeeking = true; $("#cPos").textContent = fmt($("#cSeek").value);
  $("#cSeek").style.setProperty("--p", `${$("#cSeek").value / $("#cSeek").max * 100}%`);
});
$("#cSeek").addEventListener("change", async () => { await ctl("seek", +$("#cSeek").value); cSeeking = false; });
$("#cVol").addEventListener("input", () => setVol(+$("#cVol").value));

/* touch: a swipe down closes it; a swipe sideways on the cover skips (left: next, right: previous) */
let cDrag = null, artSwiped = 0;
const art = $("#cImg");
cv.addEventListener("pointerdown", e => {
  if (e.pointerType === "mouse" || e.target.closest("input, .clyr")) return;
  cDrag = { y: e.clientY, x: e.clientX, id: e.pointerId, dy: 0, dx: 0, on: false, side: false, art: e.target === art };
});
addEventListener("pointermove", e => {
  if (!cDrag || e.pointerId !== cDrag.id) return;
  const dy = e.clientY - cDrag.y, dx = e.clientX - cDrag.x;
  if (!cDrag.on && !cDrag.side && cDrag.art && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) { cDrag.side = true; art.classList.add("swiping"); }
  if (cDrag.side) { cDrag.dx = dx; art.style.transform = `translateX(${dx * .6}px)`; return; }
  if (!cDrag.on && dy > 10 && dy > Math.abs(dx)) { cDrag.on = true; cv.classList.add("dragging"); }
  if (cDrag.on) { cDrag.dy = Math.max(0, dy); cv.style.transform = `translateY(${cDrag.dy}px)`; }
});
function endCanvasDrag(e, cancel) {
  if (!cDrag || e.pointerId !== cDrag.id) return;
  const d = cDrag; cDrag = null;
  if (d.side) {
    art.classList.remove("swiping"); art.style.transform = ""; artSwiped = Date.now();
    if (!cancel && Math.abs(d.dx) > 70) { if (navigator.vibrate) navigator.vibrate(10); ctl(d.dx < 0 ? "next" : "prev"); }
    return;
  }
  if (!d.on) return;
  cv.classList.remove("dragging"); cv.style.transform = "";
  if (d.dy > 110) toggleCanvas(false);
}
addEventListener("pointerup", e => endCanvasDrag(e));
addEventListener("pointercancel", e => endCanvasDrag(e, true));

on("canvas-close", () => toggleCanvas(false));
on("canvas-lyrics", () => toggleCanvasLyrics());
/* the cover was just swiped: the tap that ends the swipe isn't one */
export const coverSwiped = () => Date.now() - artSwiped < 400;
