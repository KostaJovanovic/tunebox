/* The Local page: the songs people uploaded to this Tunebox. Anyone with a name adds files (the button,
   or dropped onto the page), one request per file with its progress shown; whoever uploaded a song, and
   the admin, can change its details and cover or remove it. */
import { $, esc, plural, size } from "../../shared/dom.js";
import { api, errText, needName } from "../../shared/api.js";
import { lists, poll } from "../../shared/playback.js";
import { people, me } from "../../shared/people.js";
import { isOn, feat } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import * as icon from "./icons.js";
import { view, seq, setNav } from "./nav.js";
import { main, toast, loading, note, section, songRow, syncScrim, onCloseAll } from "./ui.js";
import { ask } from "../../shared/dialog.js";

const SORTS = { added: ["Newest", s => -s.at], title: ["Title", s => s.title.toLowerCase()], artist: ["Artist", s => s.artist.toLowerCase()],
  who: ["Who added it", s => (people[s.by]?.name || "").toLowerCase()] };
let all = [], info = { maxMB: 200, room: 0, used: 0 };
let sort = "added", flip = false;              /* flip: the other way round (a second tap on the same order) */
let ups = [];                                  /* uploads in this visit: {name, state, note, part} */
let busy = false;

export async function showLocal() {
  setNav("local"); $("#q").value = "";
  const my = seq;
  if (!all.length) main(loading("Loading"));
  try { await load(); } catch (e) { if (my === seq) main(note(esc(errText(e)))); return; }
  if (my === seq) render();
}

async function load() {
  const r = await api("api/local");
  all = r.songs; info = r;
}

function render() {
  if (view !== "local") return;
  const by = SORTS[sort][1], shown = [...all].sort((a, b) => (by(a) < by(b) ? -1 : by(a) > by(b) ? 1 : 0) * (flip ? -1 : 1));
  lists.local = shown;
  const off = shown.length ? "" : "disabled";
  main(section(1, "Local songs", `${plural(all.length, "song")} · ${size(info.used)}`)
    + `<div class="newform plain"><label class="btn red">${icon.ADD}Add files<input type="file" id="localFiles" accept="audio/*,.flac,.opus,.wma,.ape,.wv,.mka,.m4a,.aiff,.aif" multiple hidden></label>
      <button class="btn" data-act="play-all" data-list="local" data-label="Local songs" ${off}>${icon.PLAYS}Play all</button>
      <button class="btn" data-act="play-all" data-mode="add" data-list="local" data-label="Local songs" ${off}>${icon.ADD}Add all</button></div>
    <p class="hint tight upnote">Or drop files anywhere on this page. Up to ${info.maxMB} MB each, ${size(info.room)} of room left. mp3, FLAC, m4a, Ogg and Opus are kept as they are; WAV and AIFF become FLAC, anything else Opus.</p>
    <div id="uploads">${upRows()}</div>
    ${all.length > 1 ? `<div class="likers">${Object.entries(SORTS).filter(([k]) => k !== "who" || feat("people")).map(([k, [name]]) => `<button class="${k === sort ? "on" : ""}" aria-pressed="${k === sort}" data-act="local-sort" data-k="${k}">${name}${k === sort ? (flip ? " ↑" : " ↓") : ""}</button>`).join("")}</div>` : ""}
    <div class="list">${shown.map((t, i) => songRow(t, "local", i, { by: t.by, cls: t.mine ? "own" : "", extra: t.mine ? `<button title="Edit" aria-label="Edit" data-act="local-edit" data-i="${i}">${icon.EDIT}</button>
      <button title="Remove" aria-label="Remove" data-act="local-remove" data-i="${i}">${icon.X}</button>` : "" })).join("")
      || note("Nothing here yet. Add the songs YouTube doesn't have.")}</div>`);
  $("#localFiles").addEventListener("change", e => { add([...e.target.files]); e.target.value = ""; });
}

/* ---------- uploading ---------- */
const upRows = () => ups.map(u => `<div class="uprow ${u.state}"><div class="t">${esc(u.name)}</div><div class="s">${esc(u.note)}</div>
  <div class="upbar"><i style="width:${Math.round(u.part * 100)}%"></i></div></div>`).join("");
function paintUps() { if (view === "local" && $("#uploads")) $("#uploads").innerHTML = upRows(); }

