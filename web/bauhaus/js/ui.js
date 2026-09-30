/* Building blocks the views share: the toast, drawers and pop-ups, and the HTML for song rows, cards
   and section headings. Buttons carry data-act="..." (see shared/actions.js); a song button also says
   which list it's from and where (data-list, data-i), the song itself sits in lists[list][i]. What belongs to a feature the
   admin can switch off says so with data-f="..." (base.css hides it). */
import { $, $$, esc, pad } from "../../shared/dom.js";
import { state } from "../../shared/playback.js";
import { isLiked } from "../../shared/likes.js";
import { byChip, people, avatar } from "../../shared/people.js";
import { feat } from "../../shared/house.js";
import { spring, tracker, project, shift, letGo } from "../../shared/motion.js";
import * as icon from "./icons.js";

/* ---------- toast ---------- */
let toastT;
export function toast(t, undoable = false) {
  const el = $("#toast");
  el.innerHTML = esc(t) + (undoable ? '<button data-act="undo">Undo</button>' : "");
  el.classList.toggle("undo", undoable); el.classList.add("open"); clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove("open"), undoable ? 5000 : 2200);
}
export const hideToast = () => $("#toast").classList.remove("open");

/* ---------- drawers (Up next, Lyrics, Settings) and pop-ups ---------- */
const closeHooks = [];
/* fn runs whenever everything is closed at once (Esc, a tap on the backdrop) */
export function onCloseAll(fn) { closeHooks.push(fn); }

export const anyOpen = () => $$(".drawer.open, .modal.open").length > 0;
export const isOpen = id => $("#" + id).classList.contains("open");
export function syncScrim() { $("#scrim").classList.toggle("open", anyOpen()); }
export function clearHash() { if (location.hash === "#settings") history.replaceState(null, "", location.pathname); }
export function closeAll() {
  $$(".drawer.open, .modal.open").forEach(d => d.classList.remove("open"));
  syncScrim(); clearHash();
  closeHooks.forEach(fn => fn());
}
/* opening one closes the others */
export function openDrawer(id, open) {
  if (open) $$(".drawer.open, .modal.open").forEach(d => d.id !== id && d.classList.remove("open"));
  $("#" + id).classList.toggle("open", open); syncScrim();
}

/* ---------- dragging a panel away (touch) ---------- */
/* A panel goes back out the way it came in: a drawer to the right (axis "x"), a phone's sheet down ("y").
   It follows the finger, and on release a flick counts as much as the distance. Past half way it presses
   the panel's own Close button, so whatever closing it means still happens; if that leaves it open, it
   comes back. o.when(): the drag applies now; o.from(e): this touch may start one; o.close(): instead of
   the Close button; o.dim(): the backdrop that fades with it */
export function dragAway(el, o) {
  const X = o.axis === "x", when = o.when || (() => true), from = o.from || (() => true);
  const dim = o.dim || (() => $$(".drawer.open, .modal.open").length === 1 ? $("#scrim") : null);   /* the backdrop is shared */
  const sp = spring(v => { el.style.transform = X ? `translateX(${v}px)` : `translateY(${v}px)`; });
  const size = () => X ? el.offsetWidth : el.offsetHeight;
  let d = null, ended = 0;

  function grab(e, at) {
    d.on = true; d.x = e.clientX; d.y = e.clientY; d.base = at;
    d.dim = dim(); if (d.dim) d.dim.style.transition = "none";
    el.classList.add("dragging"); sp.jump(at);
  }
  el.addEventListener("pointerdown", e => {
    if (e.pointerType === "mouse" || !el.classList.contains("open") || !when() || !from(e)) return;
    d = { id: e.pointerId, x: e.clientX, y: e.clientY, on: false, trk: tracker() };
    const at = sp.moving ? sp.value : shift(el)[o.axis];
    if (at > 1) grab(e, at);                   /* caught on its way: it starts from where it is */
  });
  addEventListener("pointermove", e => {
    if (!d || e.pointerId !== d.id) return;
    d.trk.add(e);
    let along = X ? e.clientX - d.x : e.clientY - d.y;
    const across = X ? e.clientY - d.y : e.clientX - d.x;
    if (!d.on) {
      if (Math.abs(across) > 10 && Math.abs(across) >= Math.abs(along)) { d = null; return; }   /* a scroll */
      if (along < 10 || along < Math.abs(across)) return;
      grab(e, 0); along = 0;
    }
    const at = Math.max(0, d.base + along);
    sp.jump(at);
    if (d.dim) d.dim.style.opacity = 1 - at / size();
  });
  function end(e, cancel) {
    if (!d || e.pointerId !== d.id) return;
    const g = d; d = null;
    if (!g.on) return;
    ended = Date.now();
    const v = g.trk.velocity()[o.axis];
    if (g.dim) { g.dim.style.transition = ""; g.dim.style.opacity = ""; }
    let away = !cancel && v > -50 && sp.value + project(v) > size() / 2;
    if (away) {
      o.close ? o.close() : el.querySelector('.dhead [data-act$="-close"]')?.click();
      away = !el.classList.contains("open");
    }
    sp.to(away ? size() : 0, { velocity: v, then: () => letGo(el) });
  }
  addEventListener("pointerup", e => end(e));
  addEventListener("pointercancel", e => end(e, true));
  /* the tap that ends a drag isn't one */
  el.addEventListener("click", e => { if (e.isTrusted && Date.now() - ended < 300) { e.stopPropagation(); e.preventDefault(); } }, true);
}

