/* The wall screen: a tablet or TV showing what plays (cover, synced lyrics, big controls).
   Idle (nothing playing, or paused a while): a dimmed clock; a tap wakes it for half a minute.
   The admin picks what it shows (house.wall): lyrics, the next songs, who added the song, the clock,
   the buttons. */
import { $, $$, esc, fmt, secs, art, showCover, swapIn } from "../../shared/dom.js";
import { state, onState, startPolling, setToaster, ctl, setVolume, position, poll, queueSongs } from "../../shared/playback.js";
import { setupLikes, syncLikes, likeCurrent } from "../../shared/likes.js";
import { fetchLyrics, activeLine, syncedHtml, plainHtml } from "../../shared/lyrics.js";
import { people, syncPeople } from "../../shared/people.js";
import { house, fresh, feat, syncAdmin, syncHouse, onHouse } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { api, errText } from "../../shared/api.js";
import { store } from "../../shared/device.js";
import { setupWallpaper, wallpaperFor } from "../../shared/wallpaper.js";
import "../../shared/motion.js";              /* for its touch listener: a press shows on iOS too */

const ICON_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
const IDLE_AFTER = 30, AWAKE_FOR = 30;         /* paused this long counts as idle; a tap keeps it awake this long */

let pausedSince = null, touched = 0, volTouch = 0, msgT;

/* a short message at the bottom of the screen */
function say(t) { $("#msg").textContent = t; clearTimeout(msgT); msgT = setTimeout(() => $("#msg").textContent = "", 2500); }
setToaster(say);
setupLikes(say);

function touch() { touched = Date.now(); render(); }

function nudge(d) {
  touch(); volTouch = Date.now();
  state.volume = setVolume((state.volume || 0) + d);
  $("#vol").textContent = state.volume;
  poll();
}

/* the full screen button says which way it goes */
document.addEventListener("fullscreenchange", () => { $("#fsBtn").title = $("#fsBtn").ariaLabel = document.fullscreenElement ? "Exit full screen" : "Full screen"; });
function fullscreen() {
  const d = document.documentElement;
  (document.fullscreenElement ? document.exitFullscreen() : d.requestFullscreen?.())?.catch?.(() => {});
}

/* keep the screen on where the browser allows it (needs https or localhost) */
let lock = null;
async function keepAwake() {
  try {
    if (!lock && document.visibilityState === "visible") { lock = await navigator.wakeLock.request("screen"); lock.addEventListener("release", () => lock = null); }
  } catch {}
}
document.addEventListener("visibilitychange", keepAwake);

/* ---------- the wallpaper (shared/wallpaper.js) ---------- */
setupWallpaper($("#wp"), $("#grain"));


/* ---------- lyrics: the line being sung sits a third of the way down ----------
   They scroll: someone scrolling (a finger, the wheel) has them to themselves until 5 s after they stop;
   a tap on a line plays from there and the lines follow again at once. */
let lyr = { vid: null, lines: null }, lyrActive = -1, lyrScrolled = 0;
let lyrOff = store.get("tb_wall_lyrics", "") === "off";   /* this wall's own choice (the corner button) */
async function loadLyrics(c) {
  lyr = { vid: c.videoId, lines: null }; lyrActive = -1;
  $("#lyr").hidden = true; $("#stage").classList.add("nolyrics");
  if (!house.wall.lyrics || !feat("lyrics") || lyrOff) return;
  const d = await fetchLyrics(c);
  if (lyr.vid !== c.videoId || d.none || d.instrumental) return;
  if (d.synced) {
    lyr.lines = d.synced;
    $("#lyrIn").innerHTML = syncedHtml(d.synced);
    $("#lyr").className = "lyr";
  } else {
    $("#lyrIn").innerHTML = plainHtml(d.plain);
    $("#lyr").className = "lyr plain";
  }
  $("#lyr").hidden = false; $("#stage").classList.remove("nolyrics");
  $("#lyr").scrollTop = 0; lyrScrolled = 0;
  lyrTick(true);
}
function lyrTick(force) {
  if (!lyr.lines) return;
  const a = activeLine(lyr.lines, position());
  if (a === lyrActive && !force) return;
  lyrActive = a;
  $$("#lyrIn p[data-i]").forEach(p => { const i = +p.dataset.i; p.classList.toggle("on", i === a); p.classList.toggle("past", i < a); });
  follow(force ? "auto" : "smooth");
}
function follow(how = "smooth") {
  const el = $(`#lyrIn p[data-i="${Math.max(lyrActive, 0)}"]`);
  if (el && Date.now() - lyrScrolled > 5000)
    $("#lyr").scrollTo({ top: $("#lyrIn").offsetTop + el.offsetTop - $("#lyr").clientHeight * 0.36, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : how });
}
setInterval(() => { const was = lyrScrolled; lyrTick(); if (was && Date.now() - was > 5000) { lyrScrolled = 0; follow(); } }, 200);
for (const ev of ["wheel", "touchmove"]) $("#lyr").addEventListener(ev, () => { lyrScrolled = Date.now(); touch(); }, { passive: true });
/* a tap on a synced line plays from there (when the wall has controls) */
$("#lyr").addEventListener("click", e => {
  const p = e.target.closest("p[data-t]");
  if (p && house.wall.controls) { touch(); lyrScrolled = 0; ctl("seek", +p.dataset.t); }
});

