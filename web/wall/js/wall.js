/* The wall screen: a tablet or TV showing what plays (cover, synced lyrics, big controls).
   Idle (nothing playing, or paused a while): a dimmed clock; a tap wakes it for half a minute.
   The admin picks what it shows (house.wall): lyrics, the next songs, who added the song, the clock,
   the buttons. */
import { $, $$, esc, fmt, secs, cssUrl } from "../../shared/dom.js";
import { state, onState, startPolling, setToaster, ctl, setVolume, position, poll } from "../../shared/playback.js";
import { setupLikes, syncLikes, likeCurrent } from "../../shared/likes.js";
import { fetchLyrics, activeLine, syncedHtml, plainHtml } from "../../shared/lyrics.js";
import { people, syncPeople } from "../../shared/people.js";
import { house, fresh, feat, syncAdmin, syncHouse, onHouse } from "../../shared/house.js";
import { on } from "../../shared/actions.js";

const ICON_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
const IDLE_AFTER = 120, AWAKE_FOR = 30;        /* paused this long counts as idle; a tap keeps it awake this long */

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

/* ---------- lyrics: the line being sung sits a third of the way down ---------- */
let lyr = { vid: null, lines: null }, lyrActive = -1;
async function loadLyrics(c) {
  lyr = { vid: c.videoId, lines: null }; lyrActive = -1;
  $("#lyr").hidden = true; $("#stage").classList.add("nolyrics");
  if (!house.wall.lyrics || !feat("lyrics")) return;
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
  lyrTick(true);
}
function lyrTick(force) {
  if (!lyr.lines) return;
  const a = activeLine(lyr.lines, position());
  if (a === lyrActive && !force) return;
  lyrActive = a;
  $$("#lyrIn p[data-i]").forEach(p => { const i = +p.dataset.i; p.classList.toggle("on", i === a); p.classList.toggle("past", i < a); });
  const el = $(`#lyrIn p[data-i="${Math.max(a, 0)}"]`);
  if (el) $("#lyrIn").style.transform = `translateY(${$("#lyr").clientHeight * 0.36 - el.offsetTop}px)`;
}
setInterval(lyrTick, 200);

/* ---------- idle clock, or what plays ---------- */
function isIdle() {
  if (Date.now() - touched < AWAKE_FOR * 1000 && state.current) return false;
  if (!state.current || (state.idle && !state.loading && !state.paused)) return true;
  return state.paused && pausedSince && Date.now() - pausedSince > IDLE_AFTER * 1000;
}
function render() {
  document.body.classList.toggle("idle", !!isIdle());
  const now = new Date();
  $("#time").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("#date").textContent = now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  $("#idleNote").textContent = state.current && state.paused ? `Paused · ${state.current.title}` : "";
}
setInterval(render, 1000);                     /* the clock keeps going even when the server doesn't answer */

/* the house's setup: the wall's options, its name; a wall that was switched off goes to the player */
function applyHouse() {
  if (fresh && !feat("wall")) return location.replace("./");   /* switched off while it was open (else the server wouldn't have sent it) */
  document.title = `${house.name} wall`;
  document.body.classList.toggle("noctrls", !house.wall.controls);
  document.body.classList.toggle("noclock", !house.wall.clock);
  $("#likeBtn").hidden = !feat("likes");
  lyr.vid = null;                              /* the next poll shows or drops the lyrics */
}
onHouse(applyHouse);
applyHouse();

onState(s => {
  if (s.paused) pausedSince = pausedSince || Date.now(); else pausedSince = null;
  const c = s.current;
  if (c) {
    if ($("#cover").dataset.src !== c.thumb) { $("#cover").src = c.thumb; $("#cover").dataset.src = c.thumb; $("#bg").style.backgroundImage = cssUrl(c.thumb || ""); }
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
  $("#fill").style.width = dur ? `${Math.min(100, s.position / dur * 100)}%` : "0";
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

/* a tap on the idle screen only wakes it: the button under the finger must not fire */
let wokeAt = 0;
addEventListener("pointerdown", () => { if (document.body.classList.contains("idle")) wokeAt = Date.now(); touch(); keepAwake(); }, true);
addEventListener("click", e => { if (Date.now() - wokeAt < 800) { e.stopPropagation(); e.preventDefault(); } }, true);

startPolling();
keepAwake();
