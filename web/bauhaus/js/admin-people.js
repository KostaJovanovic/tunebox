/* The admin panel's People tab: everyone with what they played, then one person at a time: their
   details, pass phrase and devices, limits, playlists, likes and plays, and merging or removing them. */
import { $, esc, fmt, plural } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { COLORS, EMOJIS, seminars, avatar, semTags } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { toast, loading } from "./ui.js";
import { askPhrase, longEnough, withAdmin } from "./phrase.js";

let el = null;                                 /* the tab's body */
let all = [], signups = "open";
let open = null;                               /* the person on screen (id), or null for the list */
let detail = null, plays = [];                 /* theirs */
let pick = { color: "", emoji: "", sems: new Set() };   /* the details form, before it is saved */

/* every request here is the admin's: a session that ran out asks for the password again (null: it was closed) */
const call = (path, body, method) => withAdmin(() => api(path, body, method));
const person = () => all.find(p => p.id === open);
const day = t => new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const when = t => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function showPeople(target) { el = target; open = null; load(); }

async function load() {
  if (!all.length) el.innerHTML = loading("Loading");
  const [ps, st] = await Promise.all([call("api/admin/people"), api("api/admin")]);
  if (ps === null) return;
  all = ps; signups = st.signups;
  if (!person()) { open = null; return renderList(); }
  const p = person();
  [detail, plays] = await Promise.all([call(`api/admin/people/${p.id}/detail`), call(`api/admin/plays?who=${p.id}&limit=50`)]);
  if (detail === null || plays === null) return;
  renderPerson();
}

/* runs an admin action, says how it went, and shows the fresh state */
async function act(fn, done) {
  try {
    if (await fn() === null) return;
    if (done) toast(done);
    await load();
  } catch (e) { toast(errText(e)); }
}

/* ---------- the list ---------- */
const marks = p => (p.locked ? '<span class="lock" title="Has a pass phrase">🔒</span>' : "")
  + (p.noAdd ? '<i class="mark">can\'t add songs</i>' : "") + (p.cap ? `<i class="mark">max ${p.cap} waiting</i>` : "");

function renderList() {
  el.innerHTML = `<div class="sec"><h2>People</h2><span class="aside">${plural(all.length, "name")}</span></div>
    <div class="body">
      <div class="optrow"><div><div class="ot">Anyone can add a name</div><div class="od">Off: only the admin adds people, here.</div></div>
        <button class="tog" data-act="adm-signups" role="switch" aria-checked="${signups === "open"}" aria-label="Anyone can add a name"><i></i></button></div>
      <form class="aform" id="admNew"><input class="field" placeholder="A new person's name" maxlength="24" autocomplete="off">
        <select class="field" aria-label="Seminar">${Object.values(seminars).map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select>
        <button class="btn">Add</button></form>
      ${all.map(p => `<button class="aperson" data-act="adm-person" data-id="${esc(p.id)}">${avatar(p)}
        <div class="min0"><div class="t">${esc(p.name)} ${semTags(p, "sm")}${marks(p)}</div>
        <div class="s">${plural(p.plays, "play")} · ${p.minutes} min${p.last ? " · last on " + day(p.last) : ""}</div></div><span class="go">›</span></button>`).join("")
        || "<p>No names yet.</p>"}
    </div>`;
  $("#admNew").addEventListener("submit", e => {
    e.preventDefault();
    const name = $("#admNew input").value.trim();
    if (name) act(() => call("api/admin/people", { name, seminars: [$("#admNew select").value] }), `Added ${name}`);
  });
}