/* ---------- idle clock, or what plays ---------- */
/* Night (house.wall.night, "23:00-07:00"): the dimmed clock with the song under it, even while it plays */
function isNight() {
  const m = /^(\d\d):(\d\d)-(\d\d):(\d\d)$/.exec(house.wall.night || "");
  if (!m) return false;
  const d = new Date(), now = d.getHours() * 60 + d.getMinutes(), from = +m[1] * 60 + +m[2], to = +m[3] * 60 + +m[4];
  return from <= to ? now >= from && now < to : now >= from || now < to;
}
function isIdle() {
  if (!$("#find").hidden) return false;        /* someone is adding songs */
  if (Date.now() - touched < AWAKE_FOR * 1000 && state.current) return false;
  if (isNight()) return true;
  if (!state.current || (state.idle && !state.loading && !state.paused)) return true;
  return state.paused && pausedSince && Date.now() - pausedSince > IDLE_AFTER * 1000;
}
function render() {
  document.body.classList.toggle("idle", !!isIdle());
  document.body.classList.toggle("night", isNight());
  const now = new Date();
  $("#time").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("#date").textContent = now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  const c = state.current;
  $("#idleNote").textContent = !c ? "" : state.paused ? `Paused · ${c.title}` : isNight() ? [c.title, c.artist].filter(Boolean).join(" · ") : "";
}
setInterval(render, 1000);                     /* the clock keeps going even when the server doesn't answer */

/* An OLED TV left on all day keeps whatever never moves: everything drifts a few pixels every two minutes */
function shift() {
  const r = () => Math.round(Math.random() * 20 - 10);
  document.documentElement.style.setProperty("--sx", r() + "px");
  document.documentElement.style.setProperty("--sy", r() + "px");
}
setInterval(shift, 120000);

/* The join code: a QR code of the page's own address (the wall is opened the way phones reach it), so a
   guest scans it instead of typing an IP. A wall on the server itself (localhost) asks for the server's
   address on the network instead. */
let lanUrl = "";
async function joinCode() {
  let url = new URL(".", location.href);
  if (/^(localhost|127\.|\[::1\])/.test(location.hostname)) {
    if (!lanUrl) { const n = await api("api/network").catch(() => null); if (n?.ip) { url.hostname = n.ip; lanUrl = url.href; } }
    url = lanUrl;
  } else url = url.href;
  $("#join").hidden = $("#fjoin").hidden = !(house.wall.qr ?? true) || !url || typeof qrcode !== "function";
  if ($("#join").hidden || $("#qr").dataset.url === url) return;
  const q = qrcode(0, "M");
  q.addData(url); q.make();
  $("#qr").innerHTML = $("#fqr").innerHTML = q.createSvgTag({ scalable: true, margin: 0 });
  $("#qr").dataset.url = url;
}

/* the house's setup: the wall's options, its name; a wall that was switched off goes to the player */
function applyHouse() {
  if (fresh && !feat("wall")) return location.replace("./");   /* switched off while it was open (else the server wouldn't have sent it) */
  document.title = `${house.name} wall`;
  document.body.classList.toggle("noctrls", !house.wall.controls);
  document.body.classList.toggle("noclock", !house.wall.clock);
  document.body.classList.toggle("nolyricsfeat", !house.wall.lyrics || !feat("lyrics"));
  $("#likeBtn").hidden = !feat("likes");
  joinCode();
  lyr.vid = null;                              /* the next poll shows or drops the lyrics */
}
onHouse(applyHouse);
applyHouse();

