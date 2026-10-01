/* What's playing, and the requests that change it. Every page polls /api/state (see startPolling) and
   repaints from `state`; the queue helpers here are shared by the player and the wall screen. */
import { api, errText } from "./api.js";
import { secs } from "./dom.js";

export let state = {};                         /* the last /api/state (read-only elsewhere: only this module replaces it) */
export const lists = {};                       /* the songs on screen, by list name, so a button can say "song 3 of search" */

let toast = () => {};
/* How the page shows a message; `undoable` adds an Undo button */
export function setToaster(fn) { toast = fn; }

const listeners = [];
/* fn(state) runs after every poll */
export function onState(fn) { listeners.push(fn); }

/* play/pause fades for half a second on the server: flip the button now, and keep it flipped until the fade is done */
let ppHold = { until: 0 };

/* where the song is, to the fraction of a second (the poll only says it once a second) */
let base = { pos: 0, at: 0 };
export const position = () => state.paused ? base.pos : base.pos + (performance.now() - base.at) / 1000;

/* polls overlap (the timer, and one after every request): a slow older answer must not paint over a newer one */
let asked = 0, shown = 0, seekFrom = 0;    /* seekFrom: answers asked before the last seek are stale */

/* Two polls in a row that got no answer (the server or the Wi-Fi is down; behind Caddy, a 502): the page
   says so with a bar along the top, html[data-offline], and the controls dim until an answer comes. */
let failed = 0;
function reachable(ok) {
  failed = ok ? 0 : failed + 1;
  const off = failed >= 2, h = document.documentElement;
  if (h.hasAttribute("data-offline") === off) return;
  h.toggleAttribute("data-offline", off);
  if (!document.getElementById("offline")) {
    const b = Object.assign(document.createElement("div"), { id: "offline", textContent: "Can't reach the Tunebox server. Trying again…" });
    b.setAttribute("role", "status");
    document.body.append(b);
  }
}

export async function poll() {
  const n = ++asked;
  let s;
  try { s = await api("api/state"); } catch { reachable(false); return; }
  reachable(true);
  if (n < shown || n <= seekFrom) return;
  shown = n;
  if (Date.now() < ppHold.until) s.paused = ppHold.paused;
  state = s;
  base = { pos: s.position, at: performance.now() };
  for (const fn of listeners) fn(s);
}

/* once a second while a song plays; every 3 when nothing does, and in performance mode (the progress bar
   slides between answers either way). A hidden page doesn't ask at all, and asks at once when it shows again. */
let timer = 0;
const quiet = () => !state.current || (state.paused && !state.loading);
function next() {
  clearTimeout(timer);
  if (!document.hidden) timer = setTimeout(() => { poll(); next(); }, window.look.lite() || quiet() ? 3000 : 1000);
}
export function startPolling() {
  poll(); next();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); next(); });
}

const UNDOABLE = new Set(["remove", "remove_ids", "move", "promote", "promote_ids", "shuffle", "clear", "clear_mine", "clear_auto", "refresh", "stop", "restore"]);

/* A transport or queue action (/api/control). Queue changes show a toast with Undo. */
export async function ctl(action, value, videoId, to, id, videoIds) {
  if (action === "toggle" && state.current) {
    state.paused = !state.paused;
    ppHold = { paused: state.paused, until: Date.now() + 1500 };
    for (const fn of listeners) fn(state);
  }
  if (action === "seek" && state.current) {   /* the lyrics and the bar go there now, not at the next poll */
    seekFrom = asked; state.position = value; base = { pos: value, at: performance.now() };
    for (const fn of listeners) fn(state);
  }
  let r;
  try { r = await api("api/control", { action, value, videoId, to, id, videoIds }); } catch (e) { toast(errText(e)); }
  if (r && r.message) toast(r.message, UNDOABLE.has(action));
  poll();
  return r;
}

export function undo() { ctl("undo"); }

/* The queue: now playing → songs people added (a tap adds, taking turns) → radio of the last one added.
   mode: add (end of the added songs), next, now, or replace (the list becomes what's up next). */
export async function queueSongs(tracks, mode, label, wall = false) {
  if (tracks.length === 1 && (mode === "add" || mode === "next") && !confirmAgain(tracks[0])) return;
  try { const r = await api("api/play", { tracks, mode, label, wall }); toast(r.message, true); } catch (e) { toast(errText(e)); }
  poll();
}
/* One song that is already playing or waiting among people's songs: ask before it goes in twice */
function confirmAgain(t) {
  const q = state.queue || [], i = q.slice(0, (state.userCount || 0) + 1).findIndex(x => x.videoId === t.videoId);
  if (i < 0) return true;
  const where = i === 0 ? "playing now" : i === 1 ? "up next" : `${ordinal(i)} in line`;
  return confirm(`"${t.title}" is already ${where}. Add it again?`);
}
const ordinal = n => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");

/* Seconds until each song in state.queue starts (0 for the one playing), from what is left of it and
   the lengths of the songs before; a song with no known length counts as 3:30 */
export function waits() {
  const q = state.queue || [], out = [0];
  let t = Math.max(0, (state.duration || secs(q[0]?.duration) || 210) - position());
  for (let i = 1; i < q.length; i++) { out.push(t); t += secs(q[i].duration) || 210; }
  return out;
}
/* "in 4 min", "in 1 h 5 min"; under a minute is "next" */
export const inTime = s => s < 60 ? "next" : s < 3600 ? `in ${Math.round(s / 60)} min` : `in ${Math.floor(s / 3600)} h ${Math.round(s % 3600 / 60)} min`;

export const addSong = (key, i, mode = "add") => queueSongs([lists[key][i]], mode);
export const playAll = (key, label, mode = "replace") => queueSongs(lists[key], mode, label);

export function setVolume(v) {
  v = Math.max(0, Math.min(100, Math.round(v)));
  api("api/control", { action: "volume", value: v }).then(r => r?.message && toast(r.message)).catch(e => toast(errText(e)));   /* quiet hours say so */
  return v;
}

/* Anything that looks like a web address: a YouTube one opens its page, any other gets the server's
   "only YouTube links" message instead of being searched for as words */
export const LINK = /^(https?:\/\/|www\.)\S+$|^([\w-]+\.)*(youtube\.com|youtu\.be)(\/\S*)?$/i;

/* Save what's up next as a new playlist */
export async function saveQueue() {
  const name = prompt("Name for the new playlist", "Queue " + new Date().toLocaleDateString());
  if (!name) return;
  const p = await api("api/lists", { name, fromQueue: true });
  toast(`Saved "${p.name}" · ${p.tracks.length} songs`);
}
