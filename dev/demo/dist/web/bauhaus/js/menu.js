/* Right-click menus (a long press on touch): every song, album, playlist and artist has one, the
   player and the canvas have one for the song playing now, and anywhere else gets the player's own.
   Shift + right-click, and fields you type in, keep the browser's menu. On a phone the menu is a sheet
   at the bottom. The Up next drawer uses a long press to drag, so on touch it keeps its swipes instead. */
import { $, $$, esc, plural, art } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { state, lists, ctl, queueSongs, undo, poll } from "../../shared/playback.js";
import { isLiked, toggleLike } from "../../shared/likes.js";
import { admin, feat } from "../../shared/house.js";
import { people } from "../../shared/people.js";
import { toast, openDrawer, dragAway } from "./ui.js";
import { askPlay } from "./ask.js";
import { openItem, goTo } from "./library.js";
import { showList, pickFor, removeFromList } from "./playlists.js";
import { toggleQueue } from "./queue.js";
import { toggleLyrics } from "./lyrics.js";
import { toggleSettings } from "./settings.js";
import { toggleCanvas, phone } from "./player.js";
import { block } from "./admin-house.js";

const box = $("#ctx"), back = $("#ctxBack");
let items = [];

/* ---------- what's under the pointer, and its menu ---------- */
/* Item: {label, run, hint?, danger?}; SEP draws a line between groups; anything falsy is left out. */
const SEP = "-";