onState(s => {
  if (s.paused) pausedSince = pausedSince || Date.now(); else pausedSince = null;
  const c = s.current;
  if (c) {
    if ($("#cover").dataset.src !== art(c)) {
      if ($("#cover").dataset.src) swapIn($("#title"), $("#artist"));   /* not on the first song shown */
      showCover($("#cover"), c); wallpaperFor(c);
    }
    $("#title").textContent = c.title; $("#artist").textContent = [c.artist, c.album].filter(Boolean).join(" · ");
    if (lyr.vid !== c.videoId) loadLyrics(c);
  }
  syncAdmin(s.admin); syncHouse(s.houseRev);
  const w = house.wall, now = (s.queue || [])[0], next = c && w.queue ? (s.queue || []).slice(1, 4) : [];
  const by = !c || !now || !w.who || !feat("people") ? "" : now.src !== "user" ? "From the radio" : people[now.by] ? `Added by ${people[now.by].name}` : "";
  if (w.who) syncPeople(s.peopleRev);
  $("#by").textContent = by; $("#by").hidden = !by;
  $("#next").innerHTML = "<b>Up next</b>" + next.map(t => `<span>${esc(t.title)} <i>${esc(t.artist)}</i></span>`).join(""); $("#next").hidden = !next.length;
  $("#playBtn").innerHTML = s.paused || !c ? ICON_PLAY : ICON_PAUSE;
  const dur = s.duration || secs(c?.duration);   /* restored paused after a restart: mpv has no length yet */
  $("#fill").style.transform = `scaleX(${dur ? Math.min(1, s.position / dur) : 0})`;
  $("#pos").textContent = fmt(s.position); $("#dur").textContent = fmt(dur);
  if (Date.now() - volTouch > 2000) $("#vol").textContent = Math.round(s.volume ?? 0);
  syncLikes(s.listsRev);
  render();
});

/* ---------- controls ---------- */
for (const a of ["prev", "toggle", "next"]) on(a, () => { touch(); ctl(a); });
on("volume", el => nudge(+el.dataset.d));
on("like", () => { touch(); likeCurrent(); });
on("fullscreen", fullscreen);
on("lyrics-toggle", () => {
  touch();
  lyrOff = !lyrOff;
  store.set("tb_wall_lyrics", lyrOff ? "off" : "");
  $("#lyrBtn").classList.toggle("hidden-lyrics", lyrOff);
  lyr.vid = null; poll();                      /* the next answer shows them again, or leaves them out */
});
$("#lyrBtn").classList.toggle("hidden-lyrics", lyrOff);
/* Leaving the wall takes 4 presses within 2 seconds of each other, the button counting down, so a
   guest's stray tap (or a child's) doesn't take the screen away */
let exitLeft = 4, exitT;
on("exit", () => {
  touch(); clearTimeout(exitT);
  if (--exitLeft <= 0) return location.assign("./");
  $("#exitBtn").classList.add("counting"); $("#exitBtn b").textContent = exitLeft;
  exitT = setTimeout(() => { exitLeft = 4; $("#exitBtn").classList.remove("counting"); }, 2000);
});

/* ---------- gestures on the cover, when the wall has controls: tap the left half for the previous song,
   the right half for the next, double-tap to like, drag up or down for the volume ---------- */
