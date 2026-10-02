/* "Who's listening?": pick, add or edit the name this device adds songs as (top-bar badge), and the
   People list in Settings. It also opens by itself the first time someone adds a song without a name. */
import { $, esc } from "../../shared/dom.js";
import { api, errText, setNameAsker } from "../../shared/api.js";
import { COLORS, EMOJIS, people, seminars, myId, me, sortedPeople, setMe, savePerson, removePerson, unlockPerson, avatar, semTag, semTags } from "../../shared/people.js";
import { iconFor, LOCK } from "../../shared/avatars.js";
import { admin, house, feat, isOn, G } from "../../shared/house.js";
import { askPhrase, longEnough, withAdmin } from "./phrase.js";
import { on } from "../../shared/actions.js";
import { toast, syncScrim, onCloseAll } from "./ui.js";
import { ask } from "../../shared/dialog.js";

let waiting = null;                            /* resolves the name asker: true once a name is picked */
let editing = null, pickColor = COLORS[4], pickEmoji = "", pickSems = new Set(), other = false;
let fromList = false;                          /* the form was opened from the list: Back returns to it */
let finishing = false;                         /* editing only because the name has no group yet: saving picks it */
let typedNow = null;                           /* the name whose pass phrase was just typed to unlock it */
let justTyped = null;                          /* ...and opened for editing: its Phrase button needn't ask again */
let query = "", group = "";                    /* what's typed in Find your name, and the group chip picked ("": all) */
const FIND_FROM = 2;                           /* this many names or more: the field and the group chips */

export function paintMe() {
  const p = me();
  $("#meBtn").innerHTML = avatar(p);
  $("#meBtn").title = p ? `Listening as ${p.name}` : "Who's listening?";
}

/* opens on the list of names, or straight on the form when there are none yet */
function openWho() {
  query = ""; group = ""; $("#whoSearch").value = "";
  resetForm(); renderWho(); showForm(!sortedPeople().length);
  $("#who").classList.add("open"); $("#scrim").classList.add("open");
}
/* does this name still have to pick a group? (the house may not ask for one) */
const needsGroup = p => isOn("groups") && house.groups.required && !p.seminars?.length;
function showForm(on) {
  $("#whoPick").hidden = on; $("#whoForm").hidden = !on;
  $("#who").classList.toggle("form", on);      /* a phone shows the form full-screen (phone.css) */
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
setNameAsker(() => new Promise(r => { waiting = r; openWho(); }));   /* waiting first: the strip says why it asks */

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
  if (needsGroup(people[id])) return askSeminar(id);
  setMe(id);
  paintMe(); renderPeople(); closeWho(true);
  toast(`Listening as ${people[id].name}`);
}

const mayAddName = () => house.signups === "open" || admin;   /* the admin may have closed sign-ups: then only the admin adds names */
const fold = s => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();   /* "zeljko" finds "Željko" */

/* The names as tiles, this device's first; a name with a pass phrase this device hasn't typed wears a lock.
   With many names a field finds yours (by name or group), and the last tile adds a new one. */
export function renderWho() {
  const cur = me(), all = sortedPeople(), q = fold(query.trim());
  $("#whoFind").hidden = all.length < FIND_FROM;
  /* the chips: the groups that have names, only when there are two or more to tell apart */
  const used = feat("groups") ? Object.values(seminars).filter(x => all.some(p => p.seminars?.includes(x.id))) : [];
  if (!used.some(x => x.id === group)) group = "";
  $("#whoGroups").hidden = all.length < FIND_FROM || used.length < 2;
  $("#whoGroups").innerHTML = `<button type="button" class="${group ? "" : "on"}" aria-pressed="${!group}" data-act="who-group" data-s="">All</button>`
    + used.map(x => `<button type="button" class="${group === x.id ? "on" : ""}" style="--c:${esc(x.color)}" aria-pressed="${group === x.id}" data-act="who-group" data-s="${esc(x.id)}">${esc(x.name)}</button>`).join("");
  const hit = p => (!group || p.seminars?.includes(group))
    && (!q || fold(p.name).includes(q) || (feat("groups") && (p.seminars || []).some(s => seminars[s] && fold(seminars[s].name).includes(q))));
  const ps = (cur ? [cur, ...all.filter(p => p !== cur)] : all).filter(hit);
  const tile = p => `<button class="wtile${p === cur ? " on" : ""}" data-act="who-set" data-id="${esc(p.id)}">
    <span class="wav">${avatar(p)}${p.locked && !p.mine ? `<span class="wlock" title="Has a pass phrase">${LOCK}</span>` : ""}</span>
    <span class="t">${esc(p.name)}</span><span class="s">${p === cur ? "This device" : semTags(p, "sm")}</span></button>`;
  const typed = query.trim();
  const add = mayAddName() ? `<button class="wtile add" data-act="who-new"><span class="wav"><i class="av"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><path d="M12 5v14M5 12h14"/></svg></i></span>
    <span class="t">${q ? `Add ${esc(typed)}` : "Add a name"}</span><span class="s">${q ? "as a new name" : "New here?"}</span></button>` : "";
  const none = ps.length ? "" : q ? `<p class="wnone">No name matches “${esc(typed)}”${group ? ` in ${esc(seminars[group].name)}` : ""}.</p>`
    : group ? `<p class="wnone">No names in ${esc(seminars[group].name)}.</p>` : "";
  $("#whoList").innerHTML = none + ps.map(tile).join("") + add;
  $("#whoNow").innerHTML = cur
    ? `${avatar(cur, "sm")}<span class="min0">Listening as <b>${esc(cur.name)}</b></span><button type="button" class="link" data-act="who-edit-me">Edit</button>`
    : waiting ? "<span>Pick your name first.</span>" : "";
  $("#whoNow").hidden = !cur && !waiting;
}

