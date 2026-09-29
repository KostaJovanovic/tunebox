/* The main view's pages: Home, Explore, search, a pasted link, an album / playlist / artist page, and
   Liked songs. `page` says which is on screen, so one that finishes loading late doesn't take over. */
import { $, $$, esc, plural } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { lists, LINK } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { askPlay } from "./ask.js";
import { spinner, empty, songRow, card, songCard } from "./ui.js";

export let page = "home";                      /* home, explore, link, search, item or liked */
let kind = "songs", lastQuery = "", navSeq = 0;
let back = () => showHome();                   /* where Back on an album / playlist / artist page goes */
const main = html => { $("#view").innerHTML = html; };
function go(p, backTo) { page = p; if (backTo) back = backTo; }

export async function showHome() {
  $("#tabs").hidden = true; $("#q").value = ""; go("home", showHome);
  main(spinner("Loading"));
  const [mine, yt] = await Promise.all([api("api/forme").catch(() => []), api("api/home").catch(e => ({ error: e }))]);
  if (page !== "home") return;
  let html = "";
  for (const s of mine) {                      /* ours first: the house's own shelves */
    const key = "fy_" + s.key; lists[key] = s.items;
    html += `<h2 class="shelfhead">${esc(s.title)} <small>${esc(s.subtitle)}</small><button data-act="play-all" data-list="${esc(key)}" data-label="${esc(s.title)}">Play all</button></h2>
      <div class="shelf">${s.items.map((t, i) => songCard(t, key, i)).join("")}</div>`;
  }
  if (yt.error) html += empty(`Could not load YouTube's home: ${esc(yt.error.message)}`);
  else html += yt.map(s => `<h2>${esc(s.title)}</h2><div class="shelf">${s.items.map(card).join("")}</div>`).join("");
  main(html || empty("Nothing here yet. Try searching."));
}

/* ---------- Explore: new releases, and moods & genres ---------- */
export async function showExplore() {
  $("#tabs").hidden = true; $("#q").value = ""; go("explore", showExplore);
  main(spinner("Loading"));
  let ex;
  try { ex = await api("api/explore"); }
  catch (e) { if (page === "explore") main(empty(`Could not load Explore: ${esc(errText(e))}`)); return; }
  if (page !== "explore") return;
  main((ex.releases.length ? `<h2>New releases</h2><div class="shelf">${ex.releases.map(card).join("")}</div>` : "")
    + ex.moods.map(g => `<h2>${esc(g.title)}</h2><div class="chips">${g.items.map(m =>
      `<button data-act="mood" data-params="${esc(m.params)}" data-title="${esc(m.title)}">${esc(m.title)}</button>`).join("")}</div>`).join(""));
}

async function showMood(params, title) {
  go("explore", () => showMood(params, title));
  main(spinner("Loading"));
  const ps = await api(`api/mood?params=${encodeURIComponent(params)}`).catch(() => null);
  if (page !== "explore") return;
  main(`<button class="back" data-act="explore">← Explore</button><h2>${esc(title)}</h2>`
    + (ps && ps.length ? `<div class="grid">${ps.map(card).join("")}</div>` : empty("Nothing here right now.")));
}

/* ---------- search, or a pasted YouTube / YouTube Music link ---------- */
async function openLink(url) {
  lastQuery = url; $("#tabs").hidden = true; go("link", showHome);
  main(spinner("Opening the link"));
  try {
    const r = await api(`api/resolve?url=${encodeURIComponent(url)}`);
    if (lastQuery !== url || page !== "link") return;
    if (r.type !== "song") return openItem(r.type, r.id);
    lists.link = [r.track];
    main(`<h2>From your link</h2><div class="list">${songRow(r.track, "link", 0)}</div>`);
  } catch (e) { if (lastQuery === url && page === "link") main(empty(esc(errText(e)))); }
}