export function copyText(text, said = "Link copied") {
  const done = () => toast(said);
  if (navigator.clipboard && isSecureContext) return navigator.clipboard.writeText(text).then(done, () => toast("Couldn't copy"));
  const ta = document.createElement("textarea");       /* plain http on the LAN has no clipboard API */
  ta.value = text; ta.style.cssText = "position:fixed;opacity:0"; document.body.append(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch { toast("Couldn't copy"); }
  ta.remove();
}

/* The songs the house left out of the radio (anyone may; the admin's Blocked list shows them), so the
   menu can offer the way back. Fetched once, and again after every change from here. */
let radioOff = new Set();
const syncRadioOff = () => api("api/radio/skips").then(ls => { radioOff = new Set(ls.map(x => x.videoId)); }).catch(() => {});
syncRadioOff();
async function toggleRadio(t) {
  try {
    const r = radioOff.has(t.videoId) ? await api(`api/radio/skips/${encodeURIComponent(t.videoId)}`, undefined, "DELETE")
      : await api("api/radio/skips", { track: t });
    toast(r.message);
  } catch (e) { toast(errText(e), false, "error"); }
  syncRadioOff(); poll();
}

/* the "about this song" part every song menu ends with; while the admin is unlocked, blocking too.
   A local song has no artist or album page and no link: it has its place on the Local page. */
const isLocal = t => String(t.videoId).startsWith("local:");
const songTail = t => [
  feat("playlists") && { label: "Add to playlist…", run: () => pickFor(t) },
  feat("likes") && { label: isLiked(t.videoId) ? "Unlike" : "Like", run: () => toggleLike(t) },
  feat("radio") && { label: radioOff.has(t.videoId) ? "Back on the radio" : "Not for the radio", run: () => toggleRadio(t) },
  SEP,
  !isLocal(t) && t.artist && { label: "Go to artist", hint: t.artist.split(",")[0], run: () => goTo("artist", t) },
  !isLocal(t) && t.album && { label: "Go to album", hint: t.album, run: () => goTo("album", t) },
  isLocal(t) ? feat("local") && { label: "Show in Local songs", run: () => goTo("local", t) }
    : { label: "Copy link", run: () => copyText(`https://music.youtube.com/watch?v=${t.videoId}`) },
  admin && SEP,
  admin && { label: "Block this song", danger: true, run: () => block({ kind: "song", track: t }) },
  admin && t.artist && { label: "Block the artist", hint: t.artist.split(",")[0], danger: true, run: () => block({ kind: "artist", track: t }) },
];

/* with something on, playing asks first (ask.js) */
const playNow = run => state.current ? { label: "Interrupt", hint: "play now", run } : { label: "Play", run };

function songMenu(t, extra = []) {
  return [
    playNow(() => askPlay([t])),
    { label: "Play next", run: () => queueSongs([t], "next") },
    { label: "Add to the end of the queue", run: () => queueSongs([t], "add") },
    ...extra, SEP, ...songTail(t),
  ];
}

function nowMenu() {
  const t = state.current;
  const base = [
    { label: state.paused || !t ? "Play" : "Pause", hint: "Space", run: () => ctl("toggle") },
    { label: "Next", hint: "Shift+→", run: () => ctl("next") },
    { label: "Previous", hint: "Shift+←", run: () => ctl("prev") },
  ];
  if (!t) return base;
  return [...base, SEP, feat("lyrics") && { label: "Lyrics", hint: "L", run: () => toggleLyrics(true) }, ...songTail(t)];
}

/* the whole player, for anywhere that isn't a song or a list */
function playerMenu() {
  return [
    ...nowMenu().slice(0, 3), SEP,
    { label: "Up next", hint: "Q", run: () => toggleQueue(true) },
    feat("lyrics") && { label: "Lyrics", hint: "L", run: () => toggleLyrics(true) },
    state.current && { label: "Now playing", hint: "N", run: () => toggleCanvas(true) },
    { label: "Settings", hint: "S", run: () => toggleSettings(true) },
    SEP,
    state.undo && { label: `Undo: ${state.undo.label}`, hint: "Z", run: undo },
    { label: "Search", hint: "/", run: () => $("#q").focus() },
    { label: "Keyboard shortcuts", hint: "?", run: () => openDrawer("keys", true) },
  ];
}

/* an album, playlist or artist (from YouTube), or one of the house's playlists: fetch its songs first */
function collectionMenu(label, load, open) {
  const withSongs = fn => async () => {
    let tracks;
    try { tracks = await load(); } catch (e) { return toast(errText(e), false, "error"); }
    if (!tracks.length) return toast("Nothing to play in there");
    fn(tracks);
  };
  return [
    open && { label: "Open", run: open },
    open && SEP,
    playNow(withSongs(t => askPlay(t, label))),
    { label: "Play next", run: withSongs(t => queueSongs(t, "next", label)) },
    { label: "Add to the end of the queue", run: withSongs(t => queueSongs(t, "add", label)) },
  ];
}

/* a song in the Up next drawer: row i of state.queue */
function queueMenu(i) {
  const t = state.queue[i], at = (state.offset || 0) + i;
  if (!i) return nowMenu();
  return [
    { label: "Play now", run: () => ctl("jump", at, t.videoId) },
    { label: "Play next", run: () => ctl("promote", at, t.videoId) },
    { label: "Remove from the queue", danger: true, run: () => ctl("remove", at, t.videoId) },
    SEP, ...songTail(t),
  ];
}

/* The menu for whatever el is (or sits in). Returns [head, items]; head is {thumb, title, sub} or null. */
function menuFor(el) {
  const songHead = t => ({ thumb: art(t), title: t.title, sub: [t.artist, t.album].filter(Boolean).join(" · "), vid: t.videoId });

  const qrow = el.closest("#queue .row");
  if (qrow) {
    const src = qrow.querySelector('[data-list="queue"][data-i]');
    const i = src ? +src.dataset.i : -1;
    if (i >= 0 && state.queue?.[i]) return [songHead(state.queue[i]), queueMenu(i)];
  }
  const holder = el.closest(".row, .card, .hero, .player .now, .cmain img, .cinfo, #lyrics, .clyr");
  if (holder?.matches(".player .now, .cmain img, .cinfo, #lyrics, .clyr")) {
    return [state.current ? songHead(state.current) : null, nowMenu()];
  }
  if (holder?.matches(".row, .card")) {
    const src = holder.matches("[data-list][data-i]") ? holder : holder.querySelector("[data-list][data-i]");
    const t = src && lists[src.dataset.list]?.[+src.dataset.i];
    if (t) {
      const extra = src.dataset.list === "mine" ? [{ label: "Remove from this playlist", danger: true, run: () => removeFromList(+src.dataset.i) }] : [];
      return [songHead(t), songMenu(t, extra)];
    }
    if (holder.dataset.act === "add-track") { const t = JSON.parse(holder.dataset.track); return [songHead(t), songMenu(t)]; }
    const title = holder.querySelector(".t")?.textContent || "";
    const head = { thumb: holder.querySelector("img")?.src, title, sub: holder.querySelector(".s")?.textContent || "" };
    if (holder.dataset.act === "open") {
      const { type, id } = holder.dataset;
      return [head, collectionMenu(title, async () => (await api(`api/${type}/${encodeURIComponent(id)}`)).tracks, () => openItem(type, id))];
    }
    if (holder.dataset.act === "list-open") {
      const id = holder.dataset.id;
      return [head, collectionMenu(title, async () => (await api(`api/lists/${id}`)).tracks, () => showList(id))];
    }
  }
  const all = holder?.matches(".hero") && holder.querySelector('[data-act="play-all"]');
  if (all) {                                          /* the top of an album / playlist / artist page */
    const key = all.dataset.list, head = { thumb: holder.querySelector("img")?.src, title: all.dataset.label, sub: plural(lists[key].length, "song") };
    return [head, collectionMenu(all.dataset.label, async () => lists[key], null)];
  }
  return [null, playerMenu()];
}

/* ---------- showing it ---------- */
const menuOpen = () => box.classList.contains("open");

function render(head, list) {
  items = list.filter(Boolean).filter((x, k, a) => !(x === SEP && (!k || a[k - 1] === SEP)));
  while (items.length && items[items.length - 1] === SEP) items.pop();
  box.innerHTML = (head ? `<div class="chead">${head.thumb ? `<img src="${esc(head.thumb)}" alt="">` : ""}<div class="min0">
      <div class="t">${esc(head.title)}</div>${head.sub ? `<div class="s">${esc(head.sub)}</div>` : ""}</div></div>` : "")
    + items.map((x, k) => x === SEP ? '<hr>' : `<button role="menuitem" data-k="${k}"${x.danger ? ' class="danger"' : ""}>
      <span>${esc(x.label)}</span>${x.hint ? `<em>${esc(x.hint)}</em>` : ""}</button>`).join("");
}

function openMenu(el, x, y) {
  const [head, list] = menuFor(el), sheet = phone();
  render(sheet ? head : null, list);               /* on a desktop the menu sits on the thing itself: no header */
  box.classList.toggle("sheet", sheet);
  box.style.left = box.style.top = box.style.transformOrigin = "";
  /* measured while still closed (its size, not its rectangle: closed, it is scaled down), so it opens from there */
  if (sheet) box.classList.toggle("fits", box.scrollHeight <= box.clientHeight);
  else {
    const w = box.offsetWidth, h = box.offsetHeight, m = 8;
    const left = Math.max(m, Math.min(x, innerWidth - w - m)), top = Math.max(m, y + h > innerHeight - m ? y - h : y);
    box.style.left = left + "px"; box.style.top = top + "px";
    box.style.transformOrigin = `${x - left}px ${y - top}px`;   /* it grows out of the spot that was clicked */
  }
  box.classList.add("open"); back.classList.add("open");
  box.querySelector("button")?.focus({ preventScroll: true });
  if (head?.vid && feat("stats")) songInfo(head.vid);
}

/* A song's own numbers, under the menu's header: "Played 12 times · first on 3 March 2025 · mostly Ana's" */
async function songInfo(vid) {
  const line = Object.assign(document.createElement("div"), { className: "cinfo", textContent: "…" });
  const at = box.querySelector(".chead");
  at ? at.after(line) : box.prepend(line);
  let d;
  try { d = await api(`api/stats/song/${encodeURIComponent(vid)}`); } catch { return line.remove(); }
  if (!line.isConnected) return;
  const day = t => new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
  line.textContent = !d.plays ? "Not played here yet"
    : [`Played ${d.plays === 1 ? "once" : d.plays + " times"}`, `first on ${day(d.first)}`,
       people[d.by] ? `mostly ${people[d.by].name}'s` : d.radio === d.plays ? "always from the radio" : ""].filter(Boolean).join(" · ");
}
/* the phone's sheet can be dragged back down, when it has nothing to scroll */
dragAway(box, { axis: "y", when: () => box.matches(".sheet.fits"), close: () => closeMenu(), dim: () => back });

function closeMenu() {
  box.classList.remove("open"); back.classList.remove("open");
}

box.addEventListener("click", e => {
  const b = e.target.closest("button[data-k]");
  if (!b) return;
  const item = items[+b.dataset.k];
  closeMenu();
  item?.run();
});
back.addEventListener("pointerdown", e => { e.preventDefault(); closeMenu(); });
addEventListener("resize", () => menuOpen() && !phone() && closeMenu());
addEventListener("blur", () => menuOpen() && !phone() && closeMenu());
addEventListener("wheel", e => menuOpen() && !phone() && !e.target.closest("#ctx") && closeMenu(), { passive: true });

/* arrows move, Enter picks, Esc closes (before the page's own shortcuts see the key) */
document.addEventListener("keydown", e => {
  if (!menuOpen()) return;
  const bs = $$("#ctx button"), k = bs.indexOf(document.activeElement);
  const go = d => bs[(k + d + bs.length) % bs.length]?.focus();
  const keys = { Escape: closeMenu, ArrowDown: () => go(1), ArrowUp: () => go(-1), Home: () => bs[0]?.focus(), End: () => bs.at(-1)?.focus(),
    Tab: () => go(e.shiftKey ? -1 : 1) };
  if (keys[e.key]) { e.preventDefault(); e.stopPropagation(); keys[e.key](); }
  else if (e.key !== "Enter" && e.key !== " ") { e.stopPropagation(); }
}, true);

/* ---------- right-click, and a long press on touch ---------- */
const TYPING = "input, textarea, select, [contenteditable]";
const PRESSABLE = ".row, .card, .hero, .player .now, .cmain img, .cinfo";
let lastTouch = 0, press = null, swallowClick = 0;

document.addEventListener("contextmenu", e => {
  if (e.shiftKey || e.target.closest?.(TYPING)) return;
  e.preventDefault();
  if (Date.now() - lastTouch < 1500) return;          /* touch: the long press below handles it */
  let el = e.target;
  if (el === back) { closeMenu(); el = document.elementFromPoint(e.clientX, e.clientY) || document.body; }
  let { clientX: x, clientY: y } = e;
  if (!x && !y) { const r = el.getBoundingClientRect(); x = r.left + 12; y = r.top + r.height / 2; }   /* the keyboard's menu key */
  openMenu(el, x, y);
});

document.addEventListener("pointerdown", e => {
  if (e.pointerType === "mouse") return;
  lastTouch = Date.now();
  const el = e.target.closest(PRESSABLE);
  if (!el || e.target.closest("#queue, #ctx, " + TYPING) || menuOpen()) return;
  press = { x: e.clientX, y: e.clientY, id: e.pointerId, timer: setTimeout(() => {
    press = null; swallowClick = Date.now() + 800;
    navigator.vibrate?.(8);
    openMenu(el, e.clientX, e.clientY);
  }, 500) };
}, true);
const cancelPress = () => { if (press) { clearTimeout(press.timer); press = null; } };
document.addEventListener("pointermove", e => {
  if (press && e.pointerId === press.id && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 10) cancelPress();
}, true);
document.addEventListener("pointerup", cancelPress, true);
document.addEventListener("pointercancel", cancelPress, true);
/* the finger lifting after a long press would also "tap" what's under it */
document.addEventListener("click", e => {
  if (Date.now() < swallowClick && !e.target.closest("#ctx")) { e.preventDefault(); e.stopPropagation(); swallowClick = 0; }
}, true);
