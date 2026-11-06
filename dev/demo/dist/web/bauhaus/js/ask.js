/* Playing something while a song is on (playing or paused) asks first: interrupt, play next, or add to
   the end of the queue (where songs from different people take turns). With nothing on, it just plays.
   Works for one song or a whole list (an album, playlist, history...). A song already in the queue asks
   the same, without "add to the end": interrupt jumps to it, play next moves it up. */
import { $, esc, plural, art } from "../../shared/dom.js";
import { state, queueSongs, ctl } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { syncScrim, markAdded } from "./ui.js";

let pending = null;                            /* {tracks, label, from} or {queued: {at, vid}} waiting for an answer */

function open(t, title, sub, hide = []) {
  $("#askSong").innerHTML = `<img src="${esc(art(t))}" alt=""><div class="min0"><div class="t">${esc(title)}</div><div class="s">${esc(sub)}</div></div>`;
  for (const b of document.querySelectorAll("#askPlay [data-act=ask]")) b.hidden = hide.includes(b.dataset.mode);
  $("#askPlay").classList.add("open"); syncScrim();
}

/* tracks: the songs; label: the list's name (for undo and the question), empty for one song; from: the
   button tapped, whose row or card says "added" once it goes (ui.js markAdded) */
export function askPlay(tracks, label = "", from = null) {
  if (!tracks || !tracks.length) return;
  const many = tracks.length > 1;
  if (!state.current) return markAdded(from, sent => queueSongs(tracks, many ? "replace" : "add", label, false, sent));
  pending = { tracks, label, from };
  const t = tracks[0];
  open(t, many ? label || "These songs" : t.title, many ? plural(tracks.length, "song") : [t.artist, t.album].filter(Boolean).join(" · "));
}

/* a song in Up next, by its place in the whole queue (at) and its id; the one already next only asks
   whether to interrupt */
export function askQueued(at, vid) {
  const i = at - (state.offset || 0), t = state.queue?.[i];
  if (!t || i < 1) return;
  pending = { queued: { at, vid } };
  open(t, t.title, [t.artist, t.album].filter(Boolean).join(" · "), i === 1 ? ["add", "next"] : ["add"]);
}

function close() { $("#askPlay").classList.remove("open"); syncScrim(); pending = null; }

on("ask", el => {
  const p = pending;
  close();
  if (!p) return;
  if (p.queued) return ctl(el.dataset.mode === "now" ? "jump" : "promote", p.queued.at, p.queued.vid);
  const mode = el.dataset.mode === "now" && p.tracks.length > 1 ? "replace" : el.dataset.mode;   /* a list becomes what's up next */
  markAdded(p.from, sent => queueSongs(p.tracks, mode, p.label, false, sent));
});
on("ask-close", close);
