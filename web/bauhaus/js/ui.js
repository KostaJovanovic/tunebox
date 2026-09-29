/* Building blocks the views share: the toast, drawers and pop-ups, and the HTML for song rows, cards
   and section headings. Buttons carry data-act="..." (see shared/actions.js); a song button also says
   which list it's from and where (data-list, data-i), the song itself sits in lists[list][i]. */
import { $, $$, esc, pad } from "../../shared/dom.js";
import { state } from "../../shared/playback.js";
import { isLiked } from "../../shared/likes.js";
import { byChip, people, avatar } from "../../shared/people.js";
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
  return `<button class="like${on ? " on" : ""}" data-act="like" ${at(key, i)} data-like="${esc(vid)}" title="Like" aria-label="Like" aria-pressed="${on}">${icon.HEART}</button>`;
};

/* A song row. A tap on the title adds the song (o.meta: other attributes for that tap); the buttons on
   the right are Play next, Play (asks first, see ask.js), Add to playlist and Like unless o.acts says otherwise.
   o: num (shown number), playing (false: never marked as playing), by (who added it), likers (who liked it), d (text in place
   of the length), cls (extra class), extra (HTML after the buttons) */
export function songRow(t, key, i, o = {}) {
  const cur = (o.playing ?? true) && state.current && state.current.videoId === t.videoId ? " playing" : "";
  const meta = o.meta || `data-act="song" ${at(key, i)}`;
  const acts = o.acts ?? `<button class="wide" title="Play next" aria-label="Play next" data-act="song" data-mode="next" ${at(key, i)}>${icon.NEXT}</button>
      <button title="Play" aria-label="Play" data-act="song" data-mode="now" ${at(key, i)}>${icon.PLAYS}</button>
      <button title="Add to playlist" aria-label="Add to playlist" data-act="pick" ${at(key, i)}>${icon.LIST}</button>
      ${likeBtn(key, i, t.videoId)}`;
  return `<div class="row${cur}${o.cls ? " " + o.cls : ""}">
    <span class="n">${pad(o.num ?? i + 1)}</span>
    <img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="meta" ${meta}>
      <div class="t">${esc(t.title)}</div><div class="s">${o.likers ? o.likers.map(id => people[id] ? avatar(people[id], "sm") : "").join("") : o.by ? byChip(o.by) : ""}${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div>
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

/* A card for song i of a list (the house's own shelves on Home) */
export const songCard = (t, key, i) => `<button class="card" data-act="song" ${at(key, i)}><img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="t">${esc(t.title)}</div><div class="s"><i class="kind song"></i>${esc(t.artist)}</div></button>`;

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
