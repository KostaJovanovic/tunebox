/* The Settings drawer (same server settings as the Bauhaus interface, simpler controls): volume,
   equaliser, playback options, sleep timer, wake-up alarm, YouTube account, and this device. */
import { $, $$, esc, fmt } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { state, poll, setVolume } from "../../shared/playback.js";
import { store, applyLook, useUi, clearLocal } from "../../shared/device.js";
import { on } from "../../shared/actions.js";
import { syncScrim } from "./ui.js";
import { toggleQueue } from "./queue.js";

const vLabel = v => `${v}<small>${v <= 0 ? "mute" : v >= 100 ? "0 dB" : "−" + ((100 - v) / 2) + " dB"}</small>`;
const PN = { flat: "Flat", bass: "Bass", treble: "Treble", vocal: "Vocal", rock: "Rock", pop: "Pop", electronic: "Electro", jazz: "Jazz",
  classical: "Classical", loudness: "Loudness", night: "Night", custom: "Custom" };
const QN = { best: "Best", balanced: "Balanced", low: "Data saver" };
const SL = [["Off", 0], ["15 min", 15], ["30 min", 30], ["45 min", 45], ["60 min", 60], ["90 min", 90], ["2 h", 120], ["End of track", "track"]];
const DN = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
let cfg = null;

export function toggleSettings(open) {
  if (open) { toggleQueue(false); loadCfg(); }
  $("#settings").classList.toggle("open", open); syncScrim();
}

async function loadCfg() { cfg = await api("api/settings"); renderCfg(); }

function renderCfg() {
  $("#cPresets").innerHTML = [...Object.keys(cfg.presets), "custom"].map(k => `<button data-p="${k}" class="${cfg.eq.preset === k ? "on" : ""}">${PN[k] || k}</button>`).join("");
  $("#cEq").innerHTML = cfg.freqs.map((f, i) => `<label><b id="cg${i}">${cfg.bands[i] > 0 ? "+" : ""}${cfg.bands[i]}</b>
    <input type="range" min="-12" max="12" step="1" value="${cfg.bands[i]}" data-i="${i}" aria-label="${f} Hz">${f >= 1000 ? f / 1000 + "k" : f}</label>`).join("");
  $("#cNorm").setAttribute("aria-checked", cfg.normalize); $("#cAuto").setAttribute("aria-checked", cfg.autoplay); $("#cTurns").setAttribute("aria-checked", cfg.turns);
  $("#cQual").innerHTML = cfg.qualities.map(q => `<button data-q="${q}" class="${cfg.quality === q ? "on" : ""}">${QN[q]}</button>`).join("");
  const a = cfg.alarm;
  $("#cAlOn").setAttribute("aria-checked", a.enabled); $("#cAlTime").value = a.time; $("#cAlRamp").value = String(a.ramp);
  $("#cAlDays").innerHTML = DN.map((d, i) => `<button data-d="${i}" class="${a.days.includes(i) ? "on" : ""}">${d}</button>`).join("");
  $("#cAlList").innerHTML = `<option value="">Resume the queue</option>` + cfg.lists.map(p => `<option value="${esc(p.id)}">${esc(p.name)} · ${p.count} songs</option>`).join("");
  $("#cAlList").value = a.list || ""; $("#cAlLevel").value = a.level; $("#cAlLevelN").innerHTML = vLabel(a.level);
  $("#cAlNext").textContent = a.enabled ? `On at ${a.time}` : "Off";
  $("#cAcct").textContent = cfg.account.signedIn ? "Signed in: personal recommendations" : "Not signed in: anonymous recommendations";
  $("#cOut").hidden = !cfg.account.signedIn;
  const t = store.get("tb_theme", "auto");
  $$("#cTheme button").forEach(b => b.classList.toggle("on", b.dataset.t === t));
}

/* ---------- volume: the bar's slider and the one in here move together ---------- */
let volTouch = 0;
function setVol(v) {
  v = setVolume(v); volTouch = Date.now();
  $("#vol").value = $("#svol").value = v; $("#svolN").innerHTML = vLabel(v);
}
export function paintVolume(s) {
  if (Date.now() - volTouch < 2000 || s.volume === undefined) return;
  $("#vol").value = $("#svol").value = s.volume; $("#svolN").innerHTML = vLabel(Math.round(s.volume));
}
$("#vol").addEventListener("input", () => setVol(+$("#vol").value));
$("#svol").addEventListener("input", () => setVol(+$("#svol").value));

