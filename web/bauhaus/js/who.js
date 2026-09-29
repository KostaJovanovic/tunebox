/* "Who's listening?": pick, add or edit the name this device adds songs as (top-bar badge), and the
   People list in Settings. It also opens by itself the first time someone adds a song without a name. */
import { $, esc } from "../../shared/dom.js";
import { api, errText, setNameAsker } from "../../shared/api.js";
import { COLORS, EMOJIS, people, seminars, myId, me, sortedPeople, setMe, savePerson, removePerson, unlockPerson, avatar, semTag, semTags } from "../../shared/people.js";
import { askPhrase, longEnough, withAdmin } from "./phrase.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim, onCloseAll } from "./ui.js";

let waiting = null;                            /* resolves the name asker: true once a name is picked */
let editing = null, pickColor = COLORS[4], pickEmoji = "", pickSems = new Set(), other = false;
let fromList = false;                          /* the form was opened from the list: Back returns to it */
let finishing = false;                         /* editing only because the name has no seminar yet: saving picks it */
let typedNow = null;                           /* the name whose pass phrase was just typed to unlock it */
let justTyped = null;                          /* ...and opened for editing: its Phrase button needn't ask again */

export function paintMe() {
  const p = me();
  $("#meBtn").innerHTML = avatar(p);
  $("#meBtn").title = p ? `Listening as ${p.name}` : "Who's listening?";
}

/* opens on the list of names, or straight on the form when there are none yet */
function openWho() {
  resetForm(); renderWho(); showForm(!sortedPeople().length);
  $("#who").classList.add("open"); $("#scrim").classList.add("open");
}
function showForm(on) {
  $("#whoPick").hidden = on; $("#whoForm").hidden = !on;
  $("#whoBack").textContent = editing && !fromList ? "Cancel" : "Back";
  $("#whoBack").hidden = !editing && !sortedPeople().length;
  if (!on) $("#whoTitle").textContent = "Who's listening?";
  else if (!editing) setTimeout(() => $("#whoName").focus(), 50);
}
function closeWho(chosen = false) {
  $("#who").classList.remove("open"); syncScrim();
  justTyped = null;
  if (waiting) { waiting(chosen); waiting = null; }
}
onCloseAll(() => { if (waiting) { waiting(false); waiting = null; } });
setNameAsker(() => { openWho(); return new Promise(r => waiting = r); });

/* a name with a pass phrase: this device types it once */
async function unlocked(id) {
  const p = people[id];
  if (!p.locked || p.mine) return true;
  const ok = await askPhrase({ title: `${p.name}'s pass phrase`, hint: "This name has a pass phrase. Type it once on this device.",
    button: "Unlock", check: ph => unlockPerson(id, ph) }) !== null;
  if (ok) typedNow = id;
  return ok;
}

async function choose(id) {
  if (!await unlocked(id)) return;
  if (!people[id].seminars?.length) return askSeminar(id);
  setMe(id);
  paintMe(); renderPeople(); closeWho(true);
  toast(`Listening as ${people[id].name}`);
}

export function renderWho() {
  const cur = me()?.id, ps = sortedPeople();
  $("#whoEditMe").hidden = !cur;
  $("#whoList").innerHTML = ps.length ? ps.map(p => `<button class="pick${p.id === cur ? " on" : ""}" data-act="who-set" data-id="${esc(p.id)}">${avatar(p)}
    <div class="min0"><div class="t">${esc(p.name)}</div><div class="s">${semTags(p)}</div></div><span class="ok"></span></button>`).join("")
    : '<div class="note tight">No names yet. Add yours below.</div>';
}

/* the form adds a name, or edits person p */
function resetForm(p = null) {
  editing = p ? p.id : null;
  pickColor = p ? p.color : COLORS[Object.keys(people).length % COLORS.length];
  pickEmoji = p ? p.emoji : "";
  pickSems = new Set(p?.seminars || []); other = false; fromList = false; $("#whoOther").value = ""; finishing = false;
  $("#whoName").value = p ? p.name : ""; $("#whoSave").textContent = p ? "Save" : "Add"; $("#whoMsg").textContent = "";
  $("#whoTitle").textContent = p ? `Edit ${p.name}` : "Add a name";
  $("#whoPhrase").value = ""; $("#whoPhrase").hidden = !!p;    /* editing: the pass phrase has its own button */
  paintPhraseBtn(p);
  paintForm();
}

