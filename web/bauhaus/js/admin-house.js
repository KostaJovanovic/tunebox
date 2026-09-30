/* The admin panel's Features and House tabs. Features: a switch for everything Tunebox does, four
   presets that set them all at once, and the setup as a file for another Tunebox. House: its name and
   accent, the time zone, who may add a name, groups, the wall screen and the blocklist. */
import { $, esc, plural } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { house, setHouse, G } from "../../shared/house.js";
import { COLORS, people } from "../../shared/people.js";
import { ACCENTS } from "../../shared/device.js";
import { poll } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { toast, loading } from "./ui.js";
import { withAdmin } from "./phrase.js";

let el = null;                                 /* the tab's body; its data-tab says which tab is on screen */
let setup = null;                              /* /api/admin/house: every feature, the presets */
let groups = [], blocks = { songs: [], artists: [] };
let editing = null;                            /* the group whose form is open (id) */

/* every request here is the admin's: a session that ran out asks for the password again (null: it was closed) */
const call = (path, body, method) => withAdmin(() => api(path, body, method));
const here = tab => el?.dataset.tab === tab;
const day = t => new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const tog = (act, k, on, label) => `<button type="button" class="tog" data-act="${act}" data-k="${k}" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}"><i></i></button>`;
const optrow = (act, k, on, title, what) => `<div class="optrow"><div><div class="ot">${esc(title)}</div><div class="od">${esc(what)}</div></div>${tog(act, k, on, title)}</div>`;

/* Runs a change, says how it went and shows the fresh state. A change to the house answers with the
   house itself, which the page takes over at once. */
async function save(fn, done) {
  try {
    const r = await fn();
    if (r === null) return;
    if (r && r.rev) setHouse(r);
    if (done) toast(done);
    if (here("features")) await showFeatures(el); else if (here("house")) await showHouse(el);
  } catch (e) { toast(errText(e)); }
}

/* ---------- Features ---------- */
const PRESETS = [["home", "Home", "everything"], ["office", "Office", "no recap, alarm or EQ"], ["party", "Party", "no names or stats"], ["solo", "Solo", "no names or wall"]];
const FEATURES = () => [
  ["people", "Names", "Everyone picks a name: the queue shows who added what, and songs from different people take turns. Off: anyone adds songs, and nobody is named."],
  ["groups", G().many, "People belong to one or more of them; stats and likes can be seen for each."],
  ["playlists", "Playlists", "The house's own playlists, shared by everyone."],
  ["likes", "Likes", "The heart on every song, and the Liked songs list."],
  ["browse", "Home and Explore", "YouTube Music's shelves, new releases and moods. Off: search only."],
  ["links", "Pasting links", "A YouTube link in the search box opens that song, album or playlist."],
  ["radio", "Radio", "After the songs people add, more like the last one keep playing."],
  ["lyrics", "Lyrics", "Synced lyrics in the player and on the wall screen."],
  ["stats", "Stats", "What the house played: top songs and artists, who added the most, and when."],
  ["recap", "Recap", "The stats told as a story, from the Stats page."],
  ["wall", "Wall screen", "A full-screen view for a tablet or TV."],
  ["alarm", "Wake-up alarm", "Starts the music at a set time. Off: a set alarm doesn't ring."],
  ["sleep", "Sleep timer", "Fades out and pauses after a while."],
  ["eq", "Equaliser", "Presets and a custom curve. Off: the sound stays as it is now."],
];

export async function showFeatures(target) {
  el = target;
  if (!setup) el.innerHTML = loading("Loading");
  const s = await call("api/admin/house");
  if (s === null || !here("features")) return;
  setup = s;
  const off = new Set(house.off), shown = FEATURES();
  const same = name => setup.features.every(k => setup.presets[name].includes(k) === off.has(k));
  const n = shown.filter(([k]) => off.has(k)).length;
  el.innerHTML = `<div class="sec"><h2>Presets</h2></div>
    <div class="body"><p>A place to start: each one sets every switch below. Change any of them afterwards.</p>
      <div class="presets">${PRESETS.map(([k, name, what]) => `<button class="${same(k) ? "on" : ""}" data-act="adm-preset" data-p="${k}">${name}<small>${what}</small></button>`).join("")}</div></div>
    <div class="sec"><h2>Features</h2><span class="aside">${n ? `${n} off` : "all on"}</span></div>
    <div class="body"><p>What is off is hidden from everyone and refused by the server. Only the admin still sees and uses it, shown faded. Nothing is deleted: switching it back on brings everything back.</p>
      ${shown.map(([k, name, what]) => optrow("adm-feature", k, !off.has(k), name, what)).join("")}</div>
    <div class="sec"><h2>Copy this setup</h2></div>
    <div class="body"><p>The switches, the house's name and accent, what ${esc(G().some)} are called and the wall's options, as a file to load into another Tunebox. People, playlists and plays are not in it: those are in the backup.</p>
      <div class="eqtools"><a class="btn" href="api/admin/features/export" download="tunebox-setup.json">Download the setup</a>
        <label class="btn">Load a setup file<input type="file" id="admSetupFile" accept=".json,application/json" hidden></label></div></div>`;
  $("#admSetupFile").addEventListener("change", async e => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    let file;
    try { file = JSON.parse(await f.text()); } catch { return toast("That isn't a Tunebox setup file"); }
    if (confirm("Load this setup? It replaces the switches, the house's name and accent, and the wall's options.")) save(() => call("api/admin/features/import", { setup: file }), "Setup loaded");
  });
}

