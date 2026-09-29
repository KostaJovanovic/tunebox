/* Stats: what the house (or one person, or one seminar) played in a period, from the play log.
   The recap (recap.js) tells the same numbers as a story. */
import { $, esc } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { lists } from "../../shared/playback.js";
import { people, seminars, avatar, semTag, myId } from "../../shared/people.js";
import { on } from "../../shared/actions.js";
import { seq, setNav } from "./nav.js";
import { main, loading, note, section, songRow } from "./ui.js";

const PERIODS = [["30d", "Last 30 days"], ["month", "This month"], ["lastmonth", "Last month"], ["year", "This year"],
  ["lastyear", "Last year"], ["all", "All time"], ["custom", "Custom"]];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let period = "30d", who = "", from = "", to = "";

/* since/until (Unix seconds) and a name for a period */
export function range(p = period, a = from, b = to) {
  const now = new Date(), y = now.getFullYear(), m = now.getMonth(), s = d => Math.floor(d / 1000);
  switch (p) {
    case "month": return { since: s(new Date(y, m, 1)), until: 0, label: now.toLocaleDateString([], { month: "long", year: "numeric" }) };
    case "lastmonth": { const d = new Date(y, m - 1, 1); return { since: s(d), until: s(new Date(y, m, 1)), label: d.toLocaleDateString([], { month: "long", year: "numeric" }) }; }
    case "year": return { since: s(new Date(y, 0, 1)), until: 0, label: String(y) };
    case "lastyear": return { since: s(new Date(y - 1, 0, 1)), until: s(new Date(y, 0, 1)), label: String(y - 1) };
    case "all": return { since: 0, until: 0, label: "All time" };
    case "custom": if (a && b) return { since: s(new Date(a + "T00:00")), until: s(new Date(b + "T00:00")) + 86400, label: `${a} – ${b}` };
    // falls through: a custom period without both dates
    default: return { since: s(now) - 30 * 86400, until: 0, label: "The last 30 days" };
  }
}

