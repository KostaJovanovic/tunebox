/* The pass phrase pop-up: unlocking a protected name on this device, and the admin password (the admin
   panel, removing people, clearing the history, restoring a backup). It opens on top of whatever is open. */
import { $, esc } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { syncAdmin } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim, onCloseAll } from "./ui.js";

let done = null, check = null, empty = false, alt = null;

/* Asks for a phrase. check(phrase) runs before it closes: if it throws, its message shows and the
   pop-up stays for another try. Resolves with the phrase, or null when closed. other: {label, run}, a link
   under the field that closes the pop-up (null) and runs instead ("Forgot it?"). */
export function askPhrase({ title, hint = "", button = "OK", allowEmpty = false, check: fn = null, other = null }) {
  if (done) done(null);
  $("#phraseTitle").textContent = title;
  $("#phraseHint").innerHTML = esc(hint);
  $("#phraseOk").textContent = button;
  $("#phraseIn").value = ""; $("#phraseMsg").textContent = "";
  check = fn; empty = allowEmpty; alt = other;
  $("#phraseAlt").hidden = !other; $("#phraseAlt").textContent = other?.label || "";
  $("#phrase").classList.add("open"); syncScrim();
  setTimeout(() => $("#phraseIn").focus(), 50);
  return new Promise(r => done = r);
}

function close(value) {
  $("#phrase").classList.remove("open"); syncScrim();
  if (done) { const d = done; done = null; d(value); }
}

$("#phraseForm").addEventListener("submit", async e => {
  e.preventDefault();
  const v = $("#phraseIn").value;
  if (!v.trim() && !empty) return $("#phraseIn").focus();
  if (check) {
    $("#phraseOk").disabled = true;
    try { await check(v); }
    catch (err) { $("#phraseMsg").textContent = errText(err); $("#phraseIn").select(); return; }
    finally { $("#phraseOk").disabled = false; }
  }
  close(v);
});

on("phrase-close", () => close(null));
on("phrase-alt", () => { const run = alt?.run; close(null); run?.(); });
onCloseAll(() => close(null));

/* check for a new phrase: the server's rule (spaces squeezed, at least 4 characters); empty passes */
export async function longEnough(v) {
  const n = v.trim().split(/\s+/).join(" ").length;
  if (n && n < 4) throw new Error("A pass phrase needs at least 4 characters");
}

/* Makes this device the admin: asks for the admin password, or for one to set when the house has none
   yet. True once it is unlocked (it stays so until 15 minutes pass without admin work). */
export async function unlockAdmin() {
  let st;
  try { st = await api("api/admin"); } catch (e) { toast(errText(e), false, "error"); return false; }
  if (st.admin) return syncAdmin(true), true;
  if (st.lockedFor) { toast(`Too many wrong passwords. Try again in ${Math.ceil(st.lockedFor / 60)} min`); return false; }
  let ok;
  if (st.set) ok = await askPhrase({ title: "Admin password", hint: "This needs the house's admin password.", button: "Unlock",
    check: password => api("api/admin/login", { password }) });
  else {
    const nu = await askPhrase({ title: "Choose an admin password", button: "Next", check: longEnough,
      hint: "Nobody has set one yet. The admin manages people and the house's setup. At least 4 characters." });
    if (nu === null) return false;
    ok = await askPhrase({ title: "Type it again", button: "Save", check: async v => {
      if (v !== nu) throw new Error("That's not the same");
      await api("api/admin/login", { password: nu, create: true });
    } });
  }
  if (ok === null) return false;
  syncAdmin(true);
  return true;
}

/* Runs fn(); if the server says it is the admin's, unlocks the admin here and runs it again.
   Resolves with fn's result, or null if the password pop-up was closed. */
export async function withAdmin(fn) {
  try { return await fn(); }
  catch (e) { if (errText(e) !== "admin") throw e; }
  syncAdmin(false);
  return await unlockAdmin() ? fn() : null;
}