function paintForm() {
  $("#whoSems").innerHTML = Object.values(seminars).map(x => `<button type="button" class="${pickSems.has(x.id) ? "on" : ""}" style="--c:${esc(x.color)}"
    aria-pressed="${pickSems.has(x.id)}" data-act="who-sem" data-s="${esc(x.id)}">${esc(x.name)}</button>`).join("")
    + `<button type="button" class="${other ? "on" : ""}" aria-pressed="${other}" data-act="who-sem-other">Other</button>`;
  $("#whoOther").hidden = !other;
  $("#whoColors").innerHTML = COLORS.map(c => `<button type="button" class="${c === pickColor ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="who-color" data-c="${c}"></button>`).join("");
  paintPreview();
  $("#whoEmoji").innerHTML = EMOJIS.map(e => `<button type="button" class="${e === pickEmoji ? "on" : ""}" aria-label="${e || "Initial"}" data-act="who-emoji" data-e="${e}">${e || "Aa"}</button>`).join("");
}

/* the badge being made, as it will look: avatar, then its seminar tags */
function paintPreview() {
  const name = $("#whoName").value.trim(), typed = $("#whoOther").value.trim();
  $("#whoPreview").innerHTML = avatar({ name: name || "?", color: pickColor, emoji: pickEmoji });
  const tags = [...pickSems].map(sid => semTag(sid)).join("")
    + (other && typed ? `<i class="sem">${esc(typed)}</i>` : "");
  $("#whoTags").innerHTML = tags || "No seminar yet";
}
$("#whoName").addEventListener("input", paintPreview);
$("#whoOther").addEventListener("input", paintPreview);

$("#whoForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#whoName").value.trim(), typed = $("#whoOther").value.trim();
  if (!name) return $("#whoName").focus();
  const sems = [...pickSems, ...(other && typed ? [typed] : [])], phrase = $("#whoPhrase").value;
  if (other && typed.length !== 3) return formMsg("Other: type the seminar's 3 letters"), $("#whoOther").focus();
  if (!sems.length) return formMsg("Pick your seminar");
  try {
    const p = await savePerson(editing, { name, color: pickColor, emoji: pickEmoji, seminars: sems, ...(!editing && phrase.trim() ? { phrase } : {}) });
    if (finishing || !editing) choose(p.id);
    else { closeWho(); renderPeople(); paintMe(); toast("Saved"); }
  } catch (err) { formMsg(errText(err)); }
});
function formMsg(t) { $("#whoMsg").textContent = t; $("#whoMsg").className = "msg err"; }

/* A name from before seminars: pick one before it can be used */
function askSeminar(id) {
  if (!$("#who").classList.contains("open")) openWho();
  resetForm(people[id]); finishing = true; showForm(true);
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
  $("#peopleList").innerHTML = sortedPeople().map(p => `<div class="prow">${avatar(p)}<div class="t">${esc(p.name)} ${semTags(p, "sm")}${p.locked ? '<span class="lock" title="Has a pass phrase">🔒</span>' : ""}${p.id === cur ? ' <span class="me-tag">· this device</span>' : ""}</div>
    <div class="acts"><button data-act="person-phrase" data-id="${esc(p.id)}" title="${p.locked ? "Change or remove the pass phrase" : "Add a pass phrase"}">Phrase</button><button data-act="person-edit" data-id="${esc(p.id)}">Edit</button><button data-act="person-remove" data-id="${esc(p.id)}">Remove</button></div></div>`).join("")
    || '<p class="hint tight">No names yet.</p>';
}

async function remove(id) {
  if (!confirm(`Remove ${people[id].name}? Their songs stay in the queue.`)) return;
  if (await withAdmin(admin => removePerson(id, admin)) === null) return;
  renderPeople(); paintMe();
}

async function resetPhrase(id) {
  const name = people[id].name;
  if (!confirm(`Take the pass phrase off ${name}? Anyone can then pick the name and set a new one.`)) return;
  try {
    if (await withAdmin(admin => api(`api/people/${id}/reset`, { admin })) === null) return;
  } catch (e) { return toast(errText(e)); }
  people[id].locked = false; renderPeople(); paintPhraseBtn(editing === id ? people[id] : null);
  toast(`${name} has no pass phrase now`);
}

