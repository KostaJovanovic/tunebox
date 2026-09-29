/* Buttons say what they do with data-act="name" (plus data-* details); modules register what each name does.

     <button data-act="add-song" data-list="search" data-i="3">       on("add-song", el => ...)

   One listener on the document handles every click, so rows built with innerHTML need no wiring. */

const handlers = {};

export function on(name, fn) {
  handlers[name] = fn;
}

document.addEventListener("click", e => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  const fn = handlers[el.dataset.act];
  if (!fn) { console.warn("no handler for", el.dataset.act); return; }
  fn(el, e);
});
