/* The player bar at the bottom, and the now playing canvas (big cover). On a phone the bar is a mini
   bar: a tap or swipe up opens the canvas, which has every control; a sideways swipe skips.
   On a desktop the bar keeps its controls, and the canvas can show lyrics beside the cover. */
import { $, esc, fmt, secs, art as cover, showCover, fadeTo, swapIn } from "../../shared/dom.js";
import { state, ctl, poll, position, waits, inTime } from "../../shared/playback.js";
import { me } from "../../shared/people.js";
import { spring, tracker, project, rubberband, letGo } from "../../shared/motion.js";
import { fetchLyrics, syncedHtml, plainHtml } from "../../shared/lyrics.js";
import { store, lite } from "../../shared/device.js";
import { house, feat } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { setupWallpaper, wallpaperFor } from "../../shared/wallpaper.js";
import * as icon from "./icons.js";
import { follower } from "./lyrics.js";
import { setVol, volumeTouched } from "./settings.js";

export const phone = () => innerWidth <= 760;           /* the phone layout (phone.css) */
const playIcon = s => s.paused || !s.current ? icon.PLAY : icon.PAUSE;
/* the artist and album link to their pages */
const subtitle = c => c ? [c.artist && `<button class="artlink" data-act="goto" data-to="artist">${esc(c.artist)}</button>`,
  c.album && `<button class="artlink" data-act="goto" data-to="album">${esc(c.album)}</button>`].filter(Boolean).join(" · ") : "Search for something to play";
const setHtml = (el, html) => { if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; } };
/* the songs people queued after the one playing; the radio's are left out */
const upcoming = s => Math.max(0, s.userCount || 0);
/* when this device's next song comes on: "Yours in 8 min" (only songs people added count) */
function yours(s) {
  const id = feat("people") && me()?.id, q = s.queue || [];
  const i = id ? q.findIndex((t, k) => k > 0 && k <= (s.userCount || 0) && t.by === id) : -1;
  if (i < 0) return "";
  const w = inTime(waits()[i]);
  return w === "next" ? "Yours is next" : `Yours ${w}`;
}
const countBadge = (el, n) => { el.hidden = !n; el.textContent = n > 99 ? "99+" : n; };

/* ---------- the bar ---------- */
let seeking = false, barVid = null;   /* barVid: the song the bar shows (null before the first paint) */
export function paintBar(s) {
  const c = s.current;
  $("#pTitle").textContent = c ? c.title : "Nothing playing";
  setHtml($("#pSub"), subtitle(c));
  if (c && $("#pImg").dataset.src !== cover(c)) { fadeTo($("#pImg"), $("#pImg").dataset.src = cover(c)); }
  if ((c?.videoId || "") !== barVid) { if (barVid !== null) swapIn($("#pTitle"), $("#pSub")); barVid = c?.videoId || ""; }
  $("#pBtn").innerHTML = playIcon(s);
  /* playing into silence: say so, and the speaker icons go red to show where to turn it up */
  const silent = !!c && !s.paused && !s.ramping && (s.volume ?? 1) <= 0;
  document.documentElement.classList.toggle("silent", silent);
  $("#pStatus").textContent = s.loading ? "Loading" : (s.error || (s.ramping ? "Waking up" : silent ? "Volume is at 0" : yours(s)));
  $("#prog").classList.toggle("loading", !!s.loading);
  const dur = s.duration || secs(c?.duration);   /* restored paused after a restart: mpv has no length yet */
  $("#tPos").textContent = fmt(s.position); $("#tDur").textContent = fmt(dur);
  if (!seeking) {
    $("#seek").max = Math.max(1, dur); $("#seek").value = s.position;
    /* the bar slides to where the song will be when the next answer comes (every 3 s in performance mode,
       motion.css); going back (a new song, a seek) it jumps instead of sliding backwards */
    const ahead = s.paused || !dur ? 0 : lite() ? 3 : 0, to = dur ? Math.min(1, (s.position + ahead) / dur) : 0;
    const fill = $("#fill"), was = +(fill.style.transform.match(/[\d.]+/) || [0])[0];
    if (to < was - .01) { fill.style.transition = "none"; fill.style.transform = `scaleX(${to})`; void fill.offsetWidth; fill.style.transition = ""; }
    else fill.style.transform = `scaleX(${to})`;
  }
  countBadge($("#qCount"), upcoming(s));
  document.title = c ? `${s.paused ? "❚❚" : "▶"} ${c.title} · ${house.name}` : house.name;
}

/* between answers every 3 seconds (performance mode) the time still counts each second, from the page's own clock */
setInterval(() => { if (lite() && !seeking && state.current && !state.paused) $("#tPos").textContent = fmt(position()); }, 1000);