/* ---------- one person ---------- */
function renderPerson() {
  const p = person(), others = all.filter(x => x.id !== p.id);
  pick = { color: p.color, emoji: p.emoji, sems: new Set(p.seminars) };
  const row = (title, sub, buttons) => `<div class="arow"><div class="min0"><div class="t">${title}</div><div class="s">${sub}</div></div><div class="acts">${buttons}</div></div>`;
  el.innerHTML = `<button class="back" data-act="adm-back">‹ All people</button>
    <div class="ahero"><span id="admAv">${avatar(p)}</span><div class="min0"><h1>${esc(p.name)}</h1><div class="s">${semTags(p)}${marks(p)}</div></div></div>
    <div class="astats"><div><b>${p.plays}</b><span>plays</span></div><div><b>${p.minutes}</b><span>minutes</span></div>
      <div><b>${p.last ? day(p.last) : "never"}</b><span>last played</span></div></div>

    <div class="sec"><h2>Details</h2></div>
    <form class="body whoform" id="admForm">
      <input class="field" id="admName" value="${esc(p.name)}" maxlength="24" autocomplete="off" aria-label="Name">
      <div class="lbl">Seminar</div><div class="sems" id="admSems"></div>
      <div class="lbl">Colour</div><div class="swatches" id="admColors"></div>
      <div class="lbl">Icon</div><div class="emojis" id="admEmoji"></div>
      <div class="eqtools"><button class="btn red">Save</button></div>
    </form>

    <div class="sec"><h2>Pass phrase</h2></div>
    <div class="body"><p>${p.locked ? "This name has a pass phrase: a device types it once to use the name." : "No pass phrase: anyone can pick this name."}</p>
      <div class="eqtools"><button class="btn" data-act="adm-phrase">${p.locked ? "Change it" : "Set one"}</button>
        ${p.locked ? `<button class="btn" data-act="adm-phrase-off">Remove it</button><button class="btn" data-act="adm-signout">Sign out every device</button>` : ""}</div></div>

    <div class="sec"><h2>Adding songs</h2></div>
    <div class="body">
      <div class="optrow"><div><div class="ot">Can add songs</div><div class="od">Off: they can listen and like, and see "You can't add songs right now".</div></div>
        <button class="tog" data-act="adm-noadd" role="switch" aria-checked="${!p.noAdd}" aria-label="Can add songs"><i></i></button></div>
      <form class="aform" id="admCap"><label for="admCapN">At most this many of their songs waiting (0: no limit)</label>
        <input class="field num" id="admCapN" type="number" min="0" max="999" value="${p.cap || 0}"><button class="btn">Set</button></form></div>

    ${p.top.length ? `<div class="sec"><h2>Most played</h2></div><div class="body">${p.top.map(t => row(esc(t.title), esc(t.artist), `<span class="n">${plural(t.plays, "play")}</span>`)).join("")}</div>` : ""}

    <div class="sec"><h2>Playlists</h2><span class="aside">${detail.lists.length}</span></div>
    <div class="body">${detail.lists.map(l => row(esc(l.name), plural(l.count, "song"),
      `<button data-act="adm-list-rename" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Rename</button><button data-act="adm-list-delete" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Delete</button>`)).join("")
      || "<p>None of the playlists is theirs.</p>"}</div>

    <div class="sec"><h2>Likes</h2><span class="aside">${detail.likes.length}</span></div>
    <div class="body">${detail.likes.map(t => row(esc(t.title), esc(t.artist), `<button data-act="adm-unlike" data-v="${esc(t.videoId)}">Remove</button>`)).join("") || "<p>Nothing liked.</p>"}
      ${detail.likes.length > 1 ? `<div class="eqtools"><button class="btn danger" data-act="adm-unlike-all">Remove all their likes</button></div>` : ""}</div>

    <div class="sec"><h2>Plays</h2><span class="aside">${plays.length < p.plays ? `the last ${plays.length}` : plays.length}</span></div>
    <div class="body">${plays.map(q => row(esc(q.ti), `${esc(q.ar)} · ${when(q.t)} · ${fmt(q.s)} heard`,
      `<button data-act="adm-play-del" data-t="${q.t}" data-v="${esc(q.v)}">Remove</button>`)).join("") || "<p>Nothing played yet.</p>"}
      ${plays.length ? `<div class="eqtools"><button class="btn danger" data-act="adm-plays-all">Remove all their plays</button></div>
      <p class="hint">Removed plays leave Stats and the recap for good.</p>` : ""}</div>

    <div class="sec"><h2>Merge or remove</h2></div>
    <div class="body">
      ${others.length ? `<form class="aform" id="admMerge"><label for="admInto">Made twice? Give everything of ${esc(p.name)}'s to</label>
        <select class="field" id="admInto">${others.map(x => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select><button class="btn">Merge</button></form>` : ""}
      <div class="eqtools"><button class="btn danger" data-act="adm-remove" data-mode="keep">Remove the name</button>
        <button class="btn danger" data-act="adm-remove" data-mode="purge">Remove with plays, likes and playlists</button></div>
      <p class="hint">Remove the name: their songs and plays stay, with no name on them, and their playlists become the house's.</p></div>`;
  paintPick();
  $("#admName").addEventListener("input", paintPick);
  $("#admForm").addEventListener("submit", e => {
    e.preventDefault();
    const name = $("#admName").value.trim();
    if (!name) return $("#admName").focus();
    if (!pick.sems.size) return toast("Pick a seminar");
    act(() => call(`api/admin/people/${p.id}`, { name, color: pick.color, emoji: pick.emoji, seminars: [...pick.sems] }, "PATCH"), "Saved");
  });
  $("#admCap").addEventListener("submit", e => {
    e.preventDefault();
    const cap = Math.max(0, Math.floor(+$("#admCapN").value || 0));
    act(() => call(`api/admin/people/${p.id}`, { cap }, "PATCH"), cap ? `At most ${plural(cap, "song")} waiting` : "No limit");
  });
  $("#admMerge")?.addEventListener("submit", e => {
    e.preventDefault();
    const into = all.find(x => x.id === $("#admInto").value);
    if (!confirm(`Merge ${p.name} into ${into.name}? ${p.name}'s plays, likes and playlists become ${into.name}'s, and the name ${p.name} is removed. This can't be undone.`)) return;
    open = into.id;
    act(() => call("api/admin/people/merge", { source: p.id, into: into.id }), `Merged into ${into.name}`);
  });
}

/* the form's chips, and the badge as it will look */
function paintPick() {
  $("#admSems").innerHTML = Object.values(seminars).map(x => `<button type="button" class="${pick.sems.has(x.id) ? "on" : ""}" style="--c:${esc(x.color)}"
    aria-pressed="${pick.sems.has(x.id)}" data-act="adm-sem" data-s="${esc(x.id)}">${esc(x.name)}</button>`).join("");
  $("#admColors").innerHTML = COLORS.map(c => `<button type="button" class="${c === pick.color ? "on" : ""}" style="background:${c}" aria-label="Colour ${c}" data-act="adm-color" data-c="${c}"></button>`).join("");
  $("#admEmoji").innerHTML = EMOJIS.map(e => `<button type="button" class="${e === pick.emoji ? "on" : ""}" aria-label="${e || "Initial"}" data-act="adm-emoji" data-e="${e}">${e || "Aa"}</button>`).join("");
  $("#admAv").innerHTML = avatar({ name: $("#admName").value.trim() || "?", color: pick.color, emoji: pick.emoji });
}

async function setPhrase() {
  const p = person();
  const nu = await askPhrase({ title: `A pass phrase for ${p.name}`, hint: "At least 4 characters. Every device will have to type it to use this name.", button: "Next", check: longEnough });
  if (nu === null) return;
  if (await askPhrase({ title: "Type it again", button: "Save", check: async v => { if (v !== nu) throw new Error("That's not the same"); } }) === null) return;
  act(() => call(`api/admin/people/${p.id}`, { phrase: nu }, "PATCH"), `${p.name}'s pass phrase saved`);
}

/* ---------- wiring ---------- */
on("adm-person", b => { open = b.dataset.id; load(); });
on("adm-back", () => { open = null; renderList(); el.scrollTop = 0; });
on("adm-signups", b => act(() => call("api/admin/signups", { open: b.getAttribute("aria-checked") !== "true" }, "PATCH")));
on("adm-sem", b => { const s = b.dataset.s; pick.sems.has(s) ? pick.sems.delete(s) : pick.sems.add(s); paintPick(); });
on("adm-color", b => { pick.color = b.dataset.c; paintPick(); });
on("adm-emoji", b => { pick.emoji = b.dataset.e; paintPick(); });
on("adm-phrase", setPhrase);
on("adm-phrase-off", () => {
  const p = person();
  if (confirm(`Take the pass phrase off ${p.name}? Anyone can then pick the name.`)) act(() => call(`api/admin/people/${p.id}`, { phrase: "" }, "PATCH"), `${p.name} has no pass phrase now`);
});
on("adm-signout", () => {
  const p = person();
  if (confirm(`Sign every device out of ${p.name}? Each one has to type the pass phrase again.`)) act(() => call(`api/admin/people/${p.id}/signout`, {}), "Signed out everywhere");
});
on("adm-noadd", b => act(() => call(`api/admin/people/${open}`, { noAdd: b.getAttribute("aria-checked") === "true" }, "PATCH")));
on("adm-list-rename", b => {
  const name = (prompt("A new name for this playlist", b.dataset.name) || "").trim();
  if (name && name !== b.dataset.name) act(() => call(`api/lists/${b.dataset.id}`, { name }, "PATCH"), "Renamed");
});
on("adm-list-delete", b => {
  if (confirm(`Delete "${b.dataset.name}" for everyone?`)) act(() => call(`api/lists/${b.dataset.id}`, undefined, "DELETE"), "Playlist deleted");
});
on("adm-unlike", b => act(() => call(`api/admin/people/${open}/unlike`, { videoId: b.dataset.v })));
on("adm-unlike-all", () => {
  if (confirm(`Remove all of ${person().name}'s likes?`)) act(() => call(`api/admin/people/${open}/unlike`, { all: true }), "Likes removed");
});
on("adm-play-del", b => act(() => call("api/admin/plays", { plays: [{ t: +b.dataset.t, v: b.dataset.v }] }, "DELETE")));
on("adm-plays-all", () => {
  if (confirm(`Remove every play of ${person().name} from the log? Stats and the recap lose them for good.`)) act(() => call("api/admin/plays", { who: open, all: true }, "DELETE"), "Plays removed");
});
on("adm-remove", b => {
  const p = person(), purge = b.dataset.mode === "purge";
  if (!confirm(purge ? `Remove ${p.name} with all their plays, likes and playlists? This can't be undone.` : `Remove ${p.name}? Their songs and plays stay, with no name on them.`)) return;
  act(() => call(`api/admin/people/${p.id}?mode=${b.dataset.mode}`, undefined, "DELETE"), `Removed ${p.name}`);
});
