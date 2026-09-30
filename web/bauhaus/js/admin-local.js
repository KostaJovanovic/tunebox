/* The admin panel's Local songs tab: how full the disk is and how much of it the uploaded songs take,
   the limits on them (a cap in all, free space to always leave, the biggest file), what this mpv can
   convert to, and the full backup with the audio in it. */
import { $, esc, plural, size } from "../../shared/dom.js";
import { api, errText } from "../../shared/api.js";
import { isOn } from "../../shared/house.js";
import { toast, loading } from "./ui.js";
import { withAdmin } from "./phrase.js";

const GB = 2 ** 30;
const call = (path, body, method) => withAdmin(() => api(path, body, method));
const pct = (n, of) => of ? Math.max(0, Math.min(100, n / of * 100)).toFixed(2) : 0;

export async function showLocalSpace(el) {
  if (!el.querySelector("#admLimits")) el.innerHTML = loading("Loading");
  let d;
  try { d = await call("api/admin/local/disk"); } catch (e) { el.innerHTML = `<div class="body"><p>${esc(errText(e))}</p></div>`; return; }
  if (d === null || el.dataset.tab !== "local") return;
  const other = d.total - d.free - d.used, enc = d.encoders;
  const yes = (ok, what, then, otherwise) => `<div class="arow"><div class="min0"><div class="t">${what}${ok ? "" : '<i class="mark">missing</i>'}</div><div class="s">${ok ? then : otherwise}</div></div></div>`;
  el.innerHTML = `<div class="sec"><h2>Room</h2><span class="aside">${plural(d.count, "song")} · ${size(d.used)}</span></div>
    <div class="body">${isOn("local") ? "" : "<p>Local songs are switched off in the Features tab: nobody uploads, and the songs already here stay.</p>"}
      <span class="lbl">The disk</span>
      <div class="meter" role="img" aria-label="Disk use"><i class="other" style="width:${pct(other, d.total)}%"></i><i class="mine" style="width:${pct(d.used, d.total)}%"></i></div>
      <p class="hint">${size(d.free)} free of ${size(d.total)}. Local songs take ${size(d.used)}, everything else ${size(other)}.</p>
      ${d.capGB === null ? "" : `<span class="lbl">The cap</span>
      <div class="meter" role="img" aria-label="Use of the cap"><i class="mine" style="width:${pct(d.used, d.capGB * GB)}%"></i></div>
      <p class="hint">${size(d.used)} of ${d.capGB} GB.</p>`}
      <p class="hint">${d.room ? `Room for ${size(d.room)} more.` : "<b>No room left:</b> uploads are refused."}</p>
    </div>
    <div class="sec"><h2>Limits</h2></div>
    <div class="body">
      <form class="aform" id="admLimits">
        <label for="admCap">The most local songs may take in all, in GB (empty: no cap)</label>
        <input class="field num" id="admCap" type="number" min="0" step="0.5" inputmode="decimal" value="${d.capGB ?? ""}" placeholder="No cap">
        <label for="admReserve">Free space to always leave on the disk, in GB</label>
        <input class="field num" id="admReserve" type="number" min="0" step="0.5" inputmode="decimal" value="${d.reserveGB}">
        <label for="admMax">The biggest file, in MB</label>
        <input class="field num" id="admMax" type="number" min="1" max="4096" step="1" inputmode="numeric" value="${d.maxMB}">
        <button class="btn">Save</button></form>
    </div>
    <div class="sec"><h2>Converting</h2></div>
    <div class="body"><p>mp3, FLAC, m4a, Ogg and Opus files are kept as they are. The rest are converted once, by the player itself, one at a time.</p>
      ${yes(enc.mpv && enc.flac, "WAV and AIFF to FLAC", "Lossless, about half the size.", "This mpv has no FLAC encoder: these files are kept as uploaded.")}
      ${yes(enc.mpv && enc.opus, "Anything else to Opus", "160 kbit/s.", "This mpv has no Opus encoder: these files are kept as uploaded.")}
    </div>
    <div class="sec"><h2>Full backup</h2></div>
    <div class="body"><p>The backup in Settings has the local songs' names, not their audio. This one is a zip with both: the backup file, and a <code>local</code> folder with every song and cover.</p>
      <div class="eqtools"><a class="btn" href="api/backup/full" download>Download the full backup</a></div>
      <p class="hint">To bring it back: unzip the <code>local</code> folder into the data folder on the server, then restore <code>tunebox-backup.json</code> in Settings.</p>
    </div>`;
  $("#admLimits").addEventListener("submit", async e => {
    e.preventDefault();
    const cap = $("#admCap").value.trim(), num = id => +$(id).value;
    try {
      const r = await call("api/admin/local/limits", { capGB: cap === "" ? -1 : +cap, reserveGB: num("#admReserve"), maxMB: Math.round(num("#admMax")) }, "PATCH");
      if (r === null) return;
      toast("Saved"); showLocalSpace(el);
    } catch (err) { toast(errText(err)); }
  });
}
