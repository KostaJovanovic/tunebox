/* Tunebox playlists (shared, anyone can edit; "liked" is the Liked songs list), and the
   "Add to playlist" pop-up. */
import { $, esc, plural } from "../../shared/dom.js";
import { people, seminars, avatar, semTag } from "../../shared/people.js";
import { api, errText } from "../../shared/api.js";
import { lists } from "../../shared/playback.js";
import { askPlay } from "./ask.js";
import { on } from "../../shared/actions.js";
import * as icon from "./icons.js";
import { view, seq, setNav } from "./nav.js";
import { main, toast, loading, note, section, backBtn, songRow, mosaic, dayName, at, syncScrim } from "./ui.js";

let openList = null;                           /* the id of the playlist on screen */
let likedBy = "";                              /* Liked songs shows only these: "" all, a person id, or "sem:<seminar id>" */

export async function showLists() {
  setNav("lists"); $("#q").value = ""; openList = null;
  const my = seq;
  main(loading("Loading"));
  const ls = await api("api/lists").catch(() => []);
  if (my !== seq) return;
  main(section(1, "Tunebox playlists", "shared · anyone can edit") +
    `<div class="grid"><button class="card new" data-act="list-new"><div class="blank">${icon.ADD}</div><div class="t">New playlist</div><div class="s">Start empty</div></button>` +
    ls.map(p => `<button class="card" data-act="list-open" data-id="${esc(p.id)}">${p.liked && !p.thumbs.length ? `<div class="blank heart">${icon.HEART}</div>` : mosaic(p.thumbs)}<div class="t">${esc(p.name)}</div>
      <div class="s"><i class="kind ${p.liked ? "liked" : "mine"}"></i>${plural(p.count, "song")}</div></button>`).join("") + "</div>");
}

function newListForm() {
  if ($("#newList")) return $("#newList input").focus();
  $("#view .sec").insertAdjacentHTML("afterend", `<form class="newform" id="newList">
    <input class="field" placeholder="Playlist name" maxlength="80" required><button class="btn red">Create</button></form>`);
  $("#newList").addEventListener("submit", async e => {
    e.preventDefault();
    const name = $("#newList input").value.trim();
    if (!name) return;
    const p = await api("api/lists", { name });
    showList(p.id);
  });
  $("#newList input").focus();
}

export async function showList(id) {
  setNav("lists"); openList = id;
  main(loading("Loading"));
  let p;
  try { p = await api(`api/lists/${id}`); } catch { return showLists(); }
  if (openList !== id) return;
  renderList(p);
}

/* the Liked list is on screen and just changed */
export function likesChanged() { if (openList === "liked" && view === "lists") showList("liked"); }

/* Liked songs: who liked what, as chips to show one person's (or one seminar's) likes */
function likers(tracks) {
  const who = new Set(tracks.flatMap(t => t.likedBy || []).filter(id => people[id]));
  const sems = new Set([...who].flatMap(id => people[id].seminars || []).filter(s => seminars[s]));
  if (!who.size) return "";
  const chip = (v, html) => `<button class="${likedBy === v ? "on" : ""}" aria-pressed="${likedBy === v}" data-act="liked-by" data-v="${esc(v)}">${html}</button>`;
  return `<div class="likers">${chip("", "Everyone")}${[...who].sort((a, b) => people[a].name.localeCompare(people[b].name))
    .map(id => chip(id, avatar(people[id], "sm") + esc(people[id].name))).join("")}${[...sems].map(s => chip("sem:" + s, semTag(s))).join("")}</div>`;
}
const likedFilter = t => !likedBy ? true : likedBy.startsWith("sem:")
  ? (t.likedBy || []).some(id => people[id]?.seminars?.includes(likedBy.slice(4))) : (t.likedBy || []).includes(likedBy);