$("#seek").addEventListener("input", () => {
  seeking = true; $("#prog").classList.add("seeking"); $("#tPos").textContent = fmt($("#seek").value);
  $("#fill").style.transform = `scaleX(${$("#seek").value / $("#seek").max})`;
});
$("#seek").addEventListener("change", async () => { await ctl("seek", +$("#seek").value); seeking = false; $("#prog").classList.remove("seeking"); });

/* ---------- swipes (touch) ---------- */
const cv = $("#canvas");
export const canvasOpen = () => cv.classList.contains("open");

/* A sideways swipe on the cover or the mini bar skips. There is nothing to pull into view, so it follows
   the finger with some give; on release a flick counts as much as the distance. A skip sends it off the
   way it was going, and the next song comes in from the other side. */
function skipper(el) {
  const sp = spring(x => { el.style.transform = x ? `translateX(${x}px)` : ""; });
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function skip(dir, v) {
    navigator.vibrate?.(10);
    const far = el.offsetWidth / 2, changed = ctl(dir < 0 ? "next" : "prev").then(poll);
    el.style.opacity = 0; sp.to(dir * far, { velocity: v });
    await Promise.all([wait(180), Promise.race([changed, wait(700)])]);
    sp.jump(-dir * far); el.style.opacity = ""; sp.to(0);
  }
  return {
    drag(dx) { sp.jump(rubberband(dx, el.offsetWidth)); },
    /* the finger lifted, dx from where it started, at vx px/s: true if that was a skip */
    release(dx, vx, cancel) {
      const far = dx + project(vx, .99);
      if (!cancel && Math.abs(far) > 70 && far * dx > 0) { skip(Math.sign(dx), vx / 2); return true; }
      sp.to(0, { velocity: vx / 2, damping: .8 });
      return false;
    },
  };
}

/* On a phone the canvas is a sheet. It follows the finger up from the mini bar and back down, and on
   release it goes where the movement was heading, open or shut, at the speed it was let go. */
const sheet = spring(y => { cv.style.transform = `translateY(${y}px)`; });
function holdSheet(y) { cv.classList.add("dragging"); cv.classList.remove("still"); sheet.jump(Math.max(0, y)); }
function dropSheet(v, cancel, was) {
  const h = cv.offsetHeight, far = sheet.value + project(v);
  /* a quarter of the way, or a flick, is enough to change it; otherwise it goes back to what it was */
  const open = cancel ? was : was ? !(v > -100 && far > h / 4) : v < 100 && far < h * 3 / 4;
  if (open !== canvasOpen()) toggleCanvas(open);
  sheet.to(open ? 0 : h, { velocity: v, then: () => { letGo(cv); settle(); } });
}

/* the song opens the canvas; on a phone the whole bar does, a sideways swipe skips and a swipe up pulls it open */
let barSwipe = null, barSwiped = 0;
const bar = $(".player .in"), now = $(".player .now"), nowSkip = skipper(now);
bar.addEventListener("click", e => {
  if (Date.now() - barSwiped < 400 || e.target.closest(".artlink")) return;
  if (e.target.closest(".now") || (phone() && !e.target.closest("button, input, .vol"))) toggleCanvas(phone() ? true : undefined);
});
bar.addEventListener("pointerdown", e => {
  if (!phone() || e.button > 0 || (e.target.closest("button, input, .vol") && !e.target.closest(".now"))) return;
  barSwipe = { x: e.clientX, y: e.clientY, id: e.pointerId, dx: 0, dy: 0, way: "", trk: tracker() };
});
addEventListener("pointermove", e => {
  if (!barSwipe || e.pointerId !== barSwipe.id) return;
  const b = barSwipe;
  b.trk.add(e); b.dx = e.clientX - b.x; b.dy = e.clientY - b.y;
  if (!b.way) {                                /* which way it goes is settled once, after the first few pixels */
    if (Math.hypot(b.dx, b.dy) < 10) return;
    b.way = Math.abs(b.dx) > Math.abs(b.dy) ? "side" : b.dy < 0 ? "up" : "none";
    if (b.way === "up") paintCanvas(true);
  }
  if (b.way === "side") nowSkip.drag(b.dx);
  else if (b.way === "up") holdSheet(cv.offsetHeight + b.dy);
});
function endBarSwipe(e, cancel) {
  if (!barSwipe || e.pointerId !== barSwipe.id) return;
  const b = barSwipe, v = b.trk.velocity(); barSwipe = null;
  if (b.way) barSwiped = Date.now();
  if (b.way === "side") nowSkip.release(b.dx, v.x, cancel);
  else if (b.way === "up") dropSheet(v.y, cancel, false);
}
addEventListener("pointerup", e => endBarSwipe(e));
addEventListener("pointercancel", e => endBarSwipe(e, true));

/* ---------- the canvas ---------- */

/* The canvas came to rest: open and not moving, the blurred cover behind it may show (canvas.css). Nothing
   here touches <body>: a class there restyles the whole page, which a phone pays for with a dropped frame. */
