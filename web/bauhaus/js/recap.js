/* The recap: Stats told as full-screen story slides, for the period and the person or group picked
   on the Stats page. Tap the right side (or →) for the next slide, the left side (or ←) to go back,
   hold to pause; each slide moves on by itself after a few seconds. */
import { $, esc, art } from "../../shared/dom.js";
import { errText } from "../../shared/api.js";
import { lists, queueSongs } from "../../shared/playback.js";
import { people, seminars, avatar, semTag } from "../../shared/people.js";
import { house, feat, G } from "../../shared/house.js";
import { on } from "../../shared/actions.js";
import { toast } from "./ui.js";
import { range, whoName, fetchStats, statsView } from "./stats.js";

const SLIDE_MS = 6500;
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const box = $("#recap");
let slides = [], at = 0, timer = null, started = 0, left = SLIDE_MS, held = false, top = [];

const hm = min => min >= 120 ? `${Math.round(min / 60)} hours` : `${min} ${min === 1 ? "minute" : "minutes"}`;
const num = n => n.toLocaleString();
const img = t => `<img src="${esc(art(t))}" alt="">`;

function build(d, who, label) {
  const name = whoName(who), you = who && !who.startsWith("sem:");
  const s = [];
  s.push({ cls: "red", html: `<div class="k">${esc(house.name)} recap</div><h1>${esc(label)}</h1>
    <p class="lead">${esc(name)}${who.startsWith("sem:") ? " " + esc(G().a) : ""}</p><p>Tap to go on.</p>` });
  if (!d.plays) return [...s, { cls: "black", html: `<h1>Nothing yet</h1><p class="lead">No plays in this period. Put some music on.</p>` }];
  s.push({ cls: "black", html: `<div class="k">Time together</div><div class="huge">${num(d.minutes)}</div><p class="lead">minutes of music</p>
    <p>${d.minutes >= 120 ? `That's ${hm(d.minutes)}` : "Every minute counts"}, across ${d.days} ${d.days === 1 ? "day" : "days"} and ${num(d.plays)} plays.</p>` });
  const t = d.topSongs[0];
  if (t) s.push({ cls: "cover", bg: t.thumb, html: `<div class="k">${you ? "Your" : "The"} number one</div>${img(t)}
    <h2>${esc(t.title)}</h2><p class="lead">${esc(t.artist)}</p><p>Played ${t.plays} ${t.plays === 1 ? "time" : "times"}, ${hm(t.minutes)}.</p>` });
  if (d.topSongs.length > 1) s.push({ cls: "yellow", html: `<div class="k">Top songs</div><ol class="tops">${d.topSongs.slice(0, 5).map(x =>
    `<li>${img(x)}<div><b>${esc(x.title)}</b><span>${esc(x.artist)} · ${x.plays}×</span></div></li>`).join("")}</ol>` });
  const a = d.topArtists[0];
  if (a) s.push({ cls: "cover", bg: a.thumb, html: `<div class="k">Top artist</div>${img(a)}<h2>${esc(a.name)}</h2>
    <p class="lead">${a.plays} plays · ${hm(a.minutes)}</p>${d.topArtists[1] ? `<p>Then ${esc(d.topArtists.slice(1, 3).map(x => x.name).join(" and "))}.</p>` : ""}` });
  s.push({ cls: "blue", html: `<div class="k">Range</div><div class="huge">${num(d.songs)}</div><p class="lead">different songs by ${num(d.artists)} artists</p>
    <p>${d.newSongs ? `${num(d.newSongs)} of them ${d.newSongs === 1 ? "was" : "were"} new${you ? " to you" : ""}.` : "Old favourites, all of them."}</p>` });
  const hour = d.hours.indexOf(Math.max(...d.hours)), day = d.weekdays.indexOf(Math.max(...d.weekdays));
  s.push({ cls: "black", html: `<div class="k">When</div><h2>${DAYS[day]}s around ${hour}:00</h2>
    <p class="lead">That's when the music plays most.</p>${d.busiestDay ? `<p>The biggest day: ${esc(new Date(d.busiestDay.date).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }))}, ${hm(d.busiestDay.minutes)}.</p>` : ""}
    ${d.streak > 1 ? `<p>Best run: ${d.streak} days in a row.</p>` : ""}` });
  const sems = feat("groups") ? d.seminars.filter(x => seminars[x.id]) : [];
  if (sems.length && !you) {
    const mine = who.startsWith("sem:") ? who.slice(4) : null, rank = mine ? sems.findIndex(x => x.id === mine) + 1 : 0;
    s.push({ cls: "red", html: `<div class="k">${esc(G().many)}</div><h2>${mine && rank ? `${esc(seminars[mine].name)} came ${rank === 1 ? "first" : `number ${rank}`}` : `${esc(seminars[sems[0].id].name)} played the most`}</h2>
      <ol class="rank">${sems.slice(0, 5).map(x => `<li class="${x.id === mine ? "me" : ""}">${semTag(x.id)}<span>${hm(x.minutes)}</span></li>`).join("")}</ol>` });
  }
  if (you) {
    const mine = people[who]?.seminars || [];
    if (mine.length && sems.length) s.push({ cls: "red", html: `<div class="k">${esc(G().many)}</div><h2>${esc(name)} plays for ${mine.map(x => esc(seminars[x]?.name || x)).join(" and ")}</h2>
      <ol class="rank">${sems.slice(0, 5).map(x => `<li class="${mine.includes(x.id) ? "me" : ""}">${semTag(x.id)}<span>${hm(x.minutes)}</span></li>`).join("")}</ol>` });
  } else {
    const ps = feat("people") ? d.people.filter(x => people[x.id] && (!who || people[x.id].seminars?.includes(who.slice(4)))) : [];
    if (ps.length) s.push({ cls: "yellow", html: `<div class="k">Who added the most</div><h2>${esc(people[ps[0].id].name)}</h2>
      <ol class="rank">${ps.slice(0, 5).map(x => `<li>${avatar(people[x.id], "sm")}<b>${esc(people[x.id].name)}</b><span>${hm(x.minutes)}</span></li>`).join("")}</ol>` });
  }
  const f = feat("people") ? d.fun : null, pl = (n, unit) => `${num(n)} ${unit}${n === 1 ? "" : "s"}`;
  if (f && you && f.people[0]) {
    const r = f.people[0], t = r.againTrack;
    s.push({ cls: "black", html: `<div class="k">Habits</div><h2>${pl(r.added, "song")} added</h2>
      ${t ? `<p class="lead">One of them ${r.again} times: ${esc(t.title)}.</p>` : ""}
      <p>${r.skips ? `Pressed Next on ${pl(r.skips, "song")}` : "Never skipped a song"}${r.cuts ? `, cut ${pl(r.cuts, "song")} short with Play now` : ""}.
      ${r.skipped ? ` Others skipped ${pl(r.skipped, "song")} of theirs.` : ""}</p>` });
  } else if (f && f.awards.length) {
    s.push({ cls: "yellow", html: `<div class="k">The awards</div><h2>And the winners are</h2>
      <ol class="rank">${f.awards.slice(0, 6).map(a => `<li>${avatar(people[a.ids[0]], "sm")}<b>${esc(a.title)}: ${esc(a.ids.map(id => people[id]?.name || "").join(" and "))}</b>
        <span>${pl(a.n, a.unit)}</span></li>`).join("")}</ol>` });
  }
  s.push({ cls: "blue", html: `<div class="k">${esc(label)} · ${esc(name)}</div><h2>That was the recap</h2>
    <div class="sum"><div><b>${num(d.minutes)}</b>minutes</div><div><b>${num(d.songs)}</b>songs</div><div><b>${num(d.artists)}</b>artists</div></div>
    ${t ? `<p class="lead">#1: ${esc(t.title)}</p>` : ""}
    <div class="acts"><button class="btn red" data-act="recap-play">Play the top songs</button><button class="btn" data-act="recap-close">Close</button></div>`, stay: true });
  return s;
}

export async function openRecap() {
  if (!feat("recap")) return;
  const v = statsView(), r = range(v.period, v.from, v.to);
  box.innerHTML = `<div class="slide black"><div class="in"><div class="k">${esc(house.name)} recap</div><h2>Counting…</h2></div></div>`;
  box.classList.add("open"); document.body.classList.add("recap-open");
  let d;
  try { d = await fetchStats(r, v.who); } catch (e) { closeRecap(); toast(errText(e)); return; }
  top = d.topSongs; slides = build(d, v.who, r.label); at = 0;
  box.innerHTML = `<div class="bars">${slides.map(() => "<i><b></b></i>").join("")}</div>
    <button class="x" data-act="recap-close" aria-label="Close">✕</button><div class="stage"></div>`;
  show(0);
}

function show(i) {
  at = Math.max(0, Math.min(i, slides.length - 1));
  const s = slides[at];
  box.querySelector(".stage").innerHTML = `<div class="slide ${s.cls}">${s.bg ? `<div class="bg" style="background-image:url('${esc(s.bg)}')"></div>` : ""}<div class="in">${s.html}</div></div>`;
  box.querySelectorAll(".bars i").forEach((el, k) => { el.className = k < at ? "done" : ""; });
  left = SLIDE_MS; run();
}

function run() {
  clearTimeout(timer);
  const bar = box.querySelectorAll(".bars i")[at];
  if (!bar) return;
  if (slides[at].stay) { bar.className = "done"; return; }
  bar.className = "go"; bar.firstChild.style.animationDuration = SLIDE_MS + "ms";
  started = Date.now();
  timer = setTimeout(() => show(at + 1), left);
}
function pause() { if (held || slides[at]?.stay) return; held = true; clearTimeout(timer); left -= Date.now() - started; box.classList.add("paused"); }
function resume() { if (!held) return; held = false; box.classList.remove("paused"); started = Date.now(); timer = setTimeout(() => show(at + 1), left); }

export function closeRecap() {
  clearTimeout(timer); box.classList.remove("open", "paused"); document.body.classList.remove("recap-open"); held = false;
}
export const recapOpen = () => box.classList.contains("open");

let downAt = 0;
box.addEventListener("pointerdown", e => { if (e.target.closest("button")) return; downAt = Date.now(); setTimeout(() => { if (downAt) pause(); }, 250); });
box.addEventListener("pointerup", e => {
  if (e.target.closest("button") || !downAt) return;
  const tap = Date.now() - downAt < 250; downAt = 0;
  if (held) return resume();
  if (tap) show(e.clientX < innerWidth / 3 ? at - 1 : at + 1);
});
document.addEventListener("keydown", e => {
  if (!recapOpen()) return;
  e.stopImmediatePropagation();                /* the player's shortcuts wait until the recap is closed */
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); show(at + 1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); show(at - 1); }
  else if (e.key === "Escape") closeRecap();
}, true);

on("recap-open", openRecap);
on("recap-close", closeRecap);
on("recap-play", () => { if (top.length) { lists.recap = top; queueSongs(top, "replace", "Recap top songs"); } closeRecap(); });