$("#whoSearch").addEventListener("input", () => { query = $("#whoSearch").value; renderWho(); });
$("#whoSearch").addEventListener("keydown", e => {
  const first = $("#whoList .wtile");
  if (e.key === "Enter" && query.trim() && first) { e.preventDefault(); first.click(); }
  else if (e.key === "ArrowDown" && first) { e.preventDefault(); first.focus(); }
});
/* the arrows walk the tiles (not the player's seek and volume); typing goes to the field */
$("#whoList").addEventListener("keydown", e => {
  const tiles = [...$("#whoList").querySelectorAll(".wtile")], i = tiles.indexOf(document.activeElement);
  if (i < 0 || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key.length === 1 && e.key !== " " && !$("#whoFind").hidden) { e.stopPropagation(); $("#whoSearch").focus(); return; }
  const cols = getComputedStyle($("#whoList")).gridTemplateColumns.split(" ").length;
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[e.key];
  if (!step) return;
  e.preventDefault(); e.stopPropagation();
  if (i + step < 0 && !$("#whoFind").hidden) return $("#whoSearch").focus();
  tiles[Math.max(0, Math.min(tiles.length - 1, i + step))].focus();
});

/* the form adds a name, or edits person p */
function resetForm(p = null) {
  editing = p ? p.id : null;
  pickColor = p ? p.color : COLORS[Object.keys(people).length % COLORS.length];
  pickEmoji = p ? p.emoji : "";
  pickSems = new Set(p ? p.seminars || [] : house.newPerson.groups.filter(s => seminars[s])); other = false; fromList = false; $("#whoOther").value = ""; finishing = false;
  $("#whoName").value = p ? p.name : ""; $("#whoSave").textContent = p ? "Save" : "Add"; $("#whoMsg").textContent = "";
  $("#whoTitle").textContent = p ? `Edit ${p.name}` : "Add a name";
  $("#whoPhrase").value = ""; $("#whoPhrase").hidden = !!p;    /* editing: the pass phrase has its own button */
  paintPhraseBtn(p);
  paintForm();
}

function paintForm() {
  const groups = feat("groups"), mayAdd = house.groups.create === "open" || admin;   /* a new group: anyone, or only the admin */
  $("#whoSemLbl").hidden = $("#whoSems").hidden = !groups;
  $("#whoSemLbl").innerHTML = `${esc(G().one)} <span>pick one or more</span>`;
  $("#whoSems").innerHTML = Object.values(seminars).map(x => `<button type="button" class="${pickSems.has(x.id) ? "on" : ""}" style="--c:${esc(x.color)}"
    aria-pressed="${pickSems.has(x.id)}" data-act="who-sem" data-s="${esc(x.id)}">${esc(x.name)}</button>`).join("")
    + (mayAdd ? `<button type="button" class="${other ? "on" : ""}" aria-pressed="${other}" data-act="who-sem-other">+ New</button>` : "");
  $("#whoOther").hidden = !groups || !mayAdd || !other;
  $("#whoColors").innerHTML = COLORS.map(c => `<button type="button" class="${c === pickColor ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="who-color" data-c="${c}"></button>`).join("");
  paintPreview();
  $("#whoEmoji").innerHTML = EMOJIS.map(e => `<button type="button" class="${e === pickEmoji ? "on" : ""}" aria-label="${e || "Initial"}" data-act="who-emoji" data-e="${e}">${iconFor(e) || e || "Aa"}</button>`).join("");
}

