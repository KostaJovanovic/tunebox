/* The pass phrase pop-up: unlocking a protected name on this device, and the admin phrase (removing
   people, clearing the history, resetting a forgotten phrase). It opens on top of whatever is open. */
import { $, esc } from "../../shared/dom.js";
import { errText } from "../../shared/api.js";
import { on } from "../../shared/actions.js";
import { syncScrim, onCloseAll } from "./ui.js";

let done = null, check = null, empty = false;

/* Asks for a phrase. check(phrase) runs before it closes: if it throws, its message shows and the
   pop-up stays for another try. Resolves with the phrase, or null when closed. */
export function askPhrase({ title, hint = "", button = "OK", allowEmpty = false, check: fn = null }) {
  if (done) done(null);
  $("#phraseTitle").textContent = title;
  $("#phraseHint").innerHTML = esc(hint);
  $("#phraseOk").textContent = button;
  $("#phraseIn").value = ""; $("#phraseMsg").textContent = "";
  check = fn; empty = allowEmpty;
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
onCloseAll(() => close(null));

/* Runs fn(admin) without the admin phrase first; if the server wants it, asks and tries again with it.
   Resolves with fn's result, or null if the pop-up was closed. */
export async function withAdmin(fn) {
  try { return await fn(undefined); }
  catch (e) { if (errText(e) !== "admin") throw e; }
  let result = null;
  const got = await askPhrase({ title: "Admin pass phrase", hint: "This needs the house's admin pass phrase.",
    check: async ph => { result = await fn(ph); } });
  return got === null ? null : result;
}