export const whoName = w => !w ? "The house" : w.startsWith("sem:") ? (seminars[w.slice(4)]?.name || "Seminar") : (people[w]?.name || "Someone");
export const fetchStats = (r, w) => api(`api/stats?since=${r.since}&until=${r.until}&who=${encodeURIComponent(w)}`);
const hm = min => min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`;
const num = n => n.toLocaleString();

export async function showStats() {
  setNav("stats"); $("#q").value = "";
  const my = seq, r = range();
  main(loading("Counting"));
  let d;
  try { d = await fetchStats(r, who); } catch (e) { if (my === seq) main(note(`Could not load the stats: ${esc(errText(e))}`)); return; }
  if (my !== seq) return;
  render(d, r);
}

function filters(d) {
  const chip = (act, v, cur, html) => `<button class="${v === cur ? "on" : ""}" aria-pressed="${v === cur}" data-act="${act}" data-v="${esc(v)}">${html}</button>`;
  const ps = Object.values(people).sort((a, b) => a.name.localeCompare(b.name));
  const me = myId();
  return `<div class="statbar">
    <div class="likers">${PERIODS.map(([k, t]) => chip("stats-period", k, period, t)).join("")}</div>
    ${period === "custom" ? `<div class="daterange"><input class="field" type="date" id="stFrom" value="${esc(from)}"><span>to</span>
      <input class="field" type="date" id="stTo" value="${esc(to)}"><button class="btn" data-act="stats-custom">Show</button></div>` : ""}
    <div class="likers">${chip("stats-who", "", who, "Everyone")}${ps.map(p => chip("stats-who", p.id, who, avatar(p, "sm") + esc(p.name) + (p.id === me ? " <small>(you)</small>" : ""))).join("")}
      ${Object.values(seminars).map(x => chip("stats-who", "sem:" + x.id, who, semTag(x.id))).join("")}</div>
  </div>`;
}

/* one bar per slot (hours, weekdays, months): a single series, so one colour and no legend; hover says the value */
function bars(values, labels, every = 1) {
  const max = Math.max(1, ...values);
  return `<div class="bars" style="--n:${values.length}">${values.map((v, i) =>
    `<div class="bar" title="${esc(labels[i])}: ${hm(v)}"><i style="height:${(v / max * 100).toFixed(1)}%"></i><span>${i % every ? "" : esc(labels[i])}</span></div>`).join("")}</div>`;
}

/* people or seminars, longest listeners first: each bar in its own colour, the name and minutes beside it */
function board(rows, look) {
  const max = Math.max(1, ...rows.map(r => r.minutes));
  return `<div class="board">${rows.map(r => { const l = look(r.id); if (!l) return "";
    return `<div class="brow"><div class="who">${l.badge}<span>${esc(l.name)}</span></div>
      <div class="track"><i style="width:${(r.minutes / max * 100).toFixed(1)}%;background:${esc(l.color)}"></i></div><b>${hm(r.minutes)}</b></div>`; }).join("")}</div>`;
}

function render(d, r) {
  let n = 0;
  const title = `${whoName(who)} · ${r.label}`;
  let html = section(++n, "Stats", `<button class="link" data-act="recap-open">Play the recap ▸</button>`) + filters(d);
  if (!d.plays) return main(html + note(`No plays for ${esc(title.toLowerCase())} yet.`));
  html += `<div class="tiles">
    <div class="tile big"><b>${num(d.minutes)}</b><span>minutes listened</span></div>
    <div class="tile"><b>${num(d.plays)}</b><span>plays</span></div>
    <div class="tile"><b>${num(d.songs)}</b><span>different songs</span></div>
    <div class="tile"><b>${num(d.artists)}</b><span>artists</span></div>
    <div class="tile"><b>${num(d.newSongs)}</b><span>new to ${who ? (who.startsWith("sem:") ? "the seminar" : "them") : "the house"}</span></div>
    <div class="tile"><b>${d.streak}</b><span>days in a row, at best</span></div>
  </div>`;
  lists.stats = d.topSongs;
  html += section(++n, "Top songs", esc(title)) + `<div class="list">${d.topSongs.map((t, i) => songRow(t, "stats", i, { d: `${t.plays}×`, playing: false })).join("")}</div>`;
  html += section(++n, "Top artists") + `<div class="shelf">${d.topArtists.map((a, i) => `<button class="card" ${a.id ? `data-act="open" data-type="artist" data-id="${esc(a.id)}"` : "disabled"}>
    <img loading="lazy" src="${esc(a.thumb)}" alt=""><div class="t">${i + 1}. ${esc(a.name)}</div><div class="s">${a.plays} plays · ${hm(a.minutes)}</div></button>`).join("")}</div>`;
  if (!who || who.startsWith("sem:")) {
    const ps = d.people.filter(x => !who || people[x.id]?.seminars?.includes(who.slice(4)));
    if (ps.length) html += section(++n, "Who added the most", "minutes of their songs") + board(ps, id => people[id] && { name: people[id].name, color: people[id].color, badge: avatar(people[id], "sm") });
  }
  if (!who && d.seminars.length) html += section(++n, "Seminars", "minutes of their songs") + board(d.seminars, id => seminars[id] && { name: seminars[id].name, color: seminars[id].color, badge: semTag(id) });
  html += section(++n, "When", d.busiestDay ? `busiest day: ${esc(new Date(d.busiestDay.date).toLocaleDateString([], { day: "numeric", month: "long" }))}, ${hm(d.busiestDay.minutes)}` : "")
    + `<div class="when"><div><h3>Time of day</h3>${bars(d.hours, d.hours.map((_, h) => `${h}:00`), 6)}</div>
       <div><h3>Day of the week</h3>${bars(d.weekdays, DAYS)}</div></div>`;
  if (d.months.length > 2) html += section(++n, "Month by month") + bars(d.months.map(m => m.minutes),
    d.months.map(m => new Date(m.month + "-01").toLocaleDateString([], { month: "short", year: "2-digit" })));
  html += `<p class="hint tight statnote">A play counts once 30 seconds were heard. Songs count for whoever added them; radio songs count for the house only. ${d.radioShare}% of these plays were radio.</p>`;
  main(html);
}

on("stats-period", el => { period = el.dataset.v; showStats(); });
on("stats-who", el => { who = el.dataset.v; showStats(); });
on("stats-custom", () => { from = $("#stFrom").value; to = $("#stTo").value; if (from && to) showStats(); });
export const statsView = () => ({ period, who, from, to });