function send(file, u) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "api/local/upload?name=" + encodeURIComponent(file.name));
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = e => { if (e.lengthComputable) { u.part = e.loaded / e.total; u.note = u.part < 1 ? `${Math.round(u.part * 100)}%` : "Reading it…"; paintUps(); } };
    x.onload = () => {
      let r = {};
      try { r = JSON.parse(x.responseText); } catch {}
      x.status < 300 ? resolve(r) : reject(new Error(r.detail === "pick" ? "Pick your name first" : r.detail || `The server said ${x.status}`));
    };
    x.onerror = () => reject(new Error("The upload was cut off"));
    x.send(file);
  });
}

/* one file at a time: the server converts one at a time too */
async function add(files) {
  if (!files.length) return;
  if (isOn("people") && !me() && !await needName()) return toast("Pick your name first");
  const mine = files.map(f => ({ file: f, name: f.name, state: "wait", note: "Waiting", part: 0 }));
  ups = [...ups.filter(u => u.state !== "done"), ...mine]; paintUps();
  if (busy) return;                            /* the loop below picks these up */
  busy = true;
  let added = 0;
  for (let u; (u = ups.find(x => x.state === "wait"));) {
    u.state = "go"; u.note = "0%"; paintUps();
    try {
      if (u.file.size > info.maxMB * 1048576) throw new Error(`Too big: a file can be ${info.maxMB} MB at most`);
      if (u.file.size > info.room) throw new Error("There is no room left for local songs");
      const s = await send(u.file, u);
      u.state = "done"; u.part = 1; u.note = `Added as "${s.title}"${s.was !== s.ext ? ` · now ${s.ext.toUpperCase()}` : ""}`; added++;
      info.room -= s.size;
    } catch (e) { u.state = "bad"; u.note = errText(e); }
    u.file = null; paintUps();
  }
  busy = false;
  if (added) { toast(`Added ${plural(added, "song")}`); await load().catch(() => {}); render(); }
}

/* files dropped anywhere on the Local page */
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
addEventListener("dragover", e => { if (view === "local" && hasFiles(e)) { e.preventDefault(); $("#view").classList.add("dropping"); } });
addEventListener("dragleave", e => { if (!e.relatedTarget) $("#view").classList.remove("dropping"); });
addEventListener("drop", e => {
  $("#view").classList.remove("dropping");
  if (view !== "local" || !hasFiles(e)) return;
  e.preventDefault();
  add([...e.dataTransfer.files]);
});

/* ---------- changing and removing ---------- */
let editing = null;
function openEdit(t) {
  editing = t;
  $("#leTitle").value = t.title; $("#leArtist").value = t.artist; $("#leAlbum").value = t.album;
  $("#leCover").src = t.thumb || ""; $("#leFile").value = ""; $("#leMsg").textContent = "";
  $("#localEdit").classList.add("open"); syncScrim();
  setTimeout(() => $("#leTitle").focus(), 50);
}
function closeEdit() { $("#localEdit").classList.remove("open"); syncScrim(); editing = null; }
onCloseAll(() => { editing = null; });

$("#leFile").addEventListener("change", e => { const f = e.target.files[0]; if (f) $("#leCover").src = URL.createObjectURL(f); });
$("#localForm").addEventListener("submit", async e => {
  e.preventDefault();
  const t = editing, id = t.videoId.slice(6), pic = $("#leFile").files[0];
  const title = $("#leTitle").value.trim();
  if (!title) return $("#leTitle").focus();
  try {
    await api(`api/local/${id}`, { title, artist: $("#leArtist").value, album: $("#leAlbum").value }, "PATCH");
    if (pic) {
      const r = await fetch(`api/local/${id}/cover`, { method: "POST", headers: { "Content-Type": pic.type || "image/jpeg" }, body: pic });
      if (!r.ok) throw new Error(await r.text());
    }
  } catch (err) { $("#leMsg").textContent = errText(err); $("#leMsg").className = "msg err"; return; }
  closeEdit(); toast("Saved"); poll();
  await load().catch(() => {}); render();
});

async function remove(t) {
  if (!(await ask(`Remove "${t.title}" from this Tunebox? The file is deleted, and the song leaves every playlist.`, { ok: "Remove", danger: true }))) return;
  try { await api(`api/local/${t.videoId.slice(6)}`, undefined, "DELETE"); } catch (e) { return toast(errText(e), false, "error"); }
  toast("Removed"); poll();
  await load().catch(() => {}); render();
}

on("local-sort", el => { if (sort === el.dataset.k) flip = !flip; else { sort = el.dataset.k; flip = false; } render(); });
on("local-edit", el => openEdit(lists.local[+el.dataset.i]));
on("local-edit-close", closeEdit);
on("local-remove", el => remove(lists.local[+el.dataset.i]));
