/* The page's own questions, instead of the browser's confirm() and prompt(), which look like another
   program's and block the whole page on a phone. Used by the player and the wall (shared/dialog.css).

     await ask("Delete it for everyone?", { ok: "Delete", danger: true })   true or false
     await askText("Name for the new playlist", "Queue 1/10")               the text, or null

   A <dialog> opened with showModal(): the focus stays inside it, Enter answers yes (or saves), Esc and a
   tap beside it answer no, and the focus goes back where it was. One at a time: a second waits. */

let line = Promise.resolve();
const queue = fn => { const p = line.then(fn); line = p.catch(() => {}); return p; };

export const ask = (text, o = {}) => queue(() => open(text, { ok: "OK", ...o }, false));
export const askText = (label, value = "", o = {}) => queue(() => open(label, { ok: "Save", ...o, value }, true));

function open(text, o, input) {
  return new Promise(done => {
    const back = document.activeElement;
    const d = document.createElement("dialog");
    d.className = "tbask" + (o.danger ? " danger" : "");
    d.innerHTML = `<form method="dialog"><p></p>${input ? '<input type="text" autocomplete="off" maxlength="200">' : ""}
      <div class="btns"><button type="button" class="no"></button><button value="yes" class="ok"></button></div></form>`;
    d.querySelector("p").textContent = text;
    d.querySelector(".no").textContent = o.cancel || "Cancel";
    d.querySelector(".ok").textContent = o.ok;
    const field = d.querySelector("input");
    if (field) { field.value = o.value || ""; field.setAttribute("aria-label", text); }
    d.querySelector(".no").addEventListener("click", () => d.close());
    d.addEventListener("click", e => { if (e.target === d) d.close(); });   /* the backdrop is the dialog itself */
    /* keys stay here: Esc closes only this, not the panel behind; letters aren't the page's shortcuts */
    d.addEventListener("keydown", e => e.stopPropagation());
    d.addEventListener("pointerdown", e => e.stopPropagation());
    d.addEventListener("close", () => {
      const yes = d.returnValue === "yes";
      d.remove();
      back?.focus?.({ preventScroll: true });
      done(input ? (yes && field.value.trim()) || null : yes);
    });
    document.body.append(d);
    d.showModal();
    if (field) field.select(); else d.querySelector(".ok").focus();
  });
}
