/* Tapping a song while another one plays asks what to do with it: play it now, play it next, or add it
   to the queue (where songs from different people take turns). With nothing playing it just plays. */
import { $, esc } from "../../shared/dom.js";
import { state, queueSongs } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { syncScrim } from "./ui.js";

let pending = null;                            /* the song waiting for an answer */

export function tapSong(t) {
  if (!state.current || state.paused) return queueSongs([t], "add");
  pending = t;
  $("#askSong").innerHTML = `<img src="${esc(t.thumb)}" alt=""><div class="min0"><div class="t">${esc(t.title)}</div><div class="s">${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div></div>`;
  $("#askPlay").classList.add("open"); syncScrim();
}

export function closeAsk() { $("#askPlay").classList.remove("open"); syncScrim(); pending = null; }

on("ask", el => { const t = pending; closeAsk(); if (t) queueSongs([t], el.dataset.mode); });
on("ask-close", closeAsk);