let settleTimer = 0;
function settle() {
  clearTimeout(settleTimer);
  cv.classList.toggle("still", canvasOpen() && !cv.classList.contains("dragging"));
}
cv.addEventListener("transitionend", e => { if (e.target === cv) settle(); });

export function toggleCanvas(open = !canvasOpen()) {
  if (open === canvasOpen()) return;
  /* under a finger (or its spring) it was placed and painted when the swipe began, and settles when the spring lands */
  const moving = cv.classList.contains("dragging");
  cv.classList.remove("still");
  clearTimeout(settleTimer);
  if (!moving) settleTimer = setTimeout(settle, 700);   /* no transition to end (performance mode) */
  cv.classList.toggle("open", open); cv.setAttribute("aria-hidden", !open);
  /* a desktop's wheel and keys would scroll the page behind it; a phone's canvas takes every touch, and
     there the class (which restyles the whole page) would cost a frame mid-swipe */
  if (!phone()) document.body.classList.toggle("canvas-open", open);
  if (open) { if (!moving) paintCanvas(true); history.pushState({ canvas: 1 }, ""); }   /* Back (Android) closes it */
  else if (history.state?.canvas) history.back();
  syncLyrBtn();
}
addEventListener("popstate", () => { if (canvasOpen()) { cv.classList.remove("open", "still"); document.body.classList.remove("canvas-open"); } });

let lyrOn = store.get("tb_clyr", "0") === "1", cSeeking = false, lyrVid = null;
const lyrBox = $("#cLyr"), follow = follower(lyrBox, 0.4, true);

export function toggleCanvasLyrics(open = !lyrOn) { if (!feat("lyrics")) return; lyrOn = open; store.set("tb_clyr", lyrOn ? "1" : "0"); paintCanvas(true); syncLyrBtn(); }

/* On a desktop with the canvas open, every Lyrics button (the canvas's and the bar's, and L) shows the
   canvas's own lyrics beside the cover; otherwise they open the Lyrics drawer */
export const canvasLyrics = () => canvasOpen() && !phone();
export function syncLyrBtn() { $("#lyrBtn").classList.toggle("on", canvasLyrics() ? lyrOn : $("#lyrics").classList.contains("open")); }

setupWallpaper($("#cWp"), $("#cGrain"));   /* the wall's, behind the canvas */

export function paintCanvas(force) {
  if (!canvasOpen() && !force) return;         /* forced while still shut: it is being pulled open */
  const s = state, c = s.current;
  if ((c ? cover(c) : "") !== $("#cImg").dataset.src) {
    if (c) { showCover($("#cImg"), c); wallpaperFor(c); }
    else { $("#cImg").dataset.src = ""; $("#cImg")._want = ""; $("#cImg").removeAttribute("src"); }
    if (canvasOpen()) swapIn($("#cTitle"), $("#cSub"));
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
const art = $("#cImg"), artSkip = skipper(art);
cv.addEventListener("pointerdown", e => {
  if (e.pointerType === "mouse" || e.target.closest("input, .clyr")) return;
  cDrag = { y: e.clientY, x: e.clientX, id: e.pointerId, dx: 0, base: 0, on: false, side: false, art: e.target === art, was: canvasOpen(), trk: tracker() };
  if (sheet.moving) { cDrag.on = true; cDrag.base = sheet.value; holdSheet(sheet.value); }   /* caught on its way: it goes on from where it is */
});
addEventListener("pointermove", e => {
  if (!cDrag || e.pointerId !== cDrag.id) return;
  const dy = e.clientY - cDrag.y, dx = e.clientX - cDrag.x;
  cDrag.trk.add(e);
  if (!cDrag.on && !cDrag.side && cDrag.art && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) cDrag.side = true;
  if (cDrag.side) { cDrag.dx = dx; artSkip.drag(dx); return; }
  if (!cDrag.on && dy > 10 && dy > Math.abs(dx)) { cDrag.on = true; cDrag.y = e.clientY; holdSheet(0); return; }
  if (cDrag.on) holdSheet(cDrag.base + dy);
});
function endCanvasDrag(e, cancel) {
  if (!cDrag || e.pointerId !== cDrag.id) return;
  const d = cDrag, v = d.trk.velocity(); cDrag = null;
  if (d.side) { artSwiped = Date.now(); artSkip.release(d.dx, v.x, cancel); return; }
  if (d.on) dropSheet(v.y, cancel, d.was);
}
addEventListener("pointerup", e => endCanvasDrag(e));
addEventListener("pointercancel", e => endCanvasDrag(e, true));

on("canvas-close", () => toggleCanvas(false));
on("canvas-lyrics", () => toggleCanvasLyrics());
/* the cover was just swiped: the tap that ends the swipe isn't one */
export const coverSwiped = () => Date.now() - artSwiped < 400;
