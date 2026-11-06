/* yt-dlp, which finds each song's audio on YouTube. YouTube changes often and an old yt-dlp stops songs
   loading: when they keep failing, /api/state says so to the admin (s.ytdlp) and a bar along the top
   offers the update. The admin panel's yt-dlp tab shows the versions and updates it too (tunebox/ytdlp.py). */
import { $, esc } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { onState } from "../../shared/playback.js";
import { on } from "../../shared/actions.js";
import { toast, loading } from "./ui.js";
import { withAdmin } from "./phrase.js";

let shut = 0;                                  /* the failure count the bar was closed at: it comes back when more fail */
let busy = false, refresh = null;

const bar = Object.assign(document.createElement("div"), { id: "ytdlpBar", hidden: true });
bar.setAttribute("role", "status");
document.body.append(bar);

onState(s => {
  const w = s.ytdlp;
  if (!w || w.fails <= shut) { bar.hidden = true; if (!w) shut = 0; return; }
  bar.hidden = false;
  const text = w.restart ? "yt-dlp was updated. Restart Tunebox to use it."
    : "Songs are failing to load. yt-dlp may be out of date.";
  if (bar.dataset.text === text + busy) return;
  bar.dataset.text = text + busy;
  bar.innerHTML = `<span>${esc(text)}</span>`
    + (w.restart ? "" : `<button data-act="ytdlp-update"${busy || w.busy ? " disabled" : ""}>${busy || w.busy ? "Updating…" : "Update"}</button>`)
    + `<button class="x" data-act="ytdlp-shut" aria-label="Close">&times;</button>`;
  bar.dataset.fails = w.fails;
});

async function update() {
  if (busy) return;
  busy = true; bar.dataset.text = "";
  toast("Updating yt-dlp, this takes a minute");
  refresh?.();
  try {
    const r = await withAdmin(() => api("api/admin/ytdlp", {}));
    if (r) toast(r.msg);
  } catch (e) { toast(errText(e)); }
  finally { busy = false; bar.dataset.text = ""; refresh?.(); }
}

/* ---------- the admin panel's tab ---------- */
export async function showYtdlp(el) {
  refresh = () => { if (el.dataset.tab === "ytdlp") showYtdlp(el); };
  if (!el.innerHTML.includes("ytdlpTab")) el.innerHTML = loading("Asking");
  const v = await withAdmin(() => api("api/admin/ytdlp"));
  if (v === null || el.dataset.tab !== "ytdlp") return;
  const w = v.warning, b = busy || v.busy;
  const line = v.restart
    ? `${esc(v.installed)} is installed, ${esc(v.running)} is playing. Restart Tunebox to use the new one.`
    : `Version ${esc(v.running)}${v.latest ? v.outdated ? `, and ${esc(v.latest)} is out.` : ", the newest." : "."}`;
  el.innerHTML = `<div class="sec" id="ytdlpTab"><h2>yt-dlp</h2></div>
    <div class="body"><p>It finds each song's audio on YouTube. YouTube changes often, and an old yt-dlp is the usual reason songs stop loading.</p>
      <p>${line}</p>
      ${w ? `<p class="warn">The last ${w.fails} songs failed to load${w.last ? `: ${esc(w.last)}` : "."}</p>` : ""}
      <div class="eqtools"><button class="btn" data-act="ytdlp-update"${b ? " disabled" : ""}>${b ? "Updating…" : "Update yt-dlp"}</button></div>
      ${v.last?.msg ? `<p class="hint">${esc(v.last.msg)}</p>` : ""}
      <p class="hint">Only yt-dlp is updated, with the server's own Python. From a terminal: <code>tunebox update-ytdlp</code>.</p></div>`;
}

on("ytdlp-update", update);
on("ytdlp-shut", () => { shut = +bar.dataset.fails || 0; bar.hidden = true; });
