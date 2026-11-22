/* Importing a playlist: a file (m3u, CSV, text) picked, dropped on the playlists page or pasted. The
   server finds each song in the background (api/import, about one a second), so the page can be left
   and come back to. Then the review: songs to check and songs not found first; tap a song to hear it,
   pick one of its other matches or leave it out, then save it as a new playlist (one each, when the file
   holds several) or add it to one that exists. What was picked stays here only, until it is saved. */
import { $, esc, plural } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { lists } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { ask } from "../../shared/dialog.js";
import * as icon from "./icons.js";
import { view, seq, setNav } from "./nav.js";
import { main, toast, loading, note, section, backBtn, songRow } from "./ui.js";
import { pickFor, showList, showLists } from "./playlists.js";

const picked = {};                             /* job id -> {row number: a track, or null to leave it out} */
let job = null, openRow = -1, split = true;

export async function showImport() {
  setNav("lists");
  const my = seq;
  main(loading("Loading"));
  const mine = await api("api/import").catch(() => []);
  if (my !== seq) return;
  main(`${backBtn("All playlists", 'data-act="nav" data-v="lists"')}${section(1, "Import a playlist", "m3u · CSV · text")}
    <div class="newform plain"><label class="btn red">${icon.ADD}Pick a file<input type="file" id="impFile" accept=".m3u,.m3u8,.csv,.tsv,.txt,text/*" hidden></label></div>
    <p class="hint tight upnote">Or drop a file anywhere on the playlists page. An m3u, a CSV with a header row (TuneMyMusic, Exportify and the like), or text with one song per line, like "Artist - Title".</p>
    <div class="impform"><textarea id="impText" placeholder="Or paste songs here, one per line"></textarea>
      <div class="newform plain"><input class="field" id="impName" placeholder="Playlist name (optional)" maxlength="80"><button class="btn red" data-act="imp-paste">Find these songs</button></div></div>
    ${mine.length ? section(2, "Your imports") + `<div class="list">${mine.map(j => `<button class="uprow imp" data-act="imp-open" data-id="${esc(j.id)}">
      <div class="t">${esc(j.name)}</div><div class="s">${esc(progress(j))}</div>
      <div class="upbar"><i style="width:${Math.round(j.done / j.total * 100)}%"></i></div></button>`).join("")}</div>` : ""}`);
  $("#impFile").addEventListener("change", e => { const f = e.target.files[0]; e.target.value = ""; if (f) importFile(f); });
}

const progress = j => j.status === "running" ? `Finding songs · ${j.done} of ${j.total}`
  : `Ready to save · ${j.sure} sure${j.unsure ? `, ${j.unsure} to check` : ""}${j.none ? `, ${j.none} not found` : ""}`;

/* most exports are UTF-8; an old m3u is often Windows-1252 */
async function importFile(file) {
  const buf = await file.arrayBuffer();
  let text;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch { text = new TextDecoder("windows-1252").decode(buf); }
  start(text, file.name.replace(/\.[^.]+$/, ""));
}

async function start(text, name) {
  try { showJob((await api("api/import", { text, name })).id); }
  catch (e) { toast(errText(e), false, "error"); }
}

/* ---------- the review ---------- */
async function showJob(id) {
  setNav("lists");
  const my = seq;
  if (job?.id !== id) { openRow = -1; split = true; }
  main(loading("Loading"));
  for (let last = -1; my === seq;) {
    try { job = await api(`api/import/${id}`); }
    catch (e) { if (my === seq) { toast(errText(e), false, "error"); showImport(); } return; }
    if (my !== seq) return;
    if (job.done !== last || job.status !== "running") render();
    if (job.status !== "running") return;
    last = job.done;
    await new Promise(r => setTimeout(r, 2000));
  }
}

const mine = () => (picked[job.id] ||= {});
const trackOf = i => i in mine() ? mine()[i] : job.rows[i].track;
/* checking first, then not found, then the sure ones; in the file's order while it is still finding */
const ORDER = { unsure: 0, none: 1, sure: 2, wait: 3 };
const order = () => job.rows.map((_, i) => i).sort((a, b) => job.status === "running" ? a - b : ORDER[job.rows[a].state] - ORDER[job.rows[b].state] || a - b);
const LABEL = { unsure: "Check this", none: "Not found", sure: "", wait: "" };

function row(i) {
  const r = job.rows[i], t = trackOf(i), chosen = i in mine();
  const label = chosen ? (t ? "Picked" : "Left out") : LABEL[r.state];
  const src = `<div class="src"><span>${job.names.length > 1 && r.playlist ? esc(r.playlist) + " · " : ""}${esc(r.text)}</span>${label ? `<b>${label}</b>` : ""}</div>`;
  if (r.state === "wait") return "";
  const acts = `${r.alts.length ? `<button title="Other matches" aria-label="Other matches" aria-expanded="${openRow === i}" data-act="imp-alts" data-i="${i}">${icon.EDIT}</button>` : ""}
    ${t ? `<button title="Leave out" aria-label="Leave out" data-act="imp-use" data-i="${i}" data-a="-1">${icon.X}</button>`
      : r.track ? `<button title="Put back" aria-label="Put back" data-act="imp-use" data-i="${i}" data-a="-2">${icon.ADD}</button>` : ""}`;
  const alts = openRow === i ? `<div class="alts">${r.alts.map((a, k) => songRow(a, "impalt", k, { num: k + 1, next: false,
    acts: `<button title="Use this one" aria-label="Use this one" data-act="imp-use" data-i="${i}" data-a="${k}">${icon.ADD}</button>` })).join("")}</div>` : "";
  return `<div class="improw ${chosen ? (t ? "sure" : "out") : r.state}">${src}${t ? songRow(t, "imp", i, { next: false, acts })
    : `<div class="row"><span class="n">${String(i + 1).padStart(2, "0")}</span><span></span><div class="meta"><div class="s">${esc(r.error || "Nothing on YouTube Music looked like it")}</div></div><span class="d"></span><div class="acts">${acts}</div></div>`}${alts}</div>`;
}

