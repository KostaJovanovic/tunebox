/* The Settings drawer: volume, equaliser, playback options, sleep timer, wake-up alarm, YouTube account
   and this device's look. The server keeps everything except "This device". */
import { $, $$, esc, fmt } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { state, poll, setVolume } from "../../shared/playback.js";
import { store, ACCENTS, applyLook, clearLocal, weak } from "../../shared/device.js";
import { house } from "../../shared/house.js";
import { VERSION } from "../../shared/version.js";
import { on } from "../../shared/actions.js";
import { toast, openDrawer, clearHash, onCloseAll } from "./ui.js";
import { withAdmin } from "./phrase.js";
import { copyText } from "./menu.js";
import { ask } from "../../shared/dialog.js";

const FREQ_LABEL = f => f >= 1000 ? `${f / 1000}k` : String(f);
const PRESET_NAMES = { flat: "Flat", bass: "Bass", treble: "Treble", vocal: "Vocal", rock: "Rock", pop: "Pop", electronic: "Electro",
  jazz: "Jazz", classical: "Classical", loudness: "Loudness", night: "Night", custom: "Custom" };
const QUALITY_NAMES = { best: ["Best", "≈160 kbps"], balanced: ["Balanced", "≈70 kbps"], low: ["Data saver", "≈50 kbps"] };
const SLEEPS = [["Off", 0], ["15 min", 15], ["30 min", 30], ["45 min", 45], ["60 min", 60], ["90 min", 90], ["2 hours", 120], ["End of track", "track"]];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const fmtGain = g => (g > 0 ? "+" : g < 0 ? "−" : "") + Math.abs(Math.round(g));
/* the volume number with its level in dB underneath (every 10 on the slider is 5 dB) */
const volLabel = v => `${v}<small>${v <= 0 ? "MUTE" : v >= 100 ? "0 dB" : "−" + ((100 - v) / 2).toFixed(v % 2 ? 1 : 0) + " dB"}</small>`;

let cfg = null;                                /* the last /api/settings */

export function toggleSettings(open) {
  if (open) loadSettings();
  openDrawer("settings", open);
  if (!open) clearHash();
}

let net = {};                                  /* the last /api/network */
async function loadSettings() {
  /* finding the network can take a moment (it may ask the system): the rest doesn't wait for it */
  api("api/network").then(n => { net = n; if (cfg) renderNetwork(); }, () => {});
  cfg = await api("api/settings"); renderSettings();
}

function renderSettings() {
  const presets = { ...cfg.presets, custom: cfg.eq.custom };
  $("#presets").innerHTML = Object.keys(presets).map(k =>
    `<button data-p="${k}" class="${cfg.eq.preset === k ? "on" : ""}">${spark(presets[k])}${PRESET_NAMES[k] || k}</button>`).join("");
  $("#eqName").textContent = PRESET_NAMES[cfg.eq.preset] || "";
  bands = [...cfg.bands]; buildEq();
  $("#optNorm").setAttribute("aria-checked", cfg.normalize);
  $("#optAuto").setAttribute("aria-checked", cfg.autoplay);
  $("#optTurns").setAttribute("aria-checked", cfg.turns);
  $("#quality").innerHTML = cfg.qualities.map(q => `<button data-q="${q}" class="${cfg.quality === q ? "on" : ""}">${QUALITY_NAMES[q][0]}<small>${QUALITY_NAMES[q][1]}</small></button>`).join("");
  renderAlarm();
  $("#acctDot").classList.toggle("ok", cfg.account.signedIn);
  $("#acctTxt").textContent = cfg.account.signedIn ? "Signed in: personal recommendations" : "Not signed in: anonymous recommendations";
  $("#acctOut").hidden = !cfg.account.signedIn;
  renderDevice(); renderNetwork();
}

