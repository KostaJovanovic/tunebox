/* Small helpers every Tunebox page uses. */

export const $ = s => document.querySelector(s);
export const $$ = s => [...document.querySelectorAll(s)];

/* HTML-escape anything that goes into innerHTML */
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const pad = n => String(n).padStart(2, "0");
export const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${pad(s % 60)}`; };   /* 225 -> "3:45" */
export const secs = d => String(d || "").split(":").reduce((a, x) => a * 60 + (+x || 0), 0);                    /* "3:45" -> 225 */
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
/* bytes as "12 MB" or "3.4 GB" */
export const size = b => b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(b >= 10 * 2 ** 30 ? 0 : 1)} GB` : `${b ? Math.max(1, Math.round(b / 2 ** 20)) : 0} MB`;

export const cookie = k => (document.cookie.match(new RegExp(`(?:^|; )${k}=([^;]*)`)) || [])[1] || "";
export const setCookie = (k, v, maxAge = 31536000) => { document.cookie = `${k}=${v}; path=/; max-age=${maxAge}; SameSite=Lax`; };

/* for CSS url("..."): a quote, backslash or newline in a URL would end the string early */
export const cssUrl = u => `url("${String(u).replace(/["\\\n]/g, encodeURIComponent)}")`;

export function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* a cover that fails to load (YouTube sometimes refuses one) shows an empty tile, not the broken-image icon */
const BLANK = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";   /* 1x1 transparent */
addEventListener("error", e => {
  const im = e.target;
  if (im.tagName === "IMG" && im.src !== BLANK) im.src = BLANK;
}, true);
