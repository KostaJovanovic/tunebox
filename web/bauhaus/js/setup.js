/* The setup card: the house's name, its accent, what it is for (a preset of the feature switches) and the
   admin password, and how others join.
   - On a fresh install it opens by itself on the server's own browser (api/setup decides: no admin
     password yet, nobody put it off, and this browser is on the server itself). Close or Esc puts it
     away for now; Later puts it off for good.
   - The admin opens it again from the panel (Security, "Run the setup again"): keeping everything, or
     after deleting everything (askWipe: a warning, then a button tapped 3 to 6 times, counting down).
     The admin has a password already, so the card doesn't ask for one. */
import { $, esc } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { house, admin, syncAdmin, setHouse } from "../../shared/house.js";
import { ACCENTS } from "../../shared/device.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim, onCloseAll } from "./ui.js";
import { longEnough, withAdmin } from "./phrase.js";
import { PRESETS } from "./admin-house.js";

const X = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M5 5l14 14M19 5 5 19"/></svg>';
let box = null, accent = "", preset = "home", again = false;

function modal(id, label) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("div");
    el.className = "modal setup"; el.id = id;
    el.setAttribute("role", "dialog"); el.setAttribute("aria-label", label);
    document.body.append(el);
  }
  return el;
}
const show = el => requestAnimationFrame(() => { el.classList.add("open"); syncScrim(); });
const hide = el => { if (el) { el.classList.remove("open"); syncScrim(); } };

/* opens the card; fromAdmin: the admin asked for it (no password fields, no Later) */
export function openSetup(fromAdmin = false) {
  again = fromAdmin;
  accent = house.accent || ""; preset = "home";
  box = modal("setup", "Set up Tunebox");
  render();
  show(box);
  api("api/network").then(n => {
    if (!n.ip || !$("#setupJoin")) return;
    const url = `${location.protocol}//${n.ip}${location.port ? ":" + location.port : ""}${location.pathname}`;
    $("#setupJoin").innerHTML = `Phones and computers on ${n.wifi ? `the Wi-Fi <b>${esc(n.wifi)}</b>` : "the same network"} open <a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>.`;
  }, () => {});
}

function render() {
  const acc = (k, name, c) => `<button type="button" class="acc${k ? "" : " all"}${accent === k ? " on" : ""}" data-act="setup-accent" data-k="${k}">${c ? `<i class="sw" style="background:${c}"></i>` : ""}${name}</button>`;
  box.innerHTML = `<div class="dhead"><h2><i></i>${again ? "Set up the house" : "Welcome to Tunebox"}</h2><button type="button" data-act="setup-close" aria-label="Close">${X}</button></div>
    <form class="mbody setupform" id="setupForm">
      <p class="hint tight">${again ? "The house's name, its accent and what it is for. The preset sets every feature switch at once; the admin panel fine-tunes them."
        : "This computer plays the music, and every phone on the network is a remote. A minute here sets up the house; all of it can be changed later."}</p>
      <label class="lbl" for="setupName">The house's name</label>
      <input class="field" id="setupName" maxlength="24" value="${esc(house.name || "Tunebox")}" autocomplete="off">
      <span class="lbl">Accent</span>
      <div class="presets c3">${acc("", "Each device's own")}${Object.entries(ACCENTS).map(([k, a]) => acc(k, a.name, a.c)).join("")}</div>
      <span class="lbl">What it's for</span>
      <div class="presets">${PRESETS.map(([k, name, what]) => `<button type="button" class="${preset === k ? "on" : ""}" data-act="setup-preset" data-p="${k}">${name}<small>${what}</small></button>`).join("")}</div>
      ${again ? "" : `<label class="lbl" for="setupPw">Admin password</label>
      <p class="hint tight">The admin manages people and the house's setup. At least 4 characters.</p>
      <input class="field" id="setupPw" type="password" autocomplete="new-password" placeholder="Admin password">
      <input class="field" id="setupPw2" type="password" autocomplete="new-password" placeholder="Type it again">`}
      <p class="hint" id="setupJoin">Phones and computers on the same network open this page's address with this computer's name or IP.</p>
      ${again ? "" : `<p class="hint">To get back to the admin panel: the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) on a keyboard, or ten quick taps on the word Settings on a phone.</p>`}
      <div class="msg err" id="setupMsg"></div>
      <div class="setupbtns">${again ? "" : '<button type="button" class="btn ghost" data-act="setup-later">Later</button>'}<button class="btn red" id="setupOk">${again ? "Save" : "Set up"}</button></div>
    </form>`;
  $("#setupForm").addEventListener("submit", submit);
}