/* ---------- network: where the server is, as this page reaches it (same port and path, the server's own address) ---------- */
const netUrl = () => net.ip ? `${location.protocol}//${net.ip}${location.port ? ":" + location.port : ""}${location.pathname}` : "";
function renderNetwork() {
  const n = net, url = netUrl();
  $("#netUrl").textContent = url || "Not found"; $("#netUrl").href = url || "./";
  $("[data-act=net-copy]").hidden = !url;
  $("#netWifi").textContent = n.wifi || "";
  $("#netWifi").hidden = $("#netWifiLbl").hidden = !n.wifi;
}

/* ---------- volume ---------- */
let volTouch = 0, preMute = 60;
/* the sliders follow the server, except for 2 seconds after someone here moved one */
export const volumeTouched = () => Date.now() - volTouch < 2000;

export function setVol(v) {
  v = setVolume(v); volTouch = Date.now();
  $("#vol").value = $("#vol2").value = $("#cVol").value = v; $("#volN").innerHTML = $("#volP").innerHTML = volLabel(v);
  if (document.body.classList.contains("vol-open")) volPop(true);
}
export const nudgeVol = d => setVol(+$("#vol2").value + d);
export function toggleMute() {
  const v = +$("#vol2").value;
  if (v > 0) { preMute = v; setVol(0); toast("Muted"); } else { setVol(preMute || 60); toast("Unmuted"); }
}
export function paintVolume(s) {
  if (volumeTouched()) return;
  $("#vol").value = $("#vol2").value = s.volume; $("#volN").innerHTML = $("#volP").innerHTML = volLabel(Math.round(s.volume));
}
/* a phone's volume button: a small bar over the player; it goes after 4 seconds untouched, a tap elsewhere or Esc */
let volTimer = 0;
function volPop(open) {
  document.body.classList.toggle("vol-open", open);
  clearTimeout(volTimer);
  if (open) volTimer = setTimeout(() => volPop(false), 4000);
}
document.addEventListener("pointerdown", e => {
  if (document.body.classList.contains("vol-open") && !e.target.closest(".vol, .volbtn")) volPop(false);
}, true);
onCloseAll(() => volPop(false));
$("#vol").addEventListener("input", () => setVol(+$("#vol").value));
$("#vol2").addEventListener("input", () => setVol(+$("#vol2").value));

/* ---------- equaliser: columns with draggable square knobs, and a smooth response curve ---------- */
let bands = [];
const Y = g => 100 - g * (88 / 12);            /* svg y for a gain (viewBox 0..200, ±12 dB at 12/188) */

/* the preset buttons' little curve */
function spark(g) {
  const pts = g.map((v, i) => `${(i / (g.length - 1) * 44).toFixed(1)},${(7 - v * 0.55).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 44 14"><polyline points="${pts}"/></svg>`;
}

/* a smooth curve through the points (Catmull-Rom as cubic Béziers) */
function curvePath(pts) {
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0]},${p2[1].toFixed(1)}`;
  }
  return d;
}

function buildEq() {
  $("#eqcols").innerHTML = cfg.freqs.map((f, i) => `<div class="eqc" data-i="${i}" tabindex="0" role="slider" aria-orientation="vertical"
    aria-label="${FREQ_LABEL(f)} Hz" aria-valuemin="-12" aria-valuemax="12"><div class="bar"></div><div class="knob"></div></div>`).join("");
  $("#eqfoot").innerHTML = cfg.freqs.map((f, i) => `<div><b id="g${i}"></b><small>${FREQ_LABEL(f)}</small></div>`).join("");
  drawEq();
}

function drawEq() {
  const cols = $$("#eqcols .eqc"), pct = y => `${y / 2}%`;
  bands.forEach((g, i) => {
    const c = cols[i];
    if (!c) return;
    const bar = c.querySelector(".bar");
    bar.style.top = pct(Math.min(Y(g), 100)); bar.style.height = pct(Math.abs(Y(g) - 100)); bar.classList.toggle("neg", g < 0);
    c.querySelector(".knob").style.top = pct(Y(g));
    c.setAttribute("aria-valuenow", g); c.setAttribute("aria-valuetext", `${fmtGain(g)} dB`);
    $(`#g${i}`).textContent = fmtGain(g);
  });
  const pts = bands.map((g, i) => [(i + 0.5) * 100, Y(g)]);
  const line = curvePath([[0, pts[0][1]], ...pts, [1000, pts[pts.length - 1][1]]]);
  $("#eqCurve").setAttribute("d", line);
  $("#eqArea").setAttribute("d", `${line} L1000,100 L0,100 Z`);
}

