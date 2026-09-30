/* People: who's listening on this device. The name is picked once per device (cookie tb_who, which the
   server reads to know who added a song). Anyone can add names; a name with a pass phrase can only be
   picked or changed on a device that typed it. Removing a name is the admin's. */
import { cookie, esc, setCookie } from "./dom.js";
import { api } from "./api.js";
import { feat } from "./house.js";

export const COLORS = ["#E63B2E", "#EE6A1F", "#F2C230", "#1E8F5A", "#1F5FBF", "#6A4BC4", "#C8327A", "#5C5953"];
export const EMOJIS = ["", "🎸", "🎧", "🎹", "🥁", "🐱", "🐶", "🦊", "🐻", "🌻", "🚀", "⭐", "🍕", "⚽"];
const DARK_ON = new Set(["#EE6A1F", "#F2C230"]);   /* light colours get dark text */

export let people = {};                        /* {id: {id, name, color, emoji, seminars: [seminar id]}} */
export let seminars = {};                      /* {id: {id, name, color}}: the house's groups ("seminars" in the code) */
let peopleRev = null;

export const myId = () => cookie("tb_who");
/* this device's name; a name with a pass phrase only once this device has typed it (p.mine) */
export const me = () => { const p = people[myId()]; return p && (!p.locked || p.mine) ? p : null; };
export const sortedPeople = () => Object.values(people).sort((a, b) => a.name.localeCompare(b.name));

/* Reloads the names when the server says they changed (state.peopleRev); true if they did */
export async function syncPeople(rev) {
  if (rev === peopleRev) return false;
  try {
    const [ps, ss] = await Promise.all([api("api/people"), api("api/seminars")]);
    people = Object.fromEntries(ps.map(p => [p.id, p])); seminars = Object.fromEntries(ss.map(x => [x.id, x]));
    peopleRev = rev; return true;
  } catch { return false; }
}

export function setMe(id) { setCookie("tb_who", id); }

/* add (no id) or edit; returns the saved person */
export async function savePerson(id, fields) {
  const p = await api(id ? `api/people/${id}` : "api/people", fields, id ? "PATCH" : "POST");
  people[p.id] = p;
  return p;
}

/* this device knows the name's pass phrase: the server hands it a key (cookie) */
export async function unlockPerson(id, phrase) {
  await api(`api/people/${id}/unlock`, { phrase });
  people[id].mine = true;
}

export async function removePerson(id) {
  await api(`api/admin/people/${id}?mode=keep`, undefined, "DELETE");
  delete people[id];
}

/* A round badge in the person's colour with their emoji or initial */
export function avatar(p, cls = "") {
  if (!p) return `<i class="av none ${cls}">?</i>`;
  return `<i class="av ${cls}${DARK_ON.has(p.color) ? " dark" : ""}" style="background:${esc(p.color)}" title="${esc(p.name)}">${esc(p.emoji || p.name.slice(0, 1))}</i>`;
}

/* A group's tag, in its colour */
export function semTag(sid, cls = "") {
  const x = feat("groups") && seminars[sid];
  return x ? `<i class="sem ${cls}${DARK_ON.has(x.color) ? " dark" : ""}" style="background:${esc(x.color)}">${esc(x.name)}</i>` : "";
}
export const semTags = (p, cls = "") => (p?.seminars || []).map(sid => semTag(sid, cls)).join("");

/* The small badge on a queued song: who added it (and their groups), or a dot for the radio */
export const byChip = id => id === "radio" ? `<i class="av sm radio" title="Radio">•</i>` : people[id] && feat("people") ? avatar(people[id], "sm") + semTags(people[id], "sm") : "";
