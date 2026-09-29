/* "Who's listening?": pick, add or edit the name this device adds songs as, and the People list in
   Settings. It also opens by itself the first time someone adds a song without a name. */
import { $, esc } from "../../shared/dom.js";
import { errText, setNameAsker } from "../../shared/api.js";
import { COLORS, EMOJIS, people, myId, me, sortedPeople, setMe, savePerson, removePerson, avatar } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim } from "./ui.js";

let waiting = null;                            /* resolves the name asker: true once a name is picked */
let editing = null, pickColor = COLORS[4], pickEmoji = "";

export function paintMe() {
  const p = me();
  $("#meBtn").innerHTML = avatar(p);
  $("#meBtn").title = p ? `Listening as ${p.name}` : "Who's listening?";
}

function openWho() { resetForm(); renderWho(); $("#who").classList.add("open"); syncScrim(); }
export function closeWho(chosen = false) {
  $("#who").classList.remove("open"); syncScrim();
  if (waiting) { waiting(chosen); waiting = null; }
}
setNameAsker(() => { openWho(); return new Promise(r => waiting = r); });

function choose(id) {
  setMe(id);
  paintMe(); renderPeople(); closeWho(true);
  toast(`Listening as ${people[id].name}`);
}

export function renderWho() {
  const cur = myId(), ps = sortedPeople();
  $("#whoList").innerHTML = ps.length ? ps.map(p => `<button class="pick" data-act="who-set" data-id="${esc(p.id)}">${avatar(p)}<b>${esc(p.name)}</b>
    <span class="ok">${p.id === cur ? "This device" : ""}</span></button>`).join("") : '<div class="empty tight">No names yet. Add yours below.</div>';
}

/* the form adds a name, or edits person p */
function resetForm(p = null) {
  editing = p ? p.id : null;
  pickColor = p ? p.color : COLORS[Object.keys(people).length % COLORS.length];
  pickEmoji = p ? p.emoji : "";
  $("#whoName").value = p ? p.name : ""; $("#whoSave").textContent = p ? "Save" : "Add"; $("#whoMsg").textContent = "";
  $("#whoTitle").textContent = p ? `Edit ${p.name}` : "Who's listening?";
  $("#whoList").hidden = !!p;
  paintForm();
}

function paintForm() {
  $("#whoColors").innerHTML = COLORS.map(c => `<button type="button" class="${c === pickColor ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="who-color" data-c="${c}"></button>`).join("");
  $("#whoEmoji").innerHTML = EMOJIS.map(e => `<button type="button" class="${e === pickEmoji ? "on" : ""}" aria-label="${e || "Initial"}" data-act="who-emoji" data-e="${e}">${e || "Aa"}</button>`).join("");
}

$("#whoForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#whoName").value.trim();
  if (!name) return $("#whoName").focus();
  try {
    const p = await savePerson(editing, { name, color: pickColor, emoji: pickEmoji });
    if (editing) { closeWho(); renderPeople(); paintMe(); toast("Saved"); } else choose(p.id);
  } catch (err) { $("#whoMsg").textContent = errText(err); $("#whoMsg").className = "note2 err"; }
});

/* ---------- Settings → People ---------- */
export function renderPeople() {
  const cur = myId();
  $("#peopleList").innerHTML = sortedPeople().map(p => `<div class="prow">${avatar(p)}<span class="t">${esc(p.name)}${p.id === cur ? ' <small class="me-tag">· this device</small>' : ""}</span>
    <button data-act="person-edit" data-id="${esc(p.id)}">Edit</button><button data-act="person-remove" data-id="${esc(p.id)}">Remove</button></div>`).join("")
    || '<p class="note2 flush">No names yet.</p>';
}

async function remove(id) {
  if (!confirm(`Remove ${people[id].name}? Their songs stay in the queue.`)) return;
  await removePerson(id);
  renderPeople(); paintMe();
}

on("who-open", openWho);
on("who-close", () => closeWho());
on("who-set", el => choose(el.dataset.id));
on("who-color", el => { pickColor = el.dataset.c; paintForm(); });
on("who-emoji", el => { pickEmoji = el.dataset.e; paintForm(); });
on("person-edit", el => { openWho(); resetForm(people[el.dataset.id]); });
on("person-remove", el => remove(el.dataset.id));