/* a knob moved: it's the custom curve now, sent while dragging (one request at a time, the latest wins) */
function bandChanged() {
  drawEq();
  $$("#presets button").forEach(b => b.classList.toggle("on", b.dataset.p === "custom"));
  $("#eqName").textContent = "Custom";
  sendBands();
}
let eqSending = false, eqAgain = false;
async function sendBands() {
  if (eqSending) { eqAgain = true; return; }
  eqSending = true;
  try { await setEq("custom", [...bands], true); }
  finally { eqSending = false; if (eqAgain) { eqAgain = false; sendBands(); } }
}

function gainAt(col, clientY) {
  const r = col.getBoundingClientRect(), yv = (clientY - r.top) / r.height * 200;
  return Math.max(-12, Math.min(12, Math.round((100 - yv) * 12 / 88)));
}

$("#eqcols").addEventListener("pointerdown", e => {
  const col = e.target.closest(".eqc");
  if (!col) return;
  const i = +col.dataset.i;
  col.setPointerCapture(e.pointerId); col.classList.add("drag"); col.focus({ preventScroll: true });
  const move = ev => { const g = gainAt(col, ev.clientY); if (g !== bands[i]) { bands[i] = g; bandChanged(); } };
  move(e);
  col.onpointermove = move;
  col.onpointerup = col.onpointercancel = () => { col.onpointermove = null; col.classList.remove("drag"); };
});

$("#eqcols").addEventListener("keydown", e => {
  const col = e.target.closest(".eqc");
  if (!col) return;
  const i = +col.dataset.i, step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 3, PageDown: -3 }[e.key];
  let g = bands[i];
  if (step) g += step; else if (e.key === "Home") g = 12; else if (e.key === "End") g = -12; else if (e.key === "0" || e.key === "Delete") g = 0; else return;
  e.preventDefault(); e.stopPropagation();
  bands[i] = Math.max(-12, Math.min(12, g)); bandChanged();
});

/* live: sent mid-drag, so the knobs aren't redrawn under the finger */
async function setEq(preset, custom, live = false) {
  try {
    cfg = await api("api/eq", custom ? { preset, custom } : { preset });
    $("#eqMsg").textContent = ""; $("#eqMsg").className = "msg";
    if (!live) renderSettings();
  } catch (e) { $("#eqMsg").textContent = errText(e); $("#eqMsg").className = "msg err"; }
}
$("#presets").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setEq(b.dataset.p); });

/* ---------- playback options ---------- */
async function setOpt(key, btn) {
  const on = btn.getAttribute("aria-checked") !== "true";
  btn.setAttribute("aria-checked", on);
  cfg = await api("api/options", { [key]: on }); renderSettings();
}
/* ---------- backup: restore from a downloaded file ---------- */
$("#restoreFile").addEventListener("change", async e => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  let backup;
  try { backup = JSON.parse(await f.text()); } catch { return toast("That file isn't a Tunebox backup"); }
  const made = backup.made ? new Date(backup.made * 1000).toLocaleString() : "an unknown date";
  if (!(await ask(`Restore the backup from ${made}? It replaces people, playlists, likes, history, stats and settings for everyone.`, { ok: "Restore", danger: true }))) return;
  try {
    if (await withAdmin(() => api("api/restore", { backup })) === null) return;
    toast("Restored"); setTimeout(() => location.reload(), 900);
  } catch (err) { toast(errText(err), false, "error"); }
});

