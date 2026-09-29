/* The main view's pages: Home, Explore (new releases, moods), search, a pasted link, an album /
   playlist / artist page, and History. */
import { $, $$, esc, ago } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { lists, LINK } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import * as icon from "./icons.js";
import { view, seq, back, setNav, bump, setBack, visit, previous } from "./nav.js";
import { askPlay } from "./ask.js";
import { main, toast, closeAll, loading, note, section, backBtn, songRow, card, songCard, dayName } from "./ui.js";
import { toggleCanvas } from "./player.js";

let kind = "songs", lastQuery = "";

/* ---------- Home: the house's own shelves first, then YouTube's ---------- */
export async function showHome() {
  setNav("home"); $("#q").value = ""; setBack(showHome);
  main(loading("Loading"));
  const [mine, yt] = await Promise.all([api("api/forme").catch(() => []), api("api/home").catch(e => ({ error: e }))]);
  if (view !== "home") return;
  let n = 0, html = "";
  for (const s of mine) {
    const key = "fy_" + s.key; lists[key] = s.items;
    html += section(++n, s.title, `<span class="hide-sm">${esc(s.subtitle)} · </span><button class="link" data-act="play-all" data-list="${esc(key)}" data-label="${esc(s.title)}">Play all</button>`)
      + `<div class="shelf">${s.items.map((t, i) => songCard(t, key, i)).join("")}</div>`;
  }
  if (yt.error) html += note(`Could not load YouTube's home: ${esc(yt.error.message)}`);
  else html += yt.map(s => section(++n, s.title) + `<div class="shelf">${s.items.map(card).join("")}</div>`).join("");
  main(html || note("Nothing here yet. Try searching."));
}

/* ---------- Explore: new releases, and moods & genres ---------- */
export async function showExplore() {
  setNav("explore"); $("#q").value = ""; setBack(showExplore);
  main(loading("Loading"));
  let ex;
  try { ex = await api("api/explore"); }
  catch (e) { if (view === "explore") main(note(`Could not load Explore: ${esc(errText(e))}`)); return; }
  if (view !== "explore") return;
  let n = 0;
  main((ex.releases.length ? section(++n, "New releases", "albums") + `<div class="shelf">${ex.releases.map(card).join("")}</div>` : "")
    + ex.moods.map(g => section(++n, g.title) + `<div class="chips">${g.items.map((m, k) =>
      `<button data-act="mood" data-params="${esc(m.params)}" data-title="${esc(m.title)}"><i class="c${k % 3}"></i>${esc(m.title)}</button>`).join("")}</div>`).join(""));
}

async function showMood(params, title) {
  setNav("explore"); setBack(() => showMood(params, title));
  main(loading("Loading"));
  const ps = await api(`api/mood?params=${encodeURIComponent(params)}`).catch(() => null);
  if (view !== "explore") return;
  main(backBtn("Explore", 'data-act="nav" data-v="explore"') + section(1, title, ps ? `${ps.length} playlists` : "")
    + (ps && ps.length ? `<div class="grid">${ps.map(card).join("")}</div>` : note("Nothing here right now.")));
}

/* ---------- search, or a pasted YouTube / YouTube Music link ---------- */
async function openLink(url) {
  lastQuery = url; setNav("search"); $("#tabs").hidden = true; setBack(showHome);
  const my = seq;
  main(loading("Opening the link"));
  try {
    const r = await api(`api/resolve?url=${encodeURIComponent(url)}`);
    if (my !== seq) return;
    if (r.type !== "song") return openItem(r.type, r.id);
    lists.link = [r.track];
    main(section(1, "From your link") + `<div class="list">${songRow(r.track, "link", 0)}</div>`);
  } catch (e) { if (my === seq) main(note(esc(errText(e)))); }
}

async function doSearch() {
  const q = $("#q").value.trim();
  if (!q) return showHome();
  if (LINK.test(q)) return openLink(q);
  lastQuery = q; setNav("search"); $("#tabs").hidden = false; setBack(doSearch);
  main(loading("Searching"));
  try {
    const res = await api(`api/search?q=${encodeURIComponent(q)}&kind=${kind}`);
    if (q !== lastQuery || view !== "search") return;
    if (!res.length) return main(note("No results"));
    if (kind === "songs") { lists.search = res; main(`<div class="list">${res.map((t, i) => songRow(t, "search", i)).join("")}</div>`); }
    else main(`<div class="grid">${res.map(card).join("")}</div>`);
  } catch (e) { main(note(`Search failed: ${esc(e.message)}`)); }
}