const ICON = {
  prev: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 4h3v16H5zM20 4v16L9 12z"/></svg>',
  next: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 4h3v16h-3zM4 4v16l11-8z"/></svg>',
  like: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.4a4.2 4.2 0 0 1 7.5 2.4C19.5 15.4 12 20 12 20z"/></svg>',
};
function hint(kind, text, hold = false) {
  const h = $("#hint");
  h.className = "hint " + (kind === "prev" ? "l" : kind === "next" ? "r" : "c");
  h.innerHTML = text ?? ICON[kind];
  if (hold) h.classList.add("hold"); else { void h.offsetWidth; h.classList.add("go"); }
}
let g = null, lastTap = 0, tapT, volT = null, volWant = null;
function slideVolume(v) {                      /* at most one request every 80 ms while dragging */
  volWant = v; touch(); volTouch = Date.now();
  state.volume = v; $("#vol").textContent = v; hint("vol", v, true);
  volT ??= setTimeout(() => { volT = null; setVolume(volWant); }, 80);
}
$("#art").addEventListener("pointerdown", e => {
  if (!house.wall.controls || document.body.classList.contains("idle")) return;
  g = { x: e.clientX, y: e.clientY, v: Math.round(state.volume || 0), id: e.pointerId, moved: false };
  $("#art").setPointerCapture(e.pointerId);
});
$("#art").addEventListener("pointermove", e => {
  if (!g || e.pointerId !== g.id) return;
  const dy = g.y - e.clientY;
  if (!g.moved && Math.abs(dy) > 12) g.moved = true;
  if (g.moved) {
    const v = Math.max(0, Math.min(100, Math.round(g.v + dy / $("#art").clientHeight * 100)));
    if (v !== state.volume) slideVolume(v);
  }
});
$("#art").addEventListener("pointerup", e => {
  if (!g || e.pointerId !== g.id) return;
  const was = g;
  g = null;
  if (was.moved) { hint("vol", Math.round(state.volume)); return; }
  if (Math.abs(e.clientX - was.x) > 16) return;
  const r = $("#art").getBoundingClientRect(), side = e.clientX < r.left + r.width / 2 ? "prev" : "next";
  if (Date.now() - lastTap < 300) {                  /* the second tap of a double-tap: like, and no skip */
    clearTimeout(tapT); lastTap = 0;
    if (feat("likes")) { touch(); likeCurrent(); hint("like"); }
    return;
  }
  lastTap = Date.now();
  tapT = setTimeout(() => { touch(); ctl(side); hint(side); }, 300);
});
$("#art").addEventListener("pointercancel", () => { g = null; });

/* ---------- adding songs from the wall: a search over everything, rows big enough for a finger ----------
   The wall's songs are nobody's: no name is asked, they count for no one, and they take their turn as
   one more of the house's. The house counts how many were added here (Stats). */
let found = [], findT = null, findSeq = 0;
function openFind() {
  touch();
  $("#find").hidden = false; $("#fq").value = ""; found = []; $("#fres").innerHTML = "";
  $("#fwho").textContent = feat("people") ? "Songs added here are the house's, not anyone's." : "";
  setTimeout(() => $("#fq").focus(), 50);
}
function closeFind() { $("#find").hidden = true; $("#fq").blur(); }
async function find() {
  const q = $("#fq").value.trim(), my = ++findSeq;
  if (!q) { found = []; $("#fres").innerHTML = ""; return; }
  $("#fres").innerHTML = '<p class="fnote">Searching…</p>';
  try {
    const res = await api(`api/search?q=${encodeURIComponent(q)}&kind=songs`);
    if (my !== findSeq) return;
    found = res;
    $("#fres").innerHTML = res.length ? res.map((t, i) => `<div class="frow"><img src="${esc(art(t))}" alt="">
      <div class="min0"><div class="t">${esc(t.title)}</div><div class="s">${esc([t.artist, t.duration].filter(Boolean).join(" · "))}</div></div>
      <button data-act="find-add" data-i="${i}" data-mode="next">Play next</button><button class="add" data-act="find-add" data-i="${i}" data-mode="add">Add</button></div>`).join("")
      : '<p class="fnote">Nothing found</p>';
  } catch (e) { if (my === findSeq) $("#fres").innerHTML = `<p class="fnote">${esc(errText(e))}</p>`; }
}
on("find-open", openFind);
on("find-close", closeFind);
on("find-add", async el => {
  touch();
  const t = found[+el.dataset.i];
  if (!t) return;
  await queueSongs([t], el.dataset.mode, "", true);
  el.closest(".frow").classList.add("done");
});
$("#fq").addEventListener("input", () => { touch(); clearTimeout(findT); findT = setTimeout(find, 450); });
$("#fq").addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(findT); find(); $("#fq").blur(); } if (e.key === "Escape") closeFind(); });

/* a tap on the idle screen only wakes it: the button under the finger must not fire */
let wokeAt = 0;
addEventListener("pointerdown", () => { if (document.body.classList.contains("idle")) wokeAt = Date.now(); touch(); keepAwake(); }, true);
addEventListener("click", e => { if (Date.now() - wokeAt < 800) { e.stopPropagation(); e.preventDefault(); } }, true);

startPolling();
keepAwake();