$("#quality").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  cfg = await api("api/options", { quality: b.dataset.q }); renderSettings();
  toast(`Quality: ${QUALITY_NAMES[b.dataset.q][0]}`);
});

/* ---------- sleep timer ---------- */
$("#sleepBtns").innerHTML = SLEEPS.map(([n, v]) => `<button data-s="${v}">${n}</button>`).join("");
$("#sleepBtns").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  const v = b.dataset.s;
  await api("api/sleep", v === "track" ? { track: true } : { minutes: +v || null });
  poll();
});

/* after each poll: the timer's buttons and countdown, here and in the player bar */
export function paintSleep() {
  const s = state.sleep;
  $$("#sleepBtns button").forEach(b => b.classList.toggle("on", s ? (s.mode === "track" ? b.dataset.s === "track" : +b.dataset.s === s.minutes) : b.dataset.s === "0"));
  $("#sleepDot").classList.toggle("on", !!s);
  $("#sleepTxt").textContent = !s ? "Off" : s.mode === "track" ? "Stops after this track" : `Stops in ${fmt(s.left)}`;
  $("#sleepLeft").textContent = s && s.mode !== "track" ? new Date(Date.now() + s.left * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  $("#pSleep").textContent = !s ? "" : s.mode === "track" ? "☾ end of track" : `☾ ${fmt(s.left)}`;
}

/* ---------- wake-up alarm ---------- */
$("#alDays").innerHTML = DAYS.map((d, i) => `<button data-d="${i}" aria-pressed="false">${d.slice(0, 2)}</button>`).join("");
$("#alDays").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; b.classList.toggle("on"); saveAlarm(); });
for (const id of ["#alTime", "#alRamp", "#alList", "#alLevel"]) $(id).addEventListener("change", () => saveAlarm());
$("#alLevel").addEventListener("input", () => $("#alLevelN").innerHTML = volLabel(+$("#alLevel").value));

function renderAlarm() {
  const a = cfg.alarm;
  $("#alOn").setAttribute("aria-checked", a.enabled);
  $("#alTime").value = a.time; $("#alRamp").value = String(a.ramp);
  if (!$("#alRamp").value) $("#alRamp").value = "5";
  $$("#alDays button").forEach(b => { const on = a.days.includes(+b.dataset.d); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  $("#alList").innerHTML = `<option value="">Resume the queue</option>` + cfg.lists.map(p => `<option value="${esc(p.id)}">${esc(p.name)} · ${p.count} songs</option>`).join("");
  $("#alList").value = a.list || "";
  $("#alLevel").value = a.level; $("#alLevelN").innerHTML = volLabel(a.level);
  $("#alarmNext").textContent = a.enabled ? nextAlarm(a) : "Off";
}

function nextAlarm(a) {
  if (!a.days.length) return "On, but no days picked";
  const [h, m] = a.time.split(":").map(Number), now = new Date();
  for (let k = 0; k < 8; k++) {
    const d = new Date(now); d.setDate(now.getDate() + k); d.setHours(h, m, 0, 0);
    if (d > now && a.days.includes((d.getDay() + 6) % 7))
      return `Next: ${k === 0 ? "today" : k === 1 ? "tomorrow" : d.toLocaleDateString([], { weekday: "long" })} at ${a.time}`;
  }
  return "On";
}

async function saveAlarm(test = false) {
  const body = {
    enabled: $("#alOn").getAttribute("aria-checked") === "true", time: $("#alTime").value || "07:00",
    days: $$("#alDays button.on").map(b => +b.dataset.d), list: $("#alList").value || null,
    level: +$("#alLevel").value, ramp: +$("#alRamp").value,
    test,
  };
  try {
    cfg = await api("api/alarm", body); renderAlarm();
    $("#alMsg").className = "msg"; $("#alMsg").textContent = test ? "Playing the alarm now." : `Saved · ${house.tz ? house.tz + " time" : "the server's time"}`;
    poll();
  } catch (e) { $("#alMsg").className = "msg err"; $("#alMsg").textContent = errText(e); }
}

/* ---------- YouTube account ---------- */
async function saveAccount() {
  const headers = $("#hdrs").value.trim();
  if (!headers) return;
  $("#acctMsg").className = "msg"; $("#acctMsg").textContent = "Checking with YouTube...";
  try {
    if (await withAdmin(() => api("api/account", { headers })) === null) return $("#acctMsg").textContent = "";
    $("#hdrs").value = ""; $("#acctMsg").textContent = "Saved. Home now uses your account."; loadSettings();
  }
  catch (e) { $("#acctMsg").className = "msg err"; $("#acctMsg").textContent = errText(e); }
}

async function signOut() {
  if (!(await ask("Remove the saved YouTube account from Tunebox?", { ok: "Remove", danger: true }))) return;
  if (await withAdmin(() => api("api/account", undefined, "DELETE")) === null) return;
  $("#acctMsg").textContent = "Signed out."; loadSettings();
}

/* ---------- this device: performance mode, theme, accent ---------- */
$("#perfSeg").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; store.set("tb_perf", b.dataset.p); applyLook(); renderDevice(); });
$("#accents").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; store.set("tb_accent", b.dataset.a); applyLook(); renderDevice(); });
$("#themeSeg").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; store.set("tb_theme", b.dataset.t); applyLook(); renderDevice(); });