export async function doSearch() {
  const q = $("#q").value.trim();
  if (!q) return showHome();
  if (LINK.test(q)) return openLink(q);
  lastQuery = q; $("#tabs").hidden = false; go("search", doSearch);
  main(spinner("Searching"));
  try {
    const res = await api(`api/search?q=${encodeURIComponent(q)}&kind=${kind}`);
    if (q !== lastQuery || page !== "search") return;
    if (!res.length) return main(empty("No results"));
    if (kind === "songs") { lists.search = res; main(`<div class="list">${res.map((t, i) => songRow(t, "search", i)).join("")}</div>`); }
    else main(`<div class="grid">${res.map(card).join("")}</div>`);
  } catch (e) { if (q === lastQuery && page === "search") main(empty(`Search failed: ${esc(errText(e))}`)); }
}

/* ---------- an album, playlist or artist page ---------- */
export async function openItem(type, id) {
  go("item"); const my = ++navSeq;
  main(spinner("Loading"));
  try {
    const d = await api(`api/${type}/${encodeURIComponent(id)}`);
    if (my !== navSeq || page !== "item") return;
    lists.detail = d.tracks;
    const all = `data-list="detail" data-label="${esc(d.title || "")}"`;
    main(`<button class="back" data-act="back">← Back</button>
      <div class="hero"><img src="${esc(d.thumb)}" alt=""><div><h1>${esc(d.title)}</h1><div class="s">${esc(d.subtitle)} · ${d.tracks.length} songs</div>
      <div class="pills"><button class="pill" data-act="play-all" ${all}>▶ Play</button>
        <button class="pill ghost" data-act="play-all" data-mode="next" ${all}>Play next</button>
        <button class="pill ghost" data-act="play-all" data-mode="add" ${all}>Add all</button></div></div></div>
      <div class="list">${d.tracks.map((t, i) => songRow(t, "detail", i)).join("")}</div>
      ${d.albums && d.albums.length ? `<h2>Albums</h2><div class="shelf">${d.albums.map(card).join("")}</div>` : ""}`);
  } catch (e) { if (my === navSeq && page === "item") main(empty(`Could not load: ${esc(errText(e))}`)); }
}

/* ---------- Liked songs (shared by everyone) ---------- */
export async function showLiked() {
  $("#tabs").hidden = true; $("#q").value = ""; go("liked");
  main(spinner("Loading"));
  let p;
  try { p = await api("api/lists/liked"); } catch (e) { main(empty(`Could not load: ${esc(e.message)}`)); return; }
  if (page !== "liked") return;
  lists.liked = p.tracks;
  const n = p.tracks.length, all = 'data-list="liked" data-label="Liked songs"';
  main(`<button class="back" data-act="home">← Back</button>
    <div class="hero"><div><h1>Liked songs</h1><div class="s">Shared by everyone · ${plural(n, "song")}</div>
    ${n ? `<div class="pills"><button class="pill" data-act="play-all" ${all}>▶ Play</button><button class="pill ghost" data-act="play-all" data-mode="next" ${all}>Play next</button>
      <button class="pill ghost" data-act="play-all" data-mode="add" ${all}>Add all</button><button class="pill ghost" data-act="liked-shuffle">Shuffle</button></div>` : ""}</div></div>
    <div class="list">${n ? p.tracks.map((t, i) => songRow(t, "liked", i)).join("") : empty("Nothing liked yet. Tap the heart on any song.")}</div>`);
}

/* the liked list changed: redraw it if it's on screen */
export function likesChanged() { if (page === "liked") showLiked(); }

function shuffleLiked() {
  const t = [...lists.liked];
  for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; }
  askPlay(t, "Liked songs (shuffled)");
}

/* ---------- wiring ---------- */
on("home", showHome);
on("explore", showExplore);
on("liked", showLiked);
on("liked-shuffle", shuffleLiked);
on("mood", el => showMood(el.dataset.params, el.dataset.title));
on("open", el => openItem(el.dataset.type, el.dataset.id));
on("back", () => back());
on("add-track", el => askPlay([JSON.parse(el.dataset.track)]));

let typing;
$("#q").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(doSearch, 450); });
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(typing); doSearch(); } });
$("#tabs").addEventListener("click", e => {
  const k = e.target.dataset.k;
  if (!k) return;
  kind = k; $$("#tabs button").forEach(b => b.classList.toggle("on", b === e.target)); doSearch();
});