async function submit(e) {
  e.preventDefault();
  const msg = $("#setupMsg");
  msg.textContent = "";
  const pw = again ? "" : $("#setupPw").value;
  if (!again) try {
    if (!pw.trim()) throw new Error("Choose an admin password");
    await longEnough(pw);
    if (pw !== $("#setupPw2").value) throw new Error("The two passwords are not the same");
  } catch (err) { msg.textContent = err.message; return; }
  $("#setupOk").disabled = true;
  try {
    if (!again) { await api("api/admin/login", { password: pw, create: true }); syncAdmin(true); }
    const ok = await withAdmin(async () => {
      await api("api/admin/features/preset", { name: preset });
      setHouse(await api("api/admin/house", { name: $("#setupName").value, accent }, "PATCH"));
      return true;
    });
    if (!ok) return;
    if (!again) await api("api/setup/done", {});
    hide(box); toast(again ? "House set up" : "All set");
  } catch (err) { msg.textContent = errText(err); }
  finally { $("#setupOk").disabled = false; }
}

on("setup-accent", el => { accent = el.dataset.k; box.querySelectorAll("[data-act=setup-accent]").forEach(b => b.classList.toggle("on", b === el)); });
on("setup-preset", el => { preset = el.dataset.p; box.querySelectorAll("[data-act=setup-preset]").forEach(b => b.classList.toggle("on", b === el)); });
on("setup-close", () => hide(box));
on("setup-later", async () => {
  hide(box);
  try { await api("api/setup/done", {}); toast("The admin panel can set it up later"); } catch (err) { toast(errText(err)); }
});
onCloseAll(() => { hide(box); hide(document.getElementById("wipe")); });

/* ---------- deleting everything first: a warning, then a button tapped 3 to 6 times ---------- */
let left = 0;
export function askWipe() {
  left = 3 + Math.floor(Math.random() * 4);
  const el = modal("wipe", "Delete everything");
  el.innerHTML = `<div class="dhead"><h2><i class="red"></i>Delete everything?</h2><button type="button" data-act="wipe-close" aria-label="Close">${X}</button></div>
    <div class="mbody setupform">
      <p class="hint tight"><b>This can't be undone from here.</b> Gone: every name and group, playlists and likes, the history, the play log and Stats, the queue, the sound settings, the house's setup, the blocklist and the local songs.</p>
      <p class="hint">Kept: the admin password, the YouTube sign-in, the audit log and every backup already on the server. A backup of what goes is saved there first (in <code>backups/</code>), with the local songs' folder.</p>
      <div class="msg err" id="wipeMsg"></div>
      <div class="setupbtns"><button type="button" class="btn ghost" data-act="wipe-close">Keep it</button><button type="button" class="btn red" id="wipeGo" data-act="wipe-tap"></button></div>
    </div>`;
  paintWipe();
  show(el);
}
function paintWipe() {
  $("#wipeGo").textContent = `Tap ${left} more ${left === 1 ? "time" : "times"} to delete`;
}
on("wipe-close", () => hide(document.getElementById("wipe")));
on("wipe-tap", async el => {
  if (left <= 0) return;
  left -= 1;
  if (left > 0) return paintWipe();
  el.disabled = true; el.textContent = "Deleting";
  try {
    const r = await withAdmin(() => api("api/admin/wipe", { confirm: "delete" }));
    if (r === null) { hide(document.getElementById("wipe")); return; }
    hide(document.getElementById("wipe"));
    toast("Everything was deleted");
    openSetup(true);
  } catch (err) { $("#wipeMsg").textContent = errText(err); el.disabled = false; left = 1; paintWipe(); }
});

/* a fresh install's server opens the card by itself */
api("api/setup").then(st => { if (st.show && !admin) openSetup(false); }, () => {});