$$(".drawer").forEach(el => dragAway(el, { axis: "x", from: e => !e.target.closest("input, select, textarea, .eqc, .grip, #queue .row") }));
$$(".modal").forEach(el => dragAway(el, { axis: "y", when: () => innerWidth <= 760, from: e => e.target.closest(".dhead") && !e.target.closest("button, a") }));

/* ---------- HTML pieces ---------- */
/* puts a page into the main view */
export const main = html => { $("#view").innerHTML = html; };
export const loading = t => `<div class="note"><i class="spin"></i>${t}</div>`;
export const note = t => `<div class="note">${t}</div>`;
export const section = (n, title, aside = "") =>
  `<div class="sec"><b>${pad(n)}</b><h2>${esc(title)}</h2>${aside ? `<span class="aside">${aside}</span>` : ""}</div>`;
export const backBtn = (label, act = 'data-act="back"') => `<button class="back" ${act}>${icon.BACK}${esc(label)}</button>`;

/* the attributes that point a button at song i of a list */
export const at = (key, i) => `data-list="${esc(key)}" data-i="${i}"`;

export const likeBtn = (key, i, vid) => {
  const on = isLiked(vid);
  return `<button class="like${on ? " on" : ""}" data-f="likes" data-act="like" ${at(key, i)} data-like="${esc(vid)}" title="Like" aria-label="Like" aria-pressed="${on}">${icon.HEART}</button>`;
};

/* a song from the house's own files says so */
export const localTag = t => String(t.videoId).startsWith("local:") ? '<i class="loc">Local</i>' : "";

/* A song row. A tap on the title adds the song (o.meta: other attributes for that tap); the buttons on
   the right are Play next, Play (asks first, see ask.js), Add to playlist and Like unless o.acts says otherwise.
   o: num (shown number), playing (false: never marked as playing), by (who added it), likers (who liked it), d (text in place
   of the length), cls (extra class), extra (HTML after the buttons) */
export function songRow(t, key, i, o = {}) {
  const cur = (o.playing ?? true) && state.current && state.current.videoId === t.videoId ? " playing" : "";
  const meta = o.meta || `data-act="song" ${at(key, i)}`;
  const acts = o.acts ?? `<button class="wide" title="Play next" aria-label="Play next" data-act="song" data-mode="next" ${at(key, i)}>${icon.NEXT}</button>
      <button title="Play" aria-label="Play" data-act="song" data-mode="now" ${at(key, i)}>${icon.PLAYS}</button>
      <button title="Add to playlist" aria-label="Add to playlist" data-f="playlists" data-act="pick" ${at(key, i)}>${icon.LIST}</button>
      ${likeBtn(key, i, t.videoId)}`;
  return `<div class="row${cur}${o.cls ? " " + o.cls : ""}">
    <span class="n">${pad(o.num ?? i + 1)}</span>
    <img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="meta" ${meta}>
      <div class="t">${esc(t.title)}</div><div class="s">${o.likers ? o.likers.map(id => people[id] && feat("people") ? avatar(people[id], "sm") : "").join("") : o.by ? byChip(o.by) : ""}${localTag(t)}${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div>
    </div>
    <span class="d">${esc(o.d ?? t.duration)}</span>
    <div class="acts">${acts}${o.extra || ""}</div></div>`;
}

/* A card from YouTube (song, album, playlist, artist): a song is added, the rest open their page */
export function card(it) {
  const act = it.type === "song" ? `data-act="add-track" data-track="${esc(JSON.stringify(it))}"`
    : `data-act="open" data-type="${esc(it.type)}" data-id="${esc(it.id)}"`;
  return `<button class="card" ${act}><img loading="lazy" src="${esc(it.thumb)}" alt="">
    <div class="t">${esc(it.title)}</div><div class="s"><i class="kind ${esc(it.type)}"></i>${esc(it.subtitle || it.artist || it.type)}</div></button>`;
}

/* A card for song i of a list (the house's own shelves on Home); liked songs show who liked them */
const likers = t => (t.likedBy || []).filter(id => people[id] && feat("people")).map(id => avatar(people[id], "sm")).join("");
export const songCard = (t, key, i) => `<button class="card" data-act="song" ${at(key, i)}><img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="t">${esc(t.title)}</div><div class="s">${likers(t) || '<i class="kind song"></i>'}${localTag(t)}${esc(t.artist)}</div></button>`;

/* A playlist cover: four covers in a square, one if there are fewer, a note icon if none */
export function mosaic(thumbs, cls = "mosaic") {
  thumbs = (thumbs || []).filter(Boolean);
  if (!thumbs.length) return `<div class="blank">${icon.NOTE}</div>`;
  if (thumbs.length < 4) return `<div class="${cls} one"><img loading="lazy" src="${esc(thumbs[0])}" alt=""></div>`;
  return `<div class="${cls}">${thumbs.slice(0, 4).map(u => `<img loading="lazy" src="${esc(u)}" alt="">`).join("")}</div>`;
}

/* "Today", "Yesterday" or "Monday 3 Mar" */
export function dayName(ts) {
  const d = new Date(ts * 1000), t = new Date(); t.setHours(0, 0, 0, 0);
  const diff = Math.round((t - new Date(d).setHours(0, 0, 0, 0)) / 864e5);
  return diff === 0 ? "Today" : diff === 1 ? "Yesterday" : d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
}
