/* Playing something while a song is on (playing or paused) asks first: interrupt, play next, or add to
   the end of the queue (where songs from different people take turns). With nothing on, it just plays.
   Works for one song or a whole list (an album, playlist, history...). */
import { $, esc, plural } from "../../shared/dom.js";
import { state, queueSongs } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { syncScrim } from "./ui.js";

let pending = null;                            /* {tracks, label} waiting for an answer */

/* tracks: the songs; label: the list's name (for undo and the question), empty for one song */
export function askPlay(tracks, label = "") {
  if (!tracks || !tracks.length) return;
  const many = tracks.length > 1;
  if (!state.current) return queueSongs(tracks, many ? "replace" : "add", label);
  pending = { tracks, label };
  const t = tracks[0];
  $("#askSong").innerHTML = `<img src="${esc(t.thumb)}" alt=""><div class="min0"><div class="t">${esc(many ? label || "These songs" : t.title)}</div>
    <div class="s">${esc(many ? plural(tracks.length, "song") : [t.artist, t.album].filter(Boolean).join(" · "))}</div></div>`;
  $("#askPlay").classList.add("open"); syncScrim();
}

function close() { $("#askPlay").classList.remove("open"); syncScrim(); pending = null; }

on("ask", el => {
  const p = pending;
  close();
  if (!p) return;
  const mode = el.dataset.mode === "now" && p.tracks.length > 1 ? "replace" : el.dataset.mode;   /* a list becomes what's up next */
  queueSongs(p.tracks, mode, p.label);
});
on("ask-close", close);
