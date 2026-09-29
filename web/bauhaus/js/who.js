/* "Who's listening?": pick, add or edit the name this device adds songs as (top-bar badge), and the
   People list in Settings. It also opens by itself the first time someone adds a song without a name. */
import { $, esc } from "../../shared/dom.js";
import { errText, setNameAsker } from "../../shared/api.js";
import { COLORS, EMOJIS, people, seminars, myId, me, sortedPeople, setMe, savePerson, removePerson, avatar, semTags } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim, onCloseAll } from "./ui.js";

let waiting = null;                            /* resolves the name asker: true once a name is picked */
let editing = null, pickColor = COLORS[4], pickEmoji = "", pickSems = new Set(), other = false;
let finishing = false;                         /* editing only because the name has no seminar yet: saving picks it */

export function paintMe() {
  const p = me();
  $("#meBtn").innerHTML = avatar(p);
  $("#meBtn").title = p ? `Listening as ${p.name}` : "Who's listening?";
}

function openWho() {
  resetForm(); renderWho();
  $("#who").classList.add("open"); $("#scrim").classList.add("open");
}
function closeWho(chosen = false) {
  $("#who").classList.remove("open"); syncScrim();
  if (waiting) { waiting(chosen); waiting = null; }
}
onCloseAll(() => { if (waiting) { waiting(false); waiting = null; } });
setNameAsker(() => { openWho(); return new Promise(r => waiting = r); });

function choose(id) {
  if (!people[id].seminars?.length) return askSeminar(id);
  setMe(id);
  paintMe(); renderPeople(); closeWho(true);
  toast(`Listening as ${people[id].name}`);
}

export function renderWho() {
  const cur = myId(), ps = sortedPeople();
  $("#whoList").innerHTML = ps.length ? ps.map(p => `<button class="pick${p.id === cur ? " on" : ""}" data-act="who-set" data-id="${esc(p.id)}">${avatar(p)}
    <div class="min0"><div class="t">${esc(p.name)}</div><div class="s">${semTags(p)}</div></div><span class="ok"></span></button>`).join("")
    : '<div class="note tight">No names yet. Add yours below.</div>';
}

/* the form adds a name, or edits person p */
function resetForm(p = null) {
  editing = p ? p.id : null;
  pickColor = p ? p.color : COLORS[Object.keys(people).length % COLORS.length];
  pickEmoji = p ? p.emoji : "";
  pickSems = new Set(p?.seminars || []); other = false; $("#whoOther").value = ""; finishing = false;
  $("#whoName").value = p ? p.name : ""; $("#whoSave").textContent = p ? "Save" : "Add"; $("#whoMsg").textContent = "";
  $("#whoTitle").textContent = p ? `Edit ${p.name}` : "Who's listening?";
  $("#whoList").hidden = !!p;
  paintForm();
}

function paintForm() {
  $("#whoSems").innerHTML = Object.values(seminars).map(x => `<button type="button" class="${pickSems.has(x.id) ? "on" : ""}" style="--c:${esc(x.color)}"
    aria-pressed="${pickSems.has(x.id)}" data-act="who-sem" data-s="${esc(x.id)}">${esc(x.name)}</button>`).join("")
    + `<button type="button" class="${other ? "on" : ""}" aria-pressed="${other}" data-act="who-sem-other">Other</button>`;
  $("#whoOther").hidden = !other;
  $("#whoColors").innerHTML = COLORS.map(c => `<button type="button" class="${c === pickColor ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="who-color" data-c="${c}"></button>`).join("");
  $("#whoEmoji").innerHTML = EMOJIS.map(e => `<button type="button" class="${e === pickEmoji ? "on" : ""}" aria-label="${e || "Initial"}" data-act="who-emoji" data-e="${e}">${e || "Aa"}</button>`).join("");
}

$("#whoForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#whoName").value.trim(), typed = $("#whoOther").value.trim();
  if (!name) return $("#whoName").focus();
  const sems = [...pickSems, ...(other && typed ? [typed] : [])];
  if (other && typed.length !== 3) return formMsg("Other: type the seminar's 3 letters"), $("#whoOther").focus();
  if (!sems.length) return formMsg("Pick your seminar");
  try {
    const p = await savePerson(editing, { name, color: pickColor, emoji: pickEmoji, seminars: sems });
    if (finishing || !editing) choose(p.id);
    else { closeWho(); renderPeople(); paintMe(); toast("Saved"); }
  } catch (err) { formMsg(errText(err)); }
});
function formMsg(t) { $("#whoMsg").textContent = t; $("#whoMsg").className = "msg err"; }

/* A name from before seminars: pick one before it can be used */
function askSeminar(id) {
  if (!$("#who").classList.contains("open")) openWho();
  resetForm(people[id]); finishing = true;
  $("#whoTitle").textContent = `${people[id].name}: your seminar`;
  $("#whoMsg").textContent = "Pick your seminar to go on"; $("#whoMsg").className = "msg";
}

/* once per page: this device's name has no seminar yet */
let checked = false;
export function checkSeminar() {
  const p = me();
  if (checked || !p) return;
  checked = true;
  if (!p.seminars?.length) askSeminar(p.id);
}

/* ---------- Settings → People ---------- */
export function renderPeople() {
  const cur = myId();
  $("#peopleList").innerHTML = sortedPeople().map(p => `<div class="prow">${avatar(p)}<div class="t">${esc(p.name)} ${semTags(p, "sm")}${p.id === cur ? ' <span class="me-tag">· this device</span>' : ""}</div>
    <div class="acts"><button data-act="person-edit" data-id="${esc(p.id)}">Edit</button><button data-act="person-remove" data-id="${esc(p.id)}">Remove</button></div></div>`).join("")
    || '<p class="hint tight">No names yet.</p>';
}

async function remove(id) {
  if (!confirm(`Remove ${people[id].name}? Their songs stay in the queue.`)) return;
  await removePerson(id);
  renderPeople(); paintMe();
}

/* ---------- wiring ---------- */
on("who-open", openWho);
on("who-close", () => closeWho());
on("who-set", el => choose(el.dataset.id));
on("who-color", el => { pickColor = el.dataset.c; paintForm(); });
on("who-emoji", el => { pickEmoji = el.dataset.e; paintForm(); });
on("who-sem", el => { const s = el.dataset.s; pickSems.has(s) ? pickSems.delete(s) : pickSems.add(s); paintForm(); });
on("who-sem-other", () => { other = !other; paintForm(); if (other) $("#whoOther").focus(); });
on("person-edit", el => { openWho(); resetForm(people[el.dataset.id]); });
on("person-remove", el => remove(el.dataset.id));
