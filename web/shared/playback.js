/* What's playing, and the requests that change it. Every page polls /api/state once a second and
   repaints from `state`; the queue helpers here are shared by the player and the wall screen. */
import { api, errText } from "./api.js";

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
let asked = 0, shown = 0;

export async function poll() {
  const n = ++asked;
  let s;
  try { s = await api("api/state"); } catch { return; }
  if (n < shown) return;
  shown = n;
  if (Date.now() < ppHold.until) s.paused = ppHold.paused;
  state = s;
  base = { pos: s.position, at: performance.now() };
  for (const fn of listeners) fn(s);
}

/* once a second; every 3 in performance mode (the progress bar slides between answers either way) */
export function startPolling() {
  poll();
  setTimeout(function again() { poll(); setTimeout(again, window.look.lite() ? 3000 : 1000); }, window.look.lite() ? 3000 : 1000);
}

const UNDOABLE = new Set(["remove", "move", "promote", "shuffle", "clear", "clear_auto", "refresh", "stop", "restore"]);

/* A transport or queue action (/api/control). Queue changes show a toast with Undo. */
export async function ctl(action, value, videoId, to, id) {
  if (action === "toggle" && state.current) {
    state.paused = !state.paused;
    ppHold = { paused: state.paused, until: Date.now() + 1500 };
    for (const fn of listeners) fn(state);
  }
  let r;
  try { r = await api("api/control", { action, value, videoId, to, id }); } catch (e) { toast(errText(e)); }
  if (r && r.message) toast(r.message, UNDOABLE.has(action));
  poll();
  return r;
}

export function undo() { ctl("undo"); }

/* The queue: now playing → songs people added (a tap adds, taking turns) → radio of the last one added.
   mode: add (end of the added songs), next, now, or replace (the list becomes what's up next). */
export async function queueSongs(tracks, mode, label) {
  try { const r = await api("api/play", { tracks, mode, label }); toast(r.message, true); } catch (e) { toast(errText(e)); }
  poll();
}
export const addSong = (key, i, mode = "add") => queueSongs([lists[key][i]], mode);
export const playAll = (key, label, mode = "replace") => queueSongs(lists[key], mode, label);

export function setVolume(v) {
  v = Math.max(0, Math.min(100, Math.round(v)));
  api("api/control", { action: "volume", value: v }).catch(e => toast(errText(e)));
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