/* ---------- House ---------- */
export async function showHouse(target) {
  el = target;
  if (!setup) el.innerHTML = loading("Loading");
  const [s, gs, bl] = await Promise.all([call("api/admin/house"), api("api/seminars"), call("api/admin/blocks")]);
  if (s === null || bl === null || !here("house")) return;
  setup = s; groups = gs; blocks = bl;
  const h = house, g = G(), zones = Intl.supportedValuesOf?.("timeZone") || [];
  if (h.tz && !zones.includes(h.tz)) zones.unshift(h.tz);
  const accent = (k, name, c) => `<button class="acc${k ? "" : " all"}${h.accent === k ? " on" : ""}" data-act="adm-accent" data-k="${k}">${c ? `<i class="sw" style="background:${c}"></i>` : ""}${name}</button>`;
  const inGroup = id => Object.values(people).filter(p => p.seminars?.includes(id)).length;
  const group = x => {
    const starts = h.newPerson.groups.includes(x.id);
    const row = `<div class="arow"><div class="min0"><div class="t"><i class="sem" style="background:${esc(x.color)}">${esc(x.name)}</i></div>
      <div class="s">${plural(inGroup(x.id), "person").replace("persons", "people")}${starts ? " · new people start here" : ""}</div></div>
      <div class="acts"><button data-act="adm-group-edit" data-id="${esc(x.id)}">${editing === x.id ? "Close" : "Edit"}</button><button data-act="adm-group-del" data-id="${esc(x.id)}">Remove</button></div></div>`;
    if (editing !== x.id) return row;
    return row + `<form class="aform agroup" id="admGroup"><input class="field" value="${esc(x.name)}" maxlength="24" autocomplete="off" aria-label="Name"><button class="btn">Rename</button>
      <div class="swatches">${COLORS.map(c => `<button type="button" class="${c === x.color ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="adm-group-color" data-c="${c}"></button>`).join("")}</div>
      ${optrow("adm-group-start", x.id, starts, "New people start here", "Someone who adds their name without picking one gets this one.")}</form>`;
  };
  const blocked = (kind, key, title, sub) => `<div class="arow"><div class="min0"><div class="t">${esc(title)}</div><div class="s">${esc(sub)}</div></div>
    <div class="acts"><button data-act="adm-unblock" data-kind="${kind}" data-key="${esc(key)}" data-name="${esc(title)}">Unblock</button></div></div>`;

  el.innerHTML = `<div class="sec"><h2>Name and look</h2></div>
    <div class="body">
      <form class="aform" id="admHouse"><label for="admHouseName">The house's name: in the top bar, the browser's tab and the installed app</label>
        <input class="field" id="admHouseName" value="${esc(h.name)}" maxlength="24" autocomplete="off"><button class="btn">Save</button></form>
      <span class="lbl">Accent</span>
      <div class="presets c3">${accent("", "Each device's own")}${Object.entries(ACCENTS).map(([k, a]) => accent(k, a.name, a.c)).join("")}</div>
      <p class="hint">A device that picked its own accent in Settings keeps it.</p>
      <span class="lbl">Time zone</span>
      <select class="field" id="admTz" aria-label="Time zone"><option value="">The server's own time</option>${zones.map(z => `<option${z === h.tz ? " selected" : ""}>${esc(z)}</option>`).join("")}</select>
      <p class="hint">The alarm rings in this time, and Stats counts its hours and days in it.</p>
    </div>

    <div class="sec"><h2>New names</h2></div>
    <div class="body">${optrow("adm-house", "signups", h.signups === "open", "Anyone can add a name", "Off: only the admin adds people, in the People tab.")}</div>

    <div class="sec"><h2>${esc(g.many)}</h2><span class="aside">${groups.length}</span></div>
    <div class="body">
      <form class="aform" id="admWords"><label for="admOne">What they are called here: one of them, and many</label>
        <input class="field" id="admOne" value="${esc(g.one)}" maxlength="24" autocomplete="off" aria-label="One"><input class="field" id="admMany" value="${esc(g.many)}" maxlength="24" autocomplete="off" aria-label="Many"><button class="btn">Save</button></form>
      ${optrow("adm-house", "required", h.groups.required, "Everyone is in one", "Off: a name can go without.")}
      ${optrow("adm-house", "create", h.groups.create === "open", "Anyone can add a new one", "Off: people pick from this list only.")}
      ${groups.map(group).join("") || `<p>No ${esc(g.some)} yet.</p>`}
      <form class="aform" id="admNewGroup"><input class="field" placeholder="A new one's name" maxlength="24" autocomplete="off"><button class="btn">Add</button></form>
    </div>

    <div class="sec"><h2>Wall screen</h2></div>
    <div class="body">
      ${optrow("adm-wall", "lyrics", h.wall.lyrics, "Lyrics", "Beside the cover, line by line.")}
      ${optrow("adm-wall", "queue", h.wall.queue, "Up next", "The next three songs, under the cover.")}
      ${optrow("adm-wall", "who", h.wall.who, "Who added it", "The name of whoever added the song.")}
      ${optrow("adm-wall", "clock", h.wall.clock, "Clock", "The time and date while nothing plays.")}
      ${optrow("adm-wall", "controls", h.wall.controls, "Buttons", "Off: the wall only shows; nobody skips or changes the volume on it.")}
    </div>

    <div class="sec"><h2>Blocked</h2><span class="aside">${blocks.songs.length + blocks.artists.length}</span></div>
    <div class="body"><p>A blocked song or artist can't be added, the radio leaves it out, and it is taken out of what's up next. Block a song from its menu (right-click it, or hold it on a phone); block an artist there or here.</p>
      <form class="aform" id="admBlock"><input class="field" placeholder="An artist's name" maxlength="100" autocomplete="off"><button class="btn">Block</button></form>
      ${blocks.artists.map(a => blocked("artists", a.key, a.name, "Artist · blocked " + day(a.at))).join("")}
      ${blocks.songs.map(t => blocked("songs", t.id, t.title, `${t.artist} · blocked ${day(t.at)}`)).join("")}
    </div>`;

  const submit = (id, fn) => $(id)?.addEventListener("submit", e => { e.preventDefault(); fn($(id + " input").value.trim()); });
  submit("#admHouse", name => name && save(() => call("api/admin/house", { name }, "PATCH"), "Saved"));
  submit("#admWords", () => save(() => call("api/admin/house", { groups: { one: $("#admOne").value, many: $("#admMany").value } }, "PATCH"), "Saved"));
  submit("#admNewGroup", name => name && save(() => call("api/admin/groups", { name }), `Added ${name}`));
  submit("#admGroup", name => name && save(() => call(`api/admin/groups/${editing}`, { name }, "PATCH"), "Renamed"));
  submit("#admBlock", name => name && block({ kind: "artist", name }));
  $("#admTz").addEventListener("change", e => save(() => call("api/admin/house", { tz: e.target.value }, "PATCH"), e.target.value ? `${e.target.value} time` : "The server's own time"));
}

/* Blocks a song or an artist (the admin's; asks for the password if need be) and says what left the queue */
export async function block(body) {
  try {
    const r = await call("api/admin/blocks", body);
    if (r === null) return;
    toast(r.message); poll();
    if (here("house") && $("#admin").classList.contains("open")) showHouse(el);
  } catch (e) { toast(errText(e)); }
}

/* ---------- wiring ---------- */
const flip = b => b.getAttribute("aria-checked") !== "true";
on("adm-preset", b => {
  const [, name, what] = PRESETS.find(p => p[0] === b.dataset.p);
  if (confirm(`Set every switch to the ${name} preset (${what})?`)) save(() => call("api/admin/features/preset", { name: b.dataset.p }), `${name} preset`);
});
on("adm-feature", b => save(() => call("api/admin/features", { features: { [b.dataset.k]: flip(b) } }, "PATCH")));
on("adm-accent", b => save(() => call("api/admin/house", { accent: b.dataset.k }, "PATCH")));
on("adm-house", b => {
  const k = b.dataset.k, v = flip(b);
  save(() => call("api/admin/house", k === "signups" ? { signups: v ? "open" : "closed" } : { groups: k === "create" ? { create: v ? "open" : "admin" } : { required: v } }, "PATCH"));
});
on("adm-wall", b => save(() => call("api/admin/house", { wall: { [b.dataset.k]: flip(b) } }, "PATCH")));
on("adm-group-edit", b => { editing = editing === b.dataset.id ? null : b.dataset.id; showHouse(el); });
on("adm-group-color", b => save(() => call(`api/admin/groups/${editing}`, { color: b.dataset.c }, "PATCH")));
on("adm-group-start", b => {
  const now = house.newPerson.groups.filter(s => s !== b.dataset.k);
  save(() => call("api/admin/house", { newPerson: { groups: flip(b) ? [...now, b.dataset.k] : now } }, "PATCH"));
});
on("adm-group-del", b => {
  const x = groups.find(s => s.id === b.dataset.id);
  if (confirm(`Remove ${x.name}? Its people stay, without it.`)) save(() => call(`api/admin/groups/${x.id}`, undefined, "DELETE"), `Removed ${x.name}`);
});
on("adm-unblock", b => save(() => call(`api/admin/blocks/${b.dataset.kind}/${encodeURIComponent(b.dataset.key)}`, undefined, "DELETE"), `Unblocked ${b.dataset.name}`));
