/* The Up next drawer: now playing → songs people added (they take turns) → radio of the last one added.
   Rows can be dragged to reorder; on touch, swipe left removes and swipe right plays next. */
import { $, esc, ago, plural } from "../../shared/dom.js";
import { api } from "../../shared/api.js";
import { state, lists, ctl } from "../../shared/playback.js";
import { byChip } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { setupQueueGestures, queueBusy, moveLocally } from "../../shared/queue-gestures.js";
import { queueRow, isOpen, syncScrim, spinner, empty } from "./ui.js";

export function toggleQueue(open) { $("#drawer").classList.toggle("open", open); syncScrim(); renderQueue(); }

const qhead = (title, aside = "", tools = "") =>
  `<div class="qhead"><h3>${esc(title)}</h3>${aside ? `<span>${esc(aside)}</span>` : ""}<div class="qtools">${tools}</div></div>`;

/* The poll redraws every second: only touch the DOM when something changed, and never mid-gesture. */
let queueHtml = "";
export function renderQueue() {
  if (!isOpen("drawer") || queueBusy()) return;
  const q = state.queue || [], nu = state.userCount || 0;
  lists.queue = q;
  const put = html => { if (html !== queueHtml) { queueHtml = html; $("#queue").innerHTML = html; } };
  if (!q.length) return put(empty("Queue is empty. Tap any song to start."));
  let html = qhead("Now playing") + queueRow(q[0], 0, nu);
  html += qhead("Next in queue", nu ? plural(nu, "song") : "",
    nu ? '<button data-act="queue" data-a="shuffle">Shuffle</button><button data-act="queue" data-a="clear">Clear</button>' : "");
  html += nu ? q.slice(1, nu + 1).map((t, k) => queueRow(t, k + 1, nu)).join("")
    : '<div class="qempty">Tap any song to add it here. Songs from different people take turns.</div>';
  const auto = q.slice(nu + 1);
  html += qhead(state.seed ? `Next from: ${state.seed.title} radio` : "Radio", "",
      `<button data-act="queue" data-a="refresh">${auto.length ? "Refresh" : "Start radio"}</button>${auto.length ? '<button data-act="queue" data-a="clear_auto">Clear</button>' : ""}`)
    + auto.map((t, k) => queueRow(t, k + nu + 1, nu)).join("");
  put(html);
}

setupQueueGestures($("#queue"), {
  remove: i => ctl("remove", (state.offset || 0) + i, lists.queue[i].videoId),
  promote: i => ctl("promote", (state.offset || 0) + i, lists.queue[i].videoId),
  move(from, to) {
    const off = state.offset || 0, vid = lists.queue[from].videoId;
    moveLocally(state, from, to);              /* show it right away, the poll confirms */
    renderQueue();
    ctl("move", off + from, vid, off + to);
  },
  redraw: renderQueue,
});

/* ---------- earlier queues: every queue change keeps a snapshot, any of which can be put back ---------- */
let earlierOpen = false;
async function toggleEarlier(open = !earlierOpen) {
  earlierOpen = open; $("#earlierBtn").classList.toggle("on", open); $("#earlier").hidden = !open;
  if (!open) return;
  $("#earlier").innerHTML = spinner("Loading");
  const hs = await api("api/queue/history").catch(() => []);
  $("#earlier").innerHTML = qhead("Earlier queues", hs.length ? `${hs.length} kept` : "") + (hs.length ? hs.map(h => `<div class="erow">
    ${h.thumb ? `<img loading="lazy" src="${esc(h.thumb)}" alt="">` : '<div class="blank"></div>'}
    <div class="min0"><div class="t">Before: ${esc(h.label)}</div><div class="s">${byChip(h.by)}${esc(ago(h.at))} · ${plural(h.count, "song")}${h.current ? " · " + esc(h.current) : ""}</div></div>
    <button data-act="restore" data-id="${esc(h.id)}">Restore</button></div>`).join("")
    : '<div class="qempty">Nothing yet. Every change to the queue lands here.</div>');
  $("#earlier").scrollIntoView({ behavior: "smooth", block: "start" });
}

on("queue-open", () => toggleQueue(true));
on("queue-close", () => toggleQueue(false));
on("queue", el => ctl(el.dataset.a, el.dataset.at ? +el.dataset.at : undefined, el.dataset.vid));
on("earlier", () => toggleEarlier());
on("restore", async el => { await ctl("restore", null, null, null, el.dataset.id); toggleEarlier(true); });