/* ---------- an album, playlist or artist page ---------- */
export async function openItem(type, id, goingBack = false) {
  const my = bump();
  visit({ type, id }, goingBack);
  main(loading("Loading")); scrollTo(0, 0);
  try {
    const d = await api(`api/${type}/${encodeURIComponent(id)}`);
    if (my !== seq) return;
    lists.detail = d.tracks;
    const title = esc(d.title || ""), all = `data-list="detail" data-label="${title}"`;
    main(`${backBtn("Back")}
      <div class="hero"><img src="${esc(d.thumb)}" alt=""><div>
        <div class="k">${esc(type)} · ${d.tracks.length} songs</div>
        <h1>${title}</h1><div class="s">${d.artistId ? `<button class="artlink" data-act="open" data-type="artist" data-id="${esc(d.artistId)}">${esc(d.subtitle)}</button>` : esc(d.subtitle)}</div>
        <div class="btns"><button class="btn red" data-act="play-all" ${all}>${icon.PLAYS}Play</button>
          <button class="btn" data-act="play-all" data-mode="next" ${all}>${icon.NEXT}Play next</button>
          <button class="btn" data-act="play-all" data-mode="add" ${all}>${icon.ADD}Add all</button>
          <button class="btn" data-act="save-as-list" data-list="detail" data-label="${esc(d.title || "Playlist")}">${icon.ADD}Save as playlist</button></div>
      </div></div>
      <div class="list">${d.tracks.map((t, i) => songRow(t, "detail", i)).join("")}</div>
      ${d.albums && d.albums.length ? section(2, "Albums") + `<div class="shelf">${d.albums.map(card).join("")}</div>` : ""}`);
  } catch (e) { if (my === seq) main(note(`Could not load: ${esc(errText(e))}`)); }
}

/* A song's artist or album page (kind: "artist" or "album"). Songs saved before tracks carried those
   ids (history, older playlists) ask the server which they are. */
export async function goTo(kind, t) {
  if (!t) return;
  let id = t[kind + "Id"];
  if (!id) try { id = (await api(`api/where/${encodeURIComponent(t.videoId)}`))[kind + "Id"]; } catch {}
  if (!id) return toast(kind === "artist" ? "YouTube Music has no page for this artist" : "Couldn't find this song's album");
  closeAll(); toggleCanvas(false);
  openItem(kind, id);
}

/* ---------- History (shared by everyone) ---------- */
export async function showHistory() {
  setNav("history"); $("#q").value = "";
  main(loading("Loading"));
  const h = await api("api/history?limit=200").catch(() => []);
  if (view !== "history") return;
  lists.history = h;
  const off = h.length ? "" : "disabled";
  let html = section(1, "Recently played", `${h.length} songs · shared by everyone`) +
    `<div class="newform plain"><button class="btn red" data-act="play-all" data-list="history" data-label="History" ${off}>${icon.PLAYS}Play all</button>
     <button class="btn" data-act="play-all" data-mode="add" data-list="history" data-label="History" ${off}>${icon.ADD}Add all</button>
     <button class="btn" data-act="save-as-list" data-list="history" data-label="From history" ${off}>${icon.ADD}Save<span class="hide-sm">&nbsp;as playlist</span></button>
     <button class="btn ghost danger push" data-act="clear-history" ${off}>Clear</button></div>`;
  if (!h.length) html += note("Nothing played yet.");
  let day = "";
  html += '<div class="list">' + h.map((t, i) => {
    const dn = dayName(t.playedAt), head = dn !== day ? `<div class="daygroup">${esc(dn)}</div>` : "";
    day = dn;
    return head + songRow(t, "history", i, { d: ago(t.playedAt), playing: i === 0, by: t.by });
  }).join("") + "</div>";
  main(html);
}

async function clearHistory() {
  if (!confirm("Clear the play history for everyone?")) return;
  await api("api/history", undefined, "DELETE");
  showHistory();
}

/* ---------- wiring ---------- */
on("open", el => openItem(el.dataset.type, el.dataset.id));
on("mood", el => showMood(el.dataset.params, el.dataset.title));
on("back", () => { const p = previous(); p ? openItem(p.type, p.id, true) : back(); });
on("clear-history", clearHistory);
on("add-track", el => askPlay([JSON.parse(el.dataset.track)]));

let typing;
$("#q").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(doSearch, 450); });
$("#q").addEventListener("keydown", e => {
  if (e.key === "Enter") { clearTimeout(typing); doSearch(); e.target.blur(); }
  if (e.key === "Escape") e.target.blur();
});
$("#tabs").addEventListener("click", e => {
  const k = e.target.dataset.k;
  if (!k) return;
  kind = k; $$("#tabs button").forEach(b => b.classList.toggle("on", b === e.target)); doSearch();
});
