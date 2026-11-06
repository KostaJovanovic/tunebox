/* Queue gestures: drag to reorder (mouse: drag a row; touch: the grip, or press and hold), and on
   touch, swipe left to remove and swipe right to play next. The first row (playing now) stays put.

   setupQueueGestures(listEl, { remove(i), promote(i), move(from, to), redraw() })
     i, from and to are row positions in the list (0 = playing now).
   queueBusy() is true while a finger or mouse is down on the list: the page must not redraw it then,
   or the row or button being pressed is swapped out and the tap gets lost.

   A swiped row is glued to the finger and let go on a spring at the finger's speed, so a flick counts
   as much as the distance. A removed row keeps going and what is under it closes up; a dropped row
   travels to its place. Both happen before the list is redrawn, so nothing jumps. */
import { spring, tracker, project } from "./motion.js";

const SWIPE = 90;                              /* px sideways that count as a swipe */
const DROP = 200;                              /* ms a dropped row takes to reach its place (queue.css) */
let drag = null, dragEnd = 0, pressed = false, dropping = false;

export const queueBusy = () => !!drag || pressed || dropping;

export function setupQueueGestures(list, on) {
  list.addEventListener("pointerdown", () => pressed = true, true);
  addEventListener("pointerup", () => { if (pressed) { pressed = false; setTimeout(on.redraw, 400); } }, true);
  addEventListener("pointercancel", () => pressed = false, true);
  addEventListener("blur", () => pressed = false);            /* released outside the window: no pointerup comes */

  list.addEventListener("pointerdown", e => {
    const row = e.target.closest(".row");
    if (!row || e.target.closest("button") || e.button > 0) return;
    const rows = [...list.querySelectorAll(".row")], i = rows.indexOf(row);
    if (i < 1) return;                         /* the playing song stays on top */
    drag = { row, rows, i, to: i, x0: e.clientX, y0: e.clientY, dx: 0, id: e.pointerId, on: false, swipe: false, touch: e.pointerType !== "mouse", trk: tracker() };
    if (e.target.closest(".grip")) { e.preventDefault(); startDrag(); }
    else if (drag.touch) drag.hold = setTimeout(startDrag, 300);
  });

  addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
    drag.trk.add(e);
    if (!drag.on) {
      if (drag.touch) {
        if (!drag.swipe && Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.5) { drag.swipe = true; clearTimeout(drag.hold); drag.row.classList.add("swiping"); }
        if (drag.swipe) {
          drag.dx = dx; drag.row.style.transform = `translateX(${dx}px)`;
          drag.row.dataset.swipe = dx < 0 ? (dx < -SWIPE ? "remove" : "left") : (dx > SWIPE ? "next" : "right");
          return;
        }
        if (Math.abs(dy) > 8) { clearTimeout(drag.hold); drag = null; }   /* a scroll, not a hold */
        return;
      }
      if (Math.abs(dy) < 6) return;
      startDrag();
    }
    const y = drag.mids[drag.i] + dy;
    let to = drag.i;
    while (to + 1 < drag.rows.length && y > drag.mids[to + 1]) to++;
    while (to > 1 && y < drag.mids[to - 1]) to--;
    drag.to = to;
    drag.rows.forEach((r, k) => r.style.transform = k === drag.i ? `translateY(${dy}px)`
      : k > drag.i && k <= to ? `translateY(${-drag.pitch}px)` : k < drag.i && k >= to ? `translateY(${drag.pitch}px)` : "");
  });

  list.addEventListener("touchmove", e => { if (drag && (drag.on || drag.swipe)) e.preventDefault(); }, { passive: false });
  list.addEventListener("contextmenu", e => { if (drag) e.preventDefault(); });

  function endDrag(e, cancel) {
    if (!drag || e.pointerId !== drag.id) return;
    clearTimeout(drag.hold);
    const d = drag; drag = null;
    if (d.swipe) {
      dragEnd = Date.now();
      const row = d.row, v = d.trk.velocity().x, far = d.dx + project(v, .99);
      const sp = spring(x => { row.style.transform = x ? `translateX(${x}px)` : ""; });
      const home = () => { delete row.dataset.swipe; sp.to(0, { velocity: v, damping: .8, then: () => row.classList.remove("swiping") }); };
      sp.jump(d.dx);
      if (cancel || Math.abs(far) < SWIPE || far * d.dx < 0) return home();
      if (navigator.vibrate) navigator.vibrate(10);
      if (d.dx > 0) { home(); return on.promote(d.i); }
      /* removed: it keeps going, and the rest closes up. The redraw that follows finds everything in place;
         if none comes (the server said no), it all goes back */
      const under = [];
      for (let el = row.nextElementSibling; el; el = el.nextElementSibling) under.push(el);
      row.dataset.swipe = "remove";
      sp.to(-row.offsetWidth, { velocity: v });
      under.forEach(el => { el.classList.add("closing"); el.style.transform = `translateY(${-row.offsetHeight}px)`; });
      setTimeout(() => {
        if (!row.isConnected) return;
        under.forEach(el => { el.style.transform = ""; el.classList.remove("closing"); });
        home();
      }, 900);
      return on.remove(d.i);
    }
    if (!d.on) return;
    dragEnd = Date.now();
    const to = cancel ? d.i : d.to;
    dropping = true;
    d.row.classList.add("dropping");
    d.rows.forEach((r, k) => { if (k === d.i) r.style.transform = `translateY(${d.mids[to] - d.mids[d.i]}px)`; else if (cancel) r.style.transform = ""; });
    setTimeout(() => {
      dropping = false;
      d.row.classList.remove("dragging", "dropping");
      d.rows.forEach(r => r.style.transform = "");
      if (to === d.i) on.redraw(); else on.move(d.i, to);
    }, DROP);
  }
  addEventListener("pointerup", e => endDrag(e));
  addEventListener("pointercancel", e => endDrag(e, true));
  /* the click that ends a drag or swipe must not also press what's under the finger */
  list.addEventListener("click", e => { if (Date.now() - dragEnd < 300) { e.stopPropagation(); e.preventDefault(); } }, true);
}

function startDrag() {
  if (!drag || drag.swipe) return;
  drag.on = true;
  drag.mids = drag.rows.map(r => { const b = r.getBoundingClientRect(); return b.top + b.height / 2; });
  drag.pitch = drag.row.offsetHeight;
  drag.row.classList.add("dragging");
  if (navigator.vibrate && drag.touch) navigator.vibrate(15);
}

/* The queue as it will look after moving row `from` to `to`, before the server confirms (same rule as
   the server: dropped among the added songs it counts as added, among the radio as radio) */
export function moveLocally(state, from, to) {
  const nu = state.userCount || 0, wasUser = from <= nu, isUser = to <= (wasUser ? nu : nu + 1);
  const t = state.queue.splice(from, 1)[0];
  t.src = isUser ? "user" : "auto";
  state.queue.splice(to, 0, t);
  state.userCount = nu - wasUser + isUser;
}