/* the accent: this device's own, or the house's (when the admin set one) until it picks */
export function renderDevice() {
  const t = store.get("tb_theme", "auto"), own = store.get("tb_accent", ""), hs = ACCENTS[house.accent];
  const a = ACCENTS[own] ? own : hs ? "" : "red";
  $("#accents").innerHTML = (hs ? `<button class="acc all" data-a=""><i class="sw" style="background:${hs.c}"></i>The house's</button>` : "")
    + Object.entries(ACCENTS).map(([k, x]) => `<button class="acc" data-a="${k}"><i class="sw" style="background:${x.c}"></i>${x.name}</button>`).join("");
  $$("#themeSeg button").forEach(b => b.classList.toggle("on", b.dataset.t === t));
  const pm = store.get("tb_perf", "auto");
  $$("#perfSeg button").forEach(b => b.classList.toggle("on", b.dataset.p === pm));
  $("#perfHint").textContent = "No animations, no blur, and the player asks the server every 3 seconds instead of every second. "
    + (pm !== "auto" ? "" : weak() ? "Auto: on here; this device is low on memory or cores." : `Auto: off here; it comes on by itself on a device with 2 GB of memory or less${navigator.deviceMemory ? "" : " (this browser doesn't say how much it has)"} or 2 cores or fewer.`);
  $$("#accents button").forEach(b => b.classList.toggle("on", b.dataset.a === a));
}

$("#verN").textContent = VERSION;

/* ---------- wiring ---------- */
on("settings-open", () => { volPop(false); toggleSettings(true); });
on("vol-pop", () => volPop(!document.body.classList.contains("vol-open")));
on("settings-close", () => toggleSettings(false));
on("vol-nudge", el => nudgeVol(+el.dataset.d));
on("eq", el => setEq(el.dataset.preset));
on("option", el => setOpt(el.dataset.key, el));
on("alarm-toggle", el => { el.setAttribute("aria-checked", el.getAttribute("aria-checked") !== "true"); saveAlarm(); });
on("alarm-test", () => saveAlarm(true));
on("account-save", saveAccount);
on("account-out", signOut);
on("clear-local", clearLocal);
on("net-copy", () => copyText(netUrl(), "Address copied"));
