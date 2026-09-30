/* The admin panel: a full screen with tabs. It opens with the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) or,
   on a phone, ten quick taps on the word "Settings". The first time it asks for a password to set;
   after that it asks for it, and this device stays unlocked until 15 minutes pass without admin work.
   Tabs: People (admin-people.js) and Security (the password, the audit log). */
import { $, esc } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { state, position, ctl, onState } from "../../shared/playback.js";
import { admin, syncAdmin } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { toast, closeAll, loading } from "./ui.js";
import { askPhrase, longEnough, unlockAdmin, withAdmin } from "./phrase.js";
import { setVol } from "./settings.js";
import { showPeople } from "./admin-people.js";

const box = $("#admin");
const TABS = { people: ["People", showPeople], security: ["Security", showSecurity] };
let tab = "people";

export const adminOpen = () => box.classList.contains("open");

export async function openAdmin() {
  if (!await unlockAdmin()) return;
  closeAll();
  box.classList.add("open"); document.body.classList.add("admin-open");
  showTab(tab);
}
function closeAdmin() { box.classList.remove("open"); document.body.classList.remove("admin-open"); }

function showTab(name) {
  tab = name;
  $("#adminTabs").innerHTML = Object.entries(TABS).map(([k, [label]]) =>
    `<button class="${k === tab ? "on" : ""}" data-act="admin-tab" data-t="${k}">${label}</button>`).join("");
  $("#adminBody").scrollTop = 0;
  TABS[tab][1]($("#adminBody"));
}

async function lock() {
  await api("api/admin/logout", {});
  syncAdmin(false); closeAdmin(); toast("Admin locked");
}

/* the session ran out (or another device changed the password) */
onState(s => { if (syncAdmin(s.admin) && !admin && adminOpen()) { closeAdmin(); toast("Admin locked"); } });

/* ---------- Security ---------- */
const when = t => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const browser = ua => (/(Firefox|Edg|Chrome|Safari)\/[\d.]+/.exec(ua)?.[1] || "").replace("Edg", "Edge")
  + (/(Android|iPhone|iPad|Windows|Mac OS X|Linux)/.exec(ua) ? " on " + /(Android|iPhone|iPad|Windows|Mac OS X|Linux)/.exec(ua)[1].replace("Mac OS X", "Mac") : "");

async function showSecurity(el) {
  el.innerHTML = loading("Loading");
  const log = await withAdmin(() => api("api/admin/audit"));
  if (log === null || tab !== "security") return;
  el.innerHTML = `<div class="sec"><h2>Password</h2></div>
    <div class="body"><p>One password for the whole house. This device locks itself after 15 minutes without admin work.</p>
      <div class="eqtools"><button class="btn" data-act="admin-password">Change the password</button><button class="btn" data-act="admin-lock">Lock now</button></div>
      <p class="hint">Forgot it? On the server, run <code>python run.py --reset-admin</code>. The next person to open this panel sets a new one.</p></div>
    <div class="sec"><h2>Audit log</h2><span class="aside">the last ${log.length}</span></div>
    <div class="body">${log.map(e => `<div class="arow ev-${esc(e.ev)}"><div class="min0"><div class="t">${esc(e.msg)}</div>
      <div class="s">${when(e.t)}${e.ip ? " · " + esc(e.ip) : ""}${browser(e.ua) ? " · " + esc(browser(e.ua)) : ""}</div></div></div>`).join("") || "<p>Nothing yet.</p>"}</div>`;
}

async function changePassword() {
  const old = await askPhrase({ title: "Current admin password", button: "Next" });
  if (old === null) return;
  const nu = await askPhrase({ title: "New admin password", hint: "At least 4 characters.", button: "Next", check: longEnough });
  if (nu === null) return;
  const done = await askPhrase({ title: "Type it again", button: "Save", check: async v => {
    if (v !== nu) throw new Error("That's not the same");
    await api("api/admin/password", { old, new: nu });
  } });
  if (done !== null) { toast("Admin password changed"); showTab("security"); }
}

/* ---------- opening it: the Konami code ---------- */
const CODE = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
let at = 0, snaps = [];                        /* how far into the code; the player as it was before each ↑ */
const snap = () => ({ vol: +$("#vol2").value, pos: position(), at: performance.now(), paused: state.paused, vid: state.current?.videoId });

/* The arrows are also the player's shortcuts (volume, seek), and they still work while the code is
   typed. When it completes, the volume and the position go back to where they were before the first ↑. */
document.addEventListener("keydown", e => {
  const tag = e.target.tagName;
  if (adminOpen() || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.ctrlKey || e.metaKey || e.altKey) { at = 0; return; }
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (k === CODE[at]) { if (at < 2) snaps[at] = snap(); at++; }
  else if (k === "ArrowUp") { snaps = at === 2 ? [snaps[1], snap()] : [snap()]; at = at === 2 ? 2 : 1; }   /* ↑ ↑ ↑: the last two count */
  else at = 0;
  if (at < CODE.length) return;
  at = 0;
  const s = snaps[0];
  setVol(s.vol);
  if (s.vid && s.vid === state.current?.videoId) ctl("seek", s.paused ? s.pos : s.pos + (performance.now() - s.at) / 1000);
  openAdmin();
}, true);

/* ...and on a touch screen: ten quick taps on the Settings heading */
let taps = 0, lastTap = 0;
$("#settings > .dhead h2").addEventListener("pointerup", () => {
  const now = Date.now();
  taps = now - lastTap < 700 ? taps + 1 : 1; lastTap = now;
  if (taps >= 10) { taps = 0; openAdmin(); }
});

/* Esc closes the panel (a pop-up on top of it closes first); the player's shortcuts wait meanwhile */
document.addEventListener("keydown", e => {
  if (!adminOpen() || document.querySelector(".modal.open")) return;
  const tag = e.target.tagName;
  if (e.key === "Escape") { e.stopImmediatePropagation(); closeAdmin(); }
  else if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT" && !e.ctrlKey && !e.metaKey) e.stopImmediatePropagation();
}, true);

on("admin-open", openAdmin);
on("admin-close", closeAdmin);
on("admin-lock", () => lock().catch(e => toast(errText(e))));
on("admin-tab", el => showTab(el.dataset.t));
on("admin-password", changePassword);