/* ---------- equaliser ---------- */
async function setEq(preset, custom, live = false) {
  try { cfg = await api("api/eq", custom ? { preset, custom } : { preset }); $("#cEqMsg").textContent = ""; if (!live) renderCfg(); }
  catch (e) { $("#cEqMsg").textContent = errText(e); $("#cEqMsg").className = "note2 err"; }
}
$("#cPresets").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setEq(b.dataset.p); });
$("#cEq").addEventListener("input", e => {
  const i = e.target.dataset.i;
  if (i === undefined) return;
  $(`#cg${i}`).textContent = (+e.target.value > 0 ? "+" : "") + e.target.value;
  $$("#cPresets button").forEach(b => b.classList.toggle("on", b.dataset.p === "custom"));
  sendBands();
});
/* sent while dragging, one request at a time (the latest wins); the sliders aren't redrawn meanwhile */
let eqSending = false, eqAgain = false;
async function sendBands() {
  if (eqSending) { eqAgain = true; return; }
  eqSending = true;
  try { await setEq("custom", $$("#cEq input").map(x => +x.value), true); }
  finally { eqSending = false; if (eqAgain) { eqAgain = false; sendBands(); } }
}

/* ---------- playback options ---------- */
async function setOpt(key, btn) {
  const on = btn.getAttribute("aria-checked") !== "true";
  btn.setAttribute("aria-checked", on);
  cfg = await api("api/options", { [key]: on }); renderCfg();
}
$("#cQual").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  cfg = await api("api/options", { quality: b.dataset.q }); renderCfg();
});

/* ---------- sleep timer ---------- */
$("#cSleep").innerHTML = SL.map(([n, v]) => `<button data-s="${v}">${n}</button>`).join("");
$("#cSleep").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  await api("api/sleep", b.dataset.s === "track" ? { track: true } : { minutes: +b.dataset.s || null });
  poll();
});
export function paintSleep() {
  const s = state.sleep;
  $$("#cSleep button").forEach(b => b.classList.toggle("on", s ? (s.mode === "track" ? b.dataset.s === "track" : +b.dataset.s === s.minutes) : b.dataset.s === "0"));
  $("#cSleepTxt").textContent = !s ? "Off · fades out gently, then pauses" : s.mode === "track" ? "Stops after this track" : `Stops in ${fmt(s.left)}`;
}

/* ---------- wake-up alarm ---------- */
$("#cAlDays").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; b.classList.toggle("on"); saveAlarm(); });
for (const id of ["#cAlTime", "#cAlRamp", "#cAlList", "#cAlLevel"]) $(id).addEventListener("change", () => saveAlarm());
$("#cAlLevel").addEventListener("input", () => $("#cAlLevelN").innerHTML = vLabel(+$("#cAlLevel").value));

async function saveAlarm(test = false) {
  const body = { enabled: $("#cAlOn").getAttribute("aria-checked") === "true", time: $("#cAlTime").value || "07:00",
    days: $$("#cAlDays button.on").map(b => +b.dataset.d), list: $("#cAlList").value || null, level: +$("#cAlLevel").value,
    ramp: +$("#cAlRamp").value, tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Belgrade", test };
  try { cfg = await api("api/alarm", body); renderCfg(); $("#cAlMsg").className = "note2"; $("#cAlMsg").textContent = test ? "Playing the alarm now." : "Saved"; }
  catch (e) { $("#cAlMsg").className = "note2 err"; $("#cAlMsg").textContent = errText(e); }
}

/* ---------- YouTube account ---------- */
async function saveAccount() {
  const headers = $("#cHdrs").value.trim();
  if (!headers) return;
  $("#cAcctMsg").className = "note2"; $("#cAcctMsg").textContent = "Checking with YouTube…";
  try { await api("api/account", { headers }); $("#cHdrs").value = ""; $("#cAcctMsg").textContent = "Saved."; loadCfg(); }
  catch (e) { $("#cAcctMsg").className = "note2 err"; $("#cAcctMsg").textContent = errText(e); }
}
async function signOut() {
  if (!confirm("Remove the saved YouTube account from Tunebox?")) return;
  await api("api/account", undefined, "DELETE");
  loadCfg();
}

/* ---------- this device ---------- */
$("#cTheme").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  store.set("tb_theme", b.dataset.t); applyLook(); renderCfg();
});

on("settings-open", () => toggleSettings(true));
on("settings-close", () => toggleSettings(false));
on("option", el => setOpt(el.dataset.key, el));
on("alarm-toggle", el => { el.setAttribute("aria-checked", el.getAttribute("aria-checked") !== "true"); saveAlarm(); });
on("alarm-test", () => saveAlarm(true));
on("account-save", saveAccount);
on("account-out", signOut);
on("use-ui", el => useUi(el.dataset.ui));
on("clear-local", clearLocal);
