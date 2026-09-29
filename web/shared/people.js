/* People: who's listening on this device. The name is picked once per device (cookie tb_who, which the
   server reads to know who added a song). Anyone can add, rename or remove names. */
import { cookie, esc, setCookie } from "./dom.js";
import { api } from "./api.js";

export const COLORS = ["#E63B2E", "#EE6A1F", "#F2C230", "#1E8F5A", "#1F5FBF", "#6A4BC4", "#C8327A", "#5C5953"];
export const EMOJIS = ["", "🎸", "🎧", "🎹", "🥁", "🐱", "🐶", "🦊", "🐻", "🌻", "🚀", "⭐", "🍕", "⚽"];
const DARK_ON = new Set(["#EE6A1F", "#F2C230"]);   /* light colours get dark text */

export let people = {};                        /* {id: {id, name, color, emoji}} */
let peopleRev = null;

export const myId = () => cookie("tb_who");
export const me = () => people[myId()] || null;
export const sortedPeople = () => Object.values(people).sort((a, b) => a.name.localeCompare(b.name));

/* Reloads the names when the server says they changed (state.peopleRev); true if they did */
export async function syncPeople(rev) {
  if (rev === peopleRev) return false;
  try { people = Object.fromEntries((await api("api/people")).map(p => [p.id, p])); peopleRev = rev; return true; }
  catch { return false; }
}

export function setMe(id) { setCookie("tb_who", id); }

/* add (no id) or edit; returns the saved person */
export async function savePerson(id, fields) {
  const p = await api(id ? `api/people/${id}` : "api/people", fields, id ? "PATCH" : "POST");
  people[p.id] = p;
  return p;
}

export async function removePerson(id) {
  await api(`api/people/${id}`, undefined, "DELETE");
  delete people[id];
}

/* A round badge in the person's colour with their emoji or initial */
export function avatar(p, cls = "") {
  if (!p) return `<i class="av none ${cls}">?</i>`;
  return `<i class="av ${cls}${DARK_ON.has(p.color) ? " dark" : ""}" style="background:${esc(p.color)}" title="${esc(p.name)}">${esc(p.emoji || p.name.slice(0, 1))}</i>`;
}

/* The small badge on a queued song: who added it, or a dot for the radio */
export const byChip = id => id === "radio" ? `<i class="av sm radio" title="Radio">•</i>` : people[id] ? avatar(people[id], "sm") : "";