function renderList(p, renaming = false) {
  if (p.id !== lists.mineMeta?.id) likedBy = "";
  const isLiked = p.id === "liked", shown = isLiked ? p.tracks.filter(likedFilter) : p.tracks, filtered = shown.length !== p.tracks.length;
  lists.mine = shown; lists.mineMeta = p;
  const n = shown.length, off = n ? "" : "disabled";
  const all = `data-list="mine" data-label="${esc(p.name)}" ${off}`;
  const title = renaming ? `<input class="name" id="rename" value="${esc(p.name)}" maxlength="80">` : `<h1>${esc(p.name)}</h1>`;
  const buttons = renaming ? `<button class="btn red" data-act="list-rename-save">Save name</button><button class="btn" data-act="list-rename-cancel">Cancel</button>`
    : `<button class="btn red" data-act="play-all" ${all}>${icon.PLAYS}Play</button>
        <button class="btn" data-act="play-all" data-mode="next" ${all}>${icon.NEXT}Play next</button>
        <button class="btn" data-act="play-all" data-mode="add" ${all}>${icon.ADD}Add all</button>
        <button class="btn" data-act="list-shuffle" ${off}>${icon.SHUFFLE}Shuffle</button>
        ${isLiked ? "" : `<button class="btn ghost" data-act="list-rename">Rename</button>
        <button class="btn ghost danger" data-act="list-delete">Delete</button>`}`;
  const row = (t, i) => songRow(t, "mine", i, { likers: isLiked ? t.likedBy || [] : null, acts:
    (filtered ? "" : `<button title="Move up" aria-label="Move up" data-act="list-move" data-i="${i}" data-d="-1" ${i ? "" : "disabled"}>${icon.UP}</button>
     <button title="Move down" aria-label="Move down" data-act="list-move" data-i="${i}" data-d="1" ${i < n - 1 ? "" : "disabled"}>${icon.DOWN}</button>`) +
     `
     <button class="wide" title="Play next" aria-label="Play next" data-act="song" data-mode="next" ${at("mine", i)}>${icon.NEXT}</button>
     <button title="Remove from playlist" aria-label="Remove from playlist" data-act="list-move" data-i="${i}" data-d="0">${icon.X}</button>` });
  main(`${backBtn("All playlists", 'data-act="nav" data-v="lists"')}
    <div class="hero">${mosaic(p.tracks.map(t => t.thumb))}<div>
      <div class="k">${isLiked ? "Liked songs" : "Tunebox playlist"} · ${filtered ? `${n} of ${plural(p.tracks.length, "song")}` : plural(n, "song")}</div>${title}
      <div class="s">Shared · updated ${esc(dayName(p.updated).toLowerCase())}</div>
      <div class="btns">${buttons}</div>
    </div></div>${isLiked ? likers(p.tracks) : ""}
    <div class="list">${n ? shown.map(row).join("")
      : note(isLiked ? "Nothing liked yet. Tap the heart on any song to add it here." : "Empty. Use the playlist button on any song to add it here.")}</div>`);
  if (renaming) {
    const r = $("#rename");
    r.addEventListener("keydown", e => { if (e.key === "Enter") doRename(); if (e.key === "Escape") renderList(lists.mineMeta); });
    r.focus(); r.select();
  }
}

async function patchList(body, sub = "") {
  const id = lists.mineMeta.id;
  try { renderList(await api(`api/lists/${id}${sub}`, body, "PATCH")); }
  catch (e) { toast(errText(e)); showList(id); }
}
function doRename() { const v = $("#rename").value.trim(); if (v) patchList({ name: v }); }

/* d: -1 up, 1 down, 0 remove. By videoId on the server, so someone else's edit in between is kept. */
export const removeFromList = i => moveTrack(i, 0);
function moveTrack(i, d) {
  const videoId = lists.mine[i].videoId;
  patchList(d ? { op: "move", videoId, at: i, to: i + d } : { op: "remove", videoId, at: i }, "/tracks");
}

async function deleteList() {
  if (!confirm(`Delete "${lists.mineMeta.name}" for everyone?`)) return;
  await api(`api/lists/${lists.mineMeta.id}`, undefined, "DELETE");
  toast("Playlist deleted"); showLists();
}

function shuffleList() {
  const t = [...lists.mine];
  for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; }
  askPlay(t, `${lists.mineMeta.name} (shuffled)`);
}

async function saveAsList(key, name) {
  const p = await api("api/lists", { name, tracks: lists[key] || [] });
  toast(`Saved "${p.name}" · ${p.tracks.length} songs`);
}

/* ---------- the "Add to playlist" pop-up ---------- */
let pickTrack = null;
export async function pickFor(track) {
  pickTrack = track;
  $("#pickList").innerHTML = loading("Loading");
  $("#picker").classList.add("open"); syncScrim();     /* on top: the queue drawer may stay open under it */
  const ls = await api("api/lists").catch(() => []);
  $("#pickList").innerHTML = ls.length ? ls.map(p => `<button class="pick" data-act="pick-add" data-id="${esc(p.id)}">${mosaic(p.thumbs)}
    <div class="min0"><div class="t">${esc(p.name)}</div><div class="s">${plural(p.count, "song")}</div></div><span class="ok"></span></button>`).join("")
    : note("No playlists yet. Name one above.");
  if (!ls.length) $("#pickName").focus();
}
function closePicker() { $("#picker").classList.remove("open"); syncScrim(); }

async function pickAdd(btn) {
  const r = await api(`api/lists/${btn.dataset.id}/tracks`, { track: pickTrack });
  btn.querySelector(".ok").textContent = r.duplicate ? "Already in" : "Added";
  toast(r.duplicate ? "Already in that playlist" : `Added · ${r.count} songs`);
  setTimeout(closePicker, 450);
}

$("#pickForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#pickName").value.trim();
  if (!name) return;
  const p = await api("api/lists", { name, tracks: [pickTrack] });
  $("#pickName").value = ""; toast(`Created "${p.name}"`); closePicker();
});

/* ---------- wiring ---------- */
on("list-new", newListForm);
on("liked-by", el => { likedBy = el.dataset.v; renderList(lists.mineMeta); });
on("list-open", el => showList(el.dataset.id));
on("list-move", el => moveTrack(+el.dataset.i, +el.dataset.d));
on("list-shuffle", shuffleList);
on("list-rename", () => renderList(lists.mineMeta, true));
on("list-rename-save", doRename);
on("list-rename-cancel", () => renderList(lists.mineMeta));
on("list-delete", deleteList);
on("save-as-list", el => saveAsList(el.dataset.list, el.dataset.label));
on("pick", el => pickFor(lists[el.dataset.list][+el.dataset.i]));
on("pick-add", pickAdd);
on("picker-close", closePicker);
