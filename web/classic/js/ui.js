/* Building blocks for the Classic interface: icons, the toast, drawers, and the HTML for song rows and
   cards. Buttons carry data-act="..." (see shared/actions.js); a song button also says which list it's
   from and where (data-list, data-i), the song itself sits in lists[list][i]. */
import { $, esc } from "../../shared/dom.js";
import { state } from "../../shared/playback.js";
import { isLiked } from "../../shared/likes.js";
import { byChip } from "../../shared/people.js";

export const ICON = {
  play: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4v16l13-8z"/></svg>',
  pause: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>',
  next: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h12M4 12h8M4 18h8M18 11v8M14 15h8"/></svg>',
  plays: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  grip: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  heart: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.4a4.2 4.2 0 0 1 7.5 2.4C19.5 15.4 12 20 12 20z"/></svg>',
};

/* ---------- toast ---------- */
let toastT;
export function toast(t, undoable = false) {
  const el = $("#toast");
  el.innerHTML = esc(t) + (undoable ? '<button data-act="undo">Undo</button>' : "");
  el.classList.toggle("undo", undoable); el.classList.add("open"); clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove("open"), undoable ? 5000 : 2200);
}
export const hideToast = () => $("#toast").classList.remove("open");

/* ---------- drawers (Up next, Settings) and the name pop-up ---------- */
export const isOpen = id => $("#" + id).classList.contains("open");
export function syncScrim() { $("#scrim").classList.toggle("open", isOpen("drawer") || isOpen("settings") || isOpen("who")); }

/* ---------- HTML pieces ---------- */
export const spinner = t => `<div class="spinner">${t}…</div>`;
export const empty = t => `<div class="empty">${t}</div>`;
export const at = (key, i) => `data-list="${esc(key)}" data-i="${i}"`;

/* A song row: a tap adds it; Play next, Play now and Like on the right */
export function songRow(t, key, i) {
  const cur = state.current && state.current.videoId === t.videoId ? " playing" : "";
  return `<div class="row${cur}">
    <img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="meta" data-act="song" ${at(key, i)}>
      <div class="t">${esc(t.title)}</div><div class="s">${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div>
    </div>
    <span class="d">${esc(t.duration)}</span>
    <div class="acts">
      <button title="Play next" aria-label="Play next" data-act="song" data-mode="next" ${at(key, i)}>${ICON.next}</button>
      <button title="Play now" aria-label="Play now" data-act="song" data-mode="now" ${at(key, i)}>${ICON.plays}</button>
      <button class="like${isLiked(t.videoId) ? " on" : ""}" data-act="like" ${at(key, i)} data-like="${esc(t.videoId)}" title="Like">${ICON.heart}</button>
    </div></div>`;
}

/* A queued song: who added it, and (after the one playing) Play next, Remove and a drag handle */
export function queueRow(t, i, nu) {
  const auto = i > nu, by = i === 0 ? (t.src === "user" ? t.by : "radio") : auto ? "radio" : t.by;
  const target = `data-at="${(state.offset || 0) + i}" data-vid="${esc(t.videoId)}"`;
  return `<div class="row${i === 0 ? " playing" : ""}${auto ? " auto" : ""}">
    <img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="meta"${i === 0 ? "" : ` data-act="queue" data-a="jump" ${target}`}><div class="t">${esc(t.title)}</div><div class="s">${byChip(by)}${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div></div>
    <span class="d">${esc(t.duration)}</span>
    <div class="acts">${i === 0 ? "" : `<button title="Play next" aria-label="Play next" data-act="queue" data-a="promote" ${target}>${ICON.next}</button>
      <button title="Remove" aria-label="Remove" data-act="queue" data-a="remove" ${target}>✕</button><span class="grip" title="Drag to move">${ICON.grip}</span>`}</div></div>`;
}

/* A card from YouTube (song, album, playlist, artist): a song is added, the rest open their page */
export function card(it) {
  const act = it.type === "song" ? `data-act="add-track" data-track="${esc(JSON.stringify(it))}"`
    : `data-act="open" data-type="${esc(it.type)}" data-id="${esc(it.id)}"`;
  return `<button class="card" ${act}><img loading="lazy" src="${esc(it.thumb)}" alt="">
    <div class="t">${esc(it.title)}</div><div class="s">${esc(it.subtitle || it.artist || "")}</div></button>`;
}

export const songCard = (t, key, i) => `<button class="card" data-act="song" ${at(key, i)}><img loading="lazy" src="${esc(t.thumb)}" alt="">
    <div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></button>`;