function render() {
  if (view !== "lists" || !job) return;
  lists.imp = job.rows.map((_, i) => trackOf(i));
  lists.impalt = openRow >= 0 ? job.rows[openRow].alts : [];
  const running = job.status === "running", saving = tracksFor().length, many = job.names.length > 1;
  const head = running ? `<p class="hint tight upnote">Finding songs · ${job.done} of ${job.total}. This keeps going if you leave the page; come back to it under Import.</p>
      <div class="uprow"><div class="upbar"><i style="width:${Math.round(job.done / job.total * 100)}%"></i></div></div>
      <div class="newform plain"><button class="btn ghost danger" data-act="imp-drop">Cancel</button></div>`
    : `<p class="hint tight upnote">${plural(job.total, "song")}: ${job.sure} found for sure${job.unsure ? `, ${job.unsure} to check` : ""}${job.none ? `, ${job.none} not found` : ""}.
        Tap a song to hear it.${job.unsure ? " Songs to check are saved as they are unless you pick another match or leave them out." : ""}</p>
      ${many ? `<div class="newform plain"><div class="seg2" role="group" aria-label="Playlists">${[[true, `One playlist each (${job.names.length})`], [false, "All in one"]]
        .map(([v, l]) => `<button class="${v === split ? "on" : ""}" aria-pressed="${v === split}" data-act="imp-split" data-v="${v}">${l}</button>`).join("")}</div></div>` : ""}
      <div class="newform plain">${many && split ? `<button class="btn red" data-act="imp-save-each" ${saving ? "" : "disabled"}>Save ${plural(job.names.length, "playlist")}</button>`
        : `<input class="field" id="impSaveName" value="${esc(job.name)}" maxlength="80" aria-label="Playlist name">
          <button class="btn red" data-act="imp-save" ${saving ? "" : "disabled"}>Save ${plural(saving, "song")}</button>
          <button class="btn" data-act="imp-add-to" ${saving ? "" : "disabled"}>Add to a playlist</button>`}
        <button class="btn ghost danger" data-act="imp-drop">Discard</button></div>`;
  main(`${backBtn("Import", 'data-act="import"')}${section(1, job.name, running ? "finding songs" : "ready to save")}${head}
    <div class="list imp">${order().map(row).join("") || note("Looking for the first song")}</div>`);
}

/* the songs to save, in the file's order, each once; `name`: only those from that playlist in the file */
function tracksFor(name) {
  const seen = new Set();
  return job.rows.map((r, i) => (name === undefined || r.playlist === name) && trackOf(i)).filter(t => t && !seen.has(t.videoId) && seen.add(t.videoId));
}

async function finish(text) {
  await api(`api/import/${job.id}`, undefined, "DELETE").catch(() => {});
  delete picked[job.id]; job = null;
  if (text) toast(text);
}

async function save() {
  const name = $("#impSaveName").value.trim() || job.name;
  try {
    const p = await api("api/lists", { name, tracks: tracksFor() });
    await finish(`Saved "${p.name}" · ${plural(p.tracks.length, "song")}`);
    showList(p.id);
  } catch (e) { toast(errText(e), false, "error"); }
}

async function saveEach() {
  try {
    for (const name of job.names) {
      const tracks = tracksFor(name);
      if (tracks.length) await api("api/lists", { name, tracks });
    }
    await finish(`Saved ${plural(job.names.length, "playlist")}`);
    showLists();
  } catch (e) { toast(errText(e), false, "error"); }
}

/* ---------- files dropped on the playlists page ---------- */
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
addEventListener("dragover", e => { if (view === "lists" && hasFiles(e)) { e.preventDefault(); $("#view").classList.add("dropping"); } });
addEventListener("drop", e => {
  if (view !== "lists" || !hasFiles(e)) return;
  e.preventDefault();
  $("#view").classList.remove("dropping");
  const f = e.dataTransfer.files[0];
  if (f) importFile(f);
});

/* ---------- wiring ---------- */
on("import", showImport);
on("imp-open", el => showJob(el.dataset.id));
on("imp-paste", () => {
  const text = $("#impText").value;
  if (!text.trim()) return $("#impText").focus();
  start(text, $("#impName").value.trim());
});
on("imp-alts", el => { openRow = openRow === +el.dataset.i ? -1 : +el.dataset.i; render(); });
on("imp-use", el => {
  const i = +el.dataset.i, a = +el.dataset.a;
  if (a === -2) delete mine()[i];                                  /* put back: the match it found */
  else mine()[i] = a === -1 ? null : job.rows[i].alts[a];
  if (a >= 0) openRow = -1;
  render();
});
on("imp-split", el => { split = el.dataset.v === "true"; render(); });
on("imp-save", save);
on("imp-save-each", saveEach);
on("imp-add-to", () => pickFor(tracksFor(), { name: job.name, done: () => finish("").then(showLists) }));
on("imp-drop", async () => {
  if (job.status !== "running" && !(await ask(`Discard the import of "${job.name}"? Nothing has been saved.`, { ok: "Discard", danger: true }))) return;
  await finish(job.status === "running" ? "Import cancelled" : "Import discarded");
  showImport();
});
