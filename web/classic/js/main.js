/* Tunebox, the Classic interface. Wires the parts together: every poll of /api/state repaints the
   player bar, the queue, likes, people and the sleep timer; buttons with data-act="..." find their
   handler in the module that owns them. */
import { $, fmt, secs, setCookie } from "../../shared/dom.js";
import { state, lists, onState, startPolling, setToaster, ctl, undo, addSong, playAll } from "../../shared/playback.js";
import { setupLikes, syncLikes, toggleLike, likeCurrent } from "../../shared/likes.js";
import { syncPeople } from "../../shared/people.js";
import { store } from "../../shared/device.js";
import { on } from "../../shared/actions.js";
import { ICON, toast, hideToast, isOpen } from "./ui.js";
import { showHome, likesChanged } from "./library.js";
import { renderQueue, toggleQueue } from "./queue.js";
import { toggleSettings, paintVolume, paintSleep } from "./settings.js";
import { paintMe, renderPeople, renderWho, closeWho } from "./who.js";
import { tapSong, closeAsk } from "./ask.js";

setToaster(toast);
setupLikes(toast, likesChanged);

/* ---------- the player bar ---------- */
let seeking = false;
onState(async s => {
  const c = s.current;
  $("#pTitle").textContent = c ? c.title : "Nothing playing";
  $("#pSub").textContent = c ? [c.artist, c.album].filter(Boolean).join(" · ") : "Search for something to play";
  if (c && $("#pImg").dataset.src !== c.thumb) { $("#pImg").src = c.thumb; $("#pImg").dataset.src = c.thumb; }
  $("#pBtn").innerHTML = s.paused || !c ? ICON.play : ICON.pause;
  $("#pStatus").textContent = s.loading ? "Loading track…" : (s.error || "");
  const dur = s.duration || secs(c?.duration);   /* restored paused after a restart: mpv has no length yet */
  $("#tPos").textContent = fmt(s.position); $("#tDur").textContent = fmt(dur);
  if (!seeking) { $("#seek").max = Math.max(1, dur); $("#seek").value = s.position; }
  paintVolume(s);
  paintSleep();
  document.title = c ? `${s.paused ? "❚❚" : "▶"} ${c.title} · Tunebox` : "Tunebox";
  renderQueue();
  syncLikes(s.listsRev);
  $("#undoBtn").disabled = !s.undo; $("#undoBtn").title = s.undo ? `Undo: ${s.undo.label}` : "Nothing to undo";
  if (await syncPeople(s.peopleRev)) { paintMe(); renderPeople(); if (isOpen("who")) renderWho(); renderQueue(); }
});

$("#seek").addEventListener("input", () => { seeking = true; $("#tPos").textContent = fmt($("#seek").value); });
$("#seek").addEventListener("change", async () => { await ctl("seek", +$("#seek").value); seeking = false; });

function closeAll() { toggleQueue(false); toggleSettings(false); closeWho(); closeAsk(); }

/* ---------- buttons that belong to no one part ---------- */
/* a tap on a song asks what to do if something plays (ask.js); its buttons say (data-mode) */
on("song", el => el.dataset.mode ? addSong(el.dataset.list, +el.dataset.i, el.dataset.mode) : tapSong(lists[el.dataset.list][+el.dataset.i]));
on("play-all", el => playAll(el.dataset.list, el.dataset.label, el.dataset.mode || "replace"));
on("like", el => toggleLike(lists[el.dataset.list][+el.dataset.i]));
on("like-now", likeCurrent);
on("prev", () => ctl("prev"));
on("next", () => ctl("next"));
on("toggle", () => ctl("toggle"));
on("stop", () => ctl("stop"));
on("undo", () => { hideToast(); undo(); });
on("close-all", closeAll);

/* Space plays/pauses, except while typing or on a focused control; Esc closes everything */
document.addEventListener("keydown", e => {
  if (e.code === "Space" && !e.target.closest("input, textarea, select, button, [contenteditable]")) { e.preventDefault(); ctl("toggle"); }
  if (e.key === "Escape") closeAll();
});

/* opening Classic makes it this device's choice, so "/" keeps showing it */
store.set("tb_ui", "classic"); setCookie("tb_ui", "classic");
showHome();
startPolling();
if (location.hash === "#settings") toggleSettings(true);
