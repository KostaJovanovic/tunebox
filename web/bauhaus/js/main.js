/* Tunebox, the Bauhaus interface. Wires the parts together: every poll of /api/state repaints the
   player, the queue, likes, people and lyrics; buttons with data-act="..." find their handler in the
   module that owns them. Keyboard shortcuts are at the bottom. */
import { $ } from "../../shared/dom.js";
import { errText } from "../../shared/api.js";
import { state, lists, onState, startPolling, setToaster, ctl, undo, addSong, playAll, saveQueue } from "../../shared/playback.js";
import { setupLikes, syncLikes, toggleLike, likeCurrent } from "../../shared/likes.js";
import { syncPeople } from "../../shared/people.js";
import { feat, syncHouse, onHouse } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { toast, hideToast, closeAll, backdropTap, anyOpen, isOpen, openDrawer } from "./ui.js";
import { showHome, showExplore, showHistory, goTo, startPage } from "./library.js";
import { view } from "./nav.js";
import { showLists, likesChanged } from "./playlists.js";
import { showStats } from "./stats.js";
import { showLocal } from "./local.js";
import { renderQueue, toggleQueue } from "./queue.js";
import { toggleLyrics, paintLyrics } from "./lyrics.js";
import { toggleSettings, paintVolume, paintSleep, nudgeVol, toggleMute, renderDevice } from "./settings.js";
import { paintMe, renderPeople, renderWho, checkSeminar } from "./who.js";
import { paintBar, paintCanvas, toggleCanvas, canvasOpen } from "./player.js";
import { askPlay } from "./ask.js";
import "./menu.js";
import "./recap.js";
import "./admin.js";

setToaster(toast);
setupLikes(toast, likesChanged);
/* a request that failed with nobody waiting for it (a button's action) still says why */
addEventListener("unhandledrejection", e => { if (e.reason instanceof Error) toast(errText(e.reason)); });

onState(async s => {
  paintBar(s);
  paintVolume(s);
  paintSleep();
  renderQueue();
  syncLikes(s.listsRev);
  $("#undoBtn").disabled = !s.undo;
  $("#undoBtn").title = s.undo ? `Undo: ${s.undo.label} (Z)` : "Nothing to undo";
  paintLyrics();
  paintCanvas();
  syncHouse(s.houseRev);
  if (await syncPeople(s.peopleRev)) { paintMe(); renderPeople(); if (isOpen("who")) renderWho(); renderQueue(); checkSeminar(); }
});

/* ---------- pages ---------- */
const PAGES = { home: showHome, lists: showLists, history: showHistory, explore: showExplore, stats: showStats, local: showLocal };
/* a page whose feature the admin switched off isn't there (the admin still has it) */
const pageOn = v => ({ home: feat("browse"), explore: feat("browse"), stats: feat("stats"), local: feat("local"), lists: feat("playlists") || feat("likes") }[v] ?? true);
const go = v => { if (pageOn(v)) PAGES[v](); };
$("#nav").addEventListener("click", e => { const b = e.target.closest("button"); if (b) go(b.dataset.v); });

/* the house's setup changed (or the admin was unlocked or locked here): what depends on it follows */
function houseChanged() {
  $("#q").placeholder = feat("links") ? "Search, or paste a YouTube link" : "Search";
  paintMe(); renderPeople(); renderQueue(); renderDevice();
  if (!feat("lyrics") && isOpen("lyrics")) openDrawer("lyrics", false);
  if (!pageOn(view)) startPage();
}
onHouse(houseChanged);

/* ---------- buttons that belong to no one part ---------- */
on("nav", el => go(el.dataset.v));
/* playing something while a song is on asks first (ask.js); Play next and Add all just do it */
on("song", el => {
  const mode = el.dataset.mode || "now";
  if (mode === "now") askPlay([lists[el.dataset.list][+el.dataset.i]]);
  else addSong(el.dataset.list, +el.dataset.i, mode);
});
on("play-all", el => {
  const mode = el.dataset.mode || "replace";
  if (mode === "replace") askPlay(lists[el.dataset.list], el.dataset.label);
  else playAll(el.dataset.list, el.dataset.label, mode);
});
on("like", el => toggleLike(lists[el.dataset.list][+el.dataset.i]));
on("like-now", likeCurrent);
on("goto", el => goTo(el.dataset.to, state.current));
on("prev", () => ctl("prev"));
on("next", () => ctl("next"));
on("toggle", () => ctl("toggle"));
on("stop", () => ctl("stop"));
on("undo", () => { hideToast(); undo(); });
on("save-queue", saveQueue);
on("close-all", backdropTap);
on("keys-open", () => openDrawer("keys", true));
on("keys-close", () => openDrawer("keys", false));

/* ---------- keyboard shortcuts ---------- */
document.addEventListener("keydown", e => {
  const tag = e.target.tagName;
  if (e.key === "Escape") { if (!anyOpen() && canvasOpen()) toggleCanvas(false); else closeAll(); return; }
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target.isContentEditable || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target.closest && e.target.closest(".eqc")) return;   /* the EQ knobs use the arrows themselves */
  const pos = () => state.position || 0;
  const keys = {
    " ": () => ctl("toggle"),
    ArrowLeft: () => e.shiftKey ? ctl("prev") : ctl("seek", Math.max(0, pos() - 10)),
    ArrowRight: () => e.shiftKey ? ctl("next") : ctl("seek", Math.min((state.duration || 1) - 1, pos() + 10)),
    ArrowUp: () => nudgeVol(5), ArrowDown: () => nudgeVol(-5),
    m: toggleMute,
    "/": () => $("#q").focus(),
    q: () => toggleQueue(),
    l: () => toggleLyrics(),
    s: () => toggleSettings(!isOpen("settings")),
    n: () => toggleCanvas(),
    h: () => go("history"), p: () => go("lists"), e: () => go("explore"), t: () => go("stats"),
    f: () => { if (feat("likes")) likeCurrent(); },
    z: () => { hideToast(); undo(); },
    "?": () => openDrawer("keys", !isOpen("keys")),
  };
  const f = keys[e.key] || keys[e.key.toLowerCase?.()];
  if (!f || (tag === "BUTTON" && e.key === " ")) return;
  e.preventDefault(); f();
});

/* ---------- installable as an app (browsers allow the service worker only over HTTPS or on localhost) ---------- */
if ("serviceWorker" in navigator && isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});

/* ---------- start ---------- */
houseChanged();
startPage();
startPolling();
if (location.hash === "#settings") toggleSettings(true);
