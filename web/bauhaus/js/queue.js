/* The Up next drawer: now playing → songs people added (they take turns) → radio of the last one added.
   Rows can be dragged to reorder; on touch, swipe left removes and swipe right plays next. */
import { $, esc, ago, plural } from "../../shared/dom.js";
import { api } from "../../shared/api.js";
import { state, lists, ctl } from "../../shared/playback.js";
import { byChip } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { setupQueueGestures, queueBusy, moveLocally } from "../../shared/queue-gestures.js";
import * as icon from "./icons.js";
import { loading, songRow, at, openDrawer, isOpen } from "./ui.js";

export function toggleQueue(open = !isOpen("drawer")) { openDrawer("drawer", open); renderQueue(); }

const qhead = (title, aside = "", tools = "") =>
  `<div class="qhead"><h3>${esc(title)}</h3>${aside ? `<span>${esc(aside)}</span>` : ""}<div class="qtools">${tools}</div></div>`;

/* the song at row i, for a queue action: its place in the whole queue, and its id so the server can
   check it's still the same song there */
const target = i => `data-at="${(state.offset || 0) + i}" data-vid="${esc(state.queue[i].videoId)}"`;

/* The poll redraws every second: only touch the DOM when something changed, and never mid-gesture. */
let queueHtml = "";
export function renderQueue() {
  if (!isOpen("drawer") || queueBusy()) return;
  const q = state.queue || [], nu = state.userCount || 0;
  lists.queue = q;
  const put = html => { if (html !== queueHtml) { queueHtml = html; $("#queue").innerHTML = html; } };
  if (!q.length) return put('<div class="note">Queue is empty. Tap any song to start.</div>');

  const pick = i => `<button title="Add to playlist" aria-label="Add to playlist" data-act="pick" ${at("queue", i)}>${icon.LIST}</button>`;
  const row = (t, i) => {
    if (i === 0) return songRow(t, "queue", 0, { num: 0, meta: 'data-act="lyrics-open"', by: t.src === "user" ? t.by : "radio", acts: pick(0) });
    const auto = i > nu;
    return songRow(t, "queue", i, { num: i, meta: `data-act="queue" data-a="jump" ${target(i)}`, by: auto ? "radio" : t.by, cls: auto ? "auto" : "",
      acts: `<button title="Play next" aria-label="Play next" data-act="queue" data-a="promote" ${target(i)}>${icon.NEXT}</button>${pick(i)}`,
      extra: `<button title="Remove" aria-label="Remove" data-act="queue" data-a="remove" ${target(i)}>${icon.X}</button><span class="grip" title="Drag to move">${icon.GRIP}</span>` });
  };

  let html = qhead("Now playing") + row(q[0], 0);
  html += qhead("Next in queue", nu ? plural(nu, "song") : "",
    nu ? '<button data-act="queue" data-a="shuffle">Shuffle</button><button data-act="queue" data-a="clear">Clear</button>' : "");
  html += nu ? q.slice(1, nu + 1).map((t, k) => row(t, k + 1)).join("")
    : '<div class="qempty">Tap any song to add it here. Songs from different people take turns.</div>';
  const auto = q.slice(nu + 1);
  html += qhead(state.seed ? `Next from: ${state.seed.title} radio` : "Radio", "",
      `<button data-act="queue" data-a="refresh">${auto.length ? "Refresh" : "Start radio"}</button>${auto.length ? '<button data-act="queue" data-a="clear_auto">Clear</button>' : ""}`)
    + auto.map((t, k) => row(t, k + nu + 1)).join("");
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
  $("#earlier").innerHTML = loading("Loading");
  const hs = await api("api/queue/history").catch(() => []);
  $("#earlier").innerHTML = qhead("Earlier queues", hs.length ? `${hs.length} kept` : "") + (hs.length ? hs.map(h => `<div class="erow">
    ${h.thumb ? `<img loading="lazy" src="${esc(h.thumb)}" alt="">` : '<div class="blank"></div>'}
    <div class="min0"><div class="t">Before: ${esc(h.label)}</div><div class="s">${byChip(h.by)}${esc(ago(h.at))} · ${plural(h.count, "song")}${h.current ? " · " + esc(h.current) : ""}</div></div>
    <button class="btn" data-act="restore" data-id="${esc(h.id)}">Restore</button></div>`).join("")
    : '<div class="qempty">Nothing yet. Every change to the queue lands here.</div>');
  $("#earlier").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- wiring ---------- */
on("queue-open", () => toggleQueue(true));
on("queue-close", () => toggleQueue(false));
on("queue", el => ctl(el.dataset.a, el.dataset.at ? +el.dataset.at : undefined, el.dataset.vid));
on("earlier", () => toggleEarlier());
on("restore", async el => { await ctl("restore", null, null, null, el.dataset.id); toggleEarlier(true); });
