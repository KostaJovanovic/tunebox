/* Lyrics: the Lyrics drawer, plus the pieces the canvas uses for its own lyrics column.
   Synced lyrics light up line by line; a tap on a line jumps there. */
import { $, esc } from "../../shared/dom.js";
import { state, ctl, position } from "../../shared/playback.js";
import { fetchLyrics, activeLine, syncedHtml, plainHtml } from "../../shared/lyrics.js";
import { on } from "../../shared/actions.js";
import { loading, openDrawer, isOpen } from "./ui.js";

/* Keeps a box of synced lines lit up and scrolled to the line being sung. `where` (0..1) is how far
   down the box that line sits; a scroll by hand pauses the following for 4 seconds. */
export function follower(box, where, smooth) {
  let lines = null, active = -1, scrolled = 0;
  box.addEventListener("click", e => { const p = e.target.closest("p[data-t]"); if (p) ctl("seek", +p.dataset.t); });
  box.addEventListener("wheel", () => scrolled = Date.now(), { passive: true });
  box.addEventListener("touchmove", () => scrolled = Date.now(), { passive: true });
  return {
    set(l) { lines = l; active = -1; },
    tick(force) {
      if (!lines) return;
      const a = activeLine(lines, position());
      if (a === active && !force) return;
      active = a;
      box.querySelectorAll("p[data-i]").forEach(p => { const i = +p.dataset.i; p.classList.toggle("on", i === a); p.classList.toggle("past", i < a); });
      const el = box.querySelector(`p[data-i="${a}"]`);
      if (el && Date.now() - scrolled > 4000) box.scrollTo({ top: el.offsetTop - box.clientHeight * where, behavior: smooth ? "smooth" : "auto" });
    },
  };
}

/* ---------- the drawer ---------- */
const box = $("#lyr"), follow = follower(box, 0.38, false);
let shown = null;                              /* the videoId the drawer shows lyrics for */

export function toggleLyrics(open = !isOpen("lyrics")) {
  openDrawer("lyrics", open); $("#lyrBtn").classList.toggle("on", open);
  if (open) loadLyrics();
}

async function loadLyrics() {
  const c = state.current;
  if (!c) { box.innerHTML = '<div class="note">Nothing playing</div>'; shown = null; follow.set(null); return; }
  if (shown === c.videoId) return;
  shown = c.videoId; follow.set(null);
  const who = `<div class="who">Now playing<b>${esc(c.title)}</b>${esc(c.artist)}</div>`;
  box.className = "lyr"; box.innerHTML = who + loading("Finding lyrics");
  const d = await fetchLyrics(c);
  if (shown !== c.videoId) return;
  const src = s => `<div class="src">Lyrics: ${esc(s)}${s === "LRCLIB" ? " (lrclib.net, open community lyrics)" : ""}</div>`;
  if (d.instrumental) box.innerHTML = who + '<div class="note">Instrumental</div>' + src(d.source);
  else if (d.none) box.innerHTML = who + '<div class="note">No lyrics found for this song.</div>';
  else if (d.synced) { follow.set(d.synced); box.innerHTML = who + syncedHtml(d.synced) + src(d.source); follow.tick(true); }
  else { box.className = "lyr plain"; box.innerHTML = who + plainHtml(d.plain) + src(d.source); }
}

/* after each poll: a new song gets its lyrics */
export function paintLyrics() {
  if (isOpen("lyrics") && (state.current?.videoId || null) !== shown) loadLyrics();
}

setInterval(() => { if (isOpen("lyrics")) follow.tick(); }, 200);

on("lyrics-toggle", () => toggleLyrics());
on("lyrics-open", () => toggleLyrics(true));
on("lyrics-close", () => toggleLyrics(false));