/* the badge being made, as it will look: avatar, then its group tags */
function paintPreview() {
  const name = $("#whoName").value.trim(), typed = $("#whoOther").value.trim();
  $("#whoPreview").innerHTML = avatar({ name: name || "?", color: pickColor, emoji: pickEmoji });
  const tags = [...pickSems].map(sid => semTag(sid)).join("")
    + (other && typed ? `<i class="sem">${esc(typed)}</i>` : "");
  $("#whoTags").innerHTML = tags || (feat("groups") ? `No ${esc(G().a)} yet` : "");
}
$("#whoName").addEventListener("input", paintPreview);
$("#whoOther").addEventListener("input", paintPreview);

$("#whoForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#whoName").value.trim(), typed = $("#whoOther").value.trim();
  if (!name) return $("#whoName").focus();
  const sems = [...pickSems, ...(other && typed ? [typed] : [])], phrase = $("#whoPhrase").value;
  if (!sems.length && isOn("groups") && house.groups.required) return formMsg(`Pick your ${G().a}`);
  try {
    const p = await savePerson(editing, { name, color: pickColor, emoji: pickEmoji, seminars: sems, ...(!editing && phrase.trim() ? { phrase } : {}) });
    if (finishing || !editing) choose(p.id);
    else { closeWho(); renderPeople(); paintMe(); toast("Saved"); }
  } catch (err) { formMsg(errText(err)); }
});
function formMsg(t) { $("#whoMsg").textContent = t; $("#whoMsg").className = "msg err"; }

/* A name without a group, where everyone has to be in one: pick it before the name can be used */
function askSeminar(id) {
  if (!$("#who").classList.contains("open")) openWho();
  resetForm(people[id]); finishing = true; showForm(true);
  $("#whoTitle").textContent = `${people[id].name}: your ${G().a}`;
  $("#whoMsg").textContent = `Pick your ${G().a} to go on`; $("#whoMsg").className = "msg";
}

/* once per page: this device's name has no group yet */
let checked = false;
export function checkSeminar() {
  const p = me();
  if (checked || !p) return;
  checked = true;
  if (needsGroup(p)) askSeminar(p.id);
}

/* ---------- Settings → People ---------- */
export function renderPeople() {
  const cur = myId();
  $("#peopleList").innerHTML = sortedPeople().map(p => `<div class="prow">${avatar(p)}<div class="t">${esc(p.name)} ${semTags(p, "sm")}${p.locked ? `<span class="lock" title="Has a pass phrase">${LOCK}</span>` : ""}${p.id === cur ? ' <span class="me-tag">· this device</span>' : ""}</div>
    <div class="acts"><button data-act="person-phrase" data-id="${esc(p.id)}" title="${p.locked ? "Change or remove the pass phrase" : "Add a pass phrase"}">Phrase</button><button data-act="person-edit" data-id="${esc(p.id)}">Edit</button><button data-act="person-remove" data-id="${esc(p.id)}">Remove</button></div></div>`).join("")
    || '<p class="hint tight">No names yet.</p>';
}

async function remove(id) {
  if (!(await ask(`Remove ${people[id].name}? Their songs stay in the queue.`, { ok: "Remove", danger: true }))) return;
  if (await withAdmin(() => removePerson(id)) === null) return;
  renderPeople(); paintMe();
}

async function resetPhrase(id) {
  const name = people[id].name;
  if (!(await ask(`Take the pass phrase off ${name}? Anyone can then pick the name and set a new one.`, { ok: "Take it off" }))) return;
  try {
    if (await withAdmin(() => api(`api/admin/people/${id}`, { phrase: "" }, "PATCH")) === null) return;
  } catch (e) { return toast(errText(e), false, "error"); }
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
  } catch (e) { toast(errText(e), false, "error"); }
}

function paintPhraseBtn(p) {
  if (!p) return $("#whoPhraseBtn").hidden = true;
  $("#whoPhraseBtn").hidden = false;
  $("#whoPhraseBtn").textContent = p.locked ? "Change or remove the pass phrase" : "Add a pass phrase";
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
on("who-group", el => { group = el.dataset.s; renderWho(); });
on("who-new", () => { resetForm(); $("#whoName").value = query.trim(); paintPreview(); showForm(true); });   /* what was typed to find it */
on("who-back", () => editing && !fromList ? closeWho() : (resetForm(), showForm(false)));
on("person-remove", el => remove(el.dataset.id));
on("person-phrase", el => editPhrase(el.dataset.id));
on("who-phrase", () => editPhrase(editing));