/* Adds, changes or removes a name's pass phrase. A name that has one asks for it first (even on a
   device that holds its key), unless it was typed a moment ago to open the name for editing. */
async function editPhrase(id) {
  const p = people[id], fresh = justTyped === id;
  justTyped = null;
  if (p.locked && !fresh && await askPhrase({ title: `${p.name}'s current pass phrase`, button: "Next",
    hint: "Type the pass phrase this name has now.", check: ph => unlockPerson(id, ph),
    other: { label: "Forgot it?", run: () => resetPhrase(id) } }) === null) return;
  const nu = await askPhrase({ title: p.locked ? `New pass phrase for ${p.name}` : `A pass phrase for ${p.name}`,
    button: "Next", allowEmpty: p.locked, check: longEnough,
    hint: p.locked ? "At least 4 characters. Leave it empty to remove the pass phrase." : "At least 4 characters. Other devices will need it to use this name." });
  if (nu === null) return;
  if (nu.trim() && await askPhrase({ title: "Type it again", button: "Save",
    check: async v => { if (v !== nu) throw new Error("That's not the same"); } }) === null) return;
  try {
    const q = await savePerson(id, { phrase: nu.trim() ? nu : "" });
    renderPeople(); paintPhraseBtn(editing === id ? q : null);
    toast(q.locked ? `${q.name}'s pass phrase saved` : `${q.name} has no pass phrase now`);
  } catch (e) { toast(errText(e)); }
}

function paintPhraseBtn(p) {
  if (!p) return $("#whoPhraseBtn").hidden = true;
  $("#whoPhraseBtn").hidden = false;
  $("#whoPhraseBtn").textContent = p.locked ? "Change or remove the pass phrase" : "Add a pass phrase";
}

/* ---------- the admin pass phrase (Settings → People) ---------- */
let adminSet = false;
export async function paintAdmin() {
  try { adminSet = (await api("api/admin")).set; } catch { return; }
  $("#adminState").textContent = `Admin pass phrase: ${adminSet ? "set" : "not set"}`;
  $("#adminBtn").textContent = adminSet ? "Change" : "Set";
}

async function setAdmin() {
  let old;
  if (adminSet && (old = await askPhrase({ title: "Current admin pass phrase" })) === null) return;
  const nu = await askPhrase({ title: "New admin pass phrase", button: "Next", allowEmpty: adminSet, check: longEnough,
    hint: adminSet ? "At least 4 characters. Leave it empty to remove the admin pass phrase." : "At least 4 characters." });
  if (nu === null) return;
  if (nu.trim() && await askPhrase({ title: "Type it again", button: "Save",
    check: async v => { if (v !== nu) throw new Error("That's not the same"); } }) === null) return;
  try {
    const r = await api("api/admin", { old, new: nu.trim() ? nu : null });
    toast(r.set ? "Admin pass phrase saved" : "Admin pass phrase removed");
  } catch (e) { toast(errText(e)); }
  paintAdmin();
}

/* ---------- wiring ---------- */
on("who-open", openWho);
on("who-close", () => closeWho());
on("who-set", el => choose(el.dataset.id));
on("who-color", el => { pickColor = el.dataset.c; paintForm(); });
on("who-emoji", el => { pickEmoji = el.dataset.e; paintForm(); });
on("who-sem", el => { const s = el.dataset.s; pickSems.has(s) ? pickSems.delete(s) : pickSems.add(s); paintForm(); });
on("who-sem-other", () => { other = !other; paintForm(); if (other) $("#whoOther").focus(); });
on("person-edit", async el => {
  const id = el.dataset.id;
  typedNow = null;
  if (!await unlocked(id)) return;
  openWho(); resetForm(people[id]); showForm(true);
  justTyped = typedNow;
});
on("who-edit-me", () => { if (me()) { resetForm(me()); fromList = true; showForm(true); } });
on("who-new", () => { resetForm(); showForm(true); });
on("who-back", () => editing && !fromList ? closeWho() : (resetForm(), showForm(false)));
on("person-remove", el => remove(el.dataset.id));
on("person-phrase", el => editPhrase(el.dataset.id));
on("who-phrase", () => editPhrase(editing));
on("admin-set", setAdmin);
