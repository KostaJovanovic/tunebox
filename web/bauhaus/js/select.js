/* Picking several songs at once, in Up next or a playlist: "Select" turns a tap on a row into a pick,
   and a bar along the bottom acts on everything picked. Songs are picked by videoId, so the queue moving
   on (and redrawing every second) keeps them picked. Rows carry data-vid (ui.js songRow). */
import { $, esc, plural } from "../../shared/dom.js";

let sel = null;                                /* { box, wrap, picked: Set<videoId>, actions: [{label, run(ids)}], onEnd } */

/* box: the element the rows are drawn into; wrap: an ancestor that sees taps before the rows' own
   handlers (gestures, actions); actions: what the bar offers */
export function startSelect(box, wrap, actions, onEnd = () => {}) {
  stopSelect();
  sel = { box, wrap, picked: new Set(), actions, onEnd };
  wrap.addEventListener("pointerdown", swallow, true);
  wrap.addEventListener("click", tap, true);
  box.classList.add("selecting");
  bar();
}

export function stopSelect() {
  if (!sel) return;
  const s = sel;
  sel = null;
  s.wrap.removeEventListener("pointerdown", swallow, true);
  s.wrap.removeEventListener("click", tap, true);
  s.box.classList.remove("selecting");
  s.box.querySelectorAll(".row.picked").forEach(r => r.classList.remove("picked"));
  $("#selbar")?.remove();
  s.onEnd();
}

export const selecting = box => !!sel && sel.box === box;

/* after the rows were drawn again: show what is picked, and forget picks whose song is gone */
export function markPicked() {
  if (!sel) return;
  const there = new Set();
  sel.box.querySelectorAll(".row[data-vid]").forEach(r => { there.add(r.dataset.vid); r.classList.toggle("picked", sel.picked.has(r.dataset.vid)); });
  for (const v of sel.picked) if (!there.has(v)) sel.picked.delete(v);
  bar();
}

const inRows = e => sel && sel.box.contains(e.target) && e.target.closest(".row[data-vid]");
function swallow(e) { if (inRows(e)) e.stopPropagation(); }   /* no drags or swipes while picking */
function tap(e) {
  const row = inRows(e);
  if (!row) return;
  e.stopPropagation(); e.preventDefault();
  const v = row.dataset.vid;
  sel.picked.has(v) ? sel.picked.delete(v) : sel.picked.add(v);
  markPicked();
}

function bar() {
  let b = $("#selbar");
  if (!b) {
    b = Object.assign(document.createElement("div"), { id: "selbar", className: "selbar" });
    b.addEventListener("click", async e => {
      const btn = e.target.closest("button");
      if (!btn || !sel) return;
      if (btn.dataset.done) return stopSelect();
      const a = sel.actions[+btn.dataset.a], ids = [...sel.picked];
      if (!ids.length) return;
      await a.run(ids);
      stopSelect();
    });
    document.body.append(b);
  }
  const n = sel.picked.size;
  b.innerHTML = `<span>${n ? plural(n, "song") : "Tap songs to pick them"}</span>`
    + sel.actions.map((a, i) => `<button class="btn${a.danger ? " danger" : ""}" data-a="${i}" ${n ? "" : "disabled"}>${esc(a.label)}</button>`).join("")
    + '<button class="btn ghost" data-done="1">Done</button>';
}
