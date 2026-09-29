/* Lyrics: one lookup per song (the server caches too), shared by every view that shows them. */
import { esc } from "./dom.js";
import { api } from "./api.js";

let cache = {};

/* {synced: [[seconds, line], ...]} or {plain: "..."} or {instrumental} or {none}, plus source */
export function fetchLyrics(c) {
  if (Object.keys(cache).length > 40) cache = {};
  const q = new URLSearchParams({ videoId: c.videoId, title: c.title, artist: c.artist || "", album: c.album || "", duration: c.duration || "" });
  return cache[c.videoId] ??= api(`api/lyrics?${q}`).catch(() => { delete cache[c.videoId]; return { none: true }; });
}

/* The lines as <p>s: synced ones carry their time (data-t) and number (data-i); an empty line is a gap */
export const syncedHtml = lines => lines.map(([t, l], i) => l ? `<p data-t="${t}" data-i="${i}">${esc(l)}</p>` : `<p class="gap" data-t="${t}" data-i="${i}"></p>`).join("");
export const plainHtml = text => text.split("\n").map(l => l.trim() ? `<p>${esc(l)}</p>` : '<p class="gap"></p>').join("");

/* The synced line being sung at `pos` seconds (-1 before the first) */
export function activeLine(lines, pos) {
  let a = -1;
  for (let i = 0; i < lines.length; i++) { if (lines[i][0] <= pos + 0.25) a = i; else break; }
  return a;
}
