/* Small helpers every Tunebox page uses. */
import { calm } from "./motion.js";

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

/* A song without a cover gets a drawn one: headphones, a record or a note, in grey so it sits on either
   theme. The pick is a hash of the seed (the song's id), so a song keeps the same one on every redraw. */
const DRAWN = [
  '<path d="M30 60v-10a18 18 0 0 1 36 0v10"/><rect x="25" y="56" width="10" height="16"/><rect x="61" y="56" width="10" height="16"/>',
  '<circle cx="48" cy="48" r="22"/><circle cx="48" cy="48" r="15" stroke-width="1.5"/><circle cx="48" cy="48" r="6"/><circle cx="48" cy="48" r="1.5" fill="#8a8a8a"/>',
  '<path d="M54 64V28l14 6v8l-14-6"/><ellipse cx="46" cy="64" rx="8" ry="6" fill="#8a8a8a"/>',
].map(s => "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" fill="none" stroke="#8a8a8a" stroke-opacity=".7" stroke-width="3" stroke-linecap="square">${s}</svg>`));
export const drawn = seed => DRAWN[[...String(seed ?? "")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % DRAWN.length];
/* a song's (or anything's) cover, or a drawn one when it has none */
export const art = t => t?.thumb || drawn(t?.videoId || t?.id || t?.title || t?.name);

/* The same cover at full size, or "" when it has none: YouTube Music's covers are sized in the URL
   (=w120-h120...), a video's is maxresdefault (missing for some videos, so load it before showing it). */
export function bigArt(u) {
  u = String(u || "");
  if (/^https:\/\/[\w.-]+\.googleusercontent\.com\//.test(u)) return u.replace(/=w\d+-h\d+/, "=w1200-h1200").replace(/=s\d+(?=-|$)/, "=s1200");
  const v = u.match(/^https:\/\/i\.ytimg\.com\/vi\/([\w-]+)\//);
  return v ? `https://i.ytimg.com/vi/${v[1]}/maxresdefault.jpg` : "";
}

/* A big <img> keyed by dataset.src shows the cover every view has at once (often 120 px), then the
   full-size one once it has loaded, if YouTube has one and the img still shows the same song. */
export function sharpen(img, t) {
  const big = bigArt(t?.thumb), im = new Image();
  if (!big || big === t.thumb) return;
  im.onload = () => { if (img.dataset.src === art(t)) fadeTo(img, big); };
  im.src = big;
}

/* A song's cover into a big <img>: the small one (fading in over the last song's), then the full-size one */
export function showCover(img, t) {
  img.dataset.src = art(t);
  fadeTo(img, art(t)); sharpen(img, t);
}

/* Shows src in img without a blank moment: it loads first, so the old picture stays until the new one is
   ready, then the old one fades out over it. At once with less motion or in performance mode. The last
   call wins. */
export function fadeTo(img, src) {
  img._want = src;
  const im = new Image();
  im.onload = im.onerror = () => {
    if (img._want !== src || img.getAttribute("src") === src) return;
    if (!calm() && img.isConnected && img.complete && img.naturalWidth && img.offsetWidth) ghost(img);
    img.src = src;
  };
  im.src = src;
}
/* a copy of what img shows, laid exactly over it, fading away (whatever positions it: measured, not assumed) */
function ghost(img) {
  const g = img.cloneNode(), cs = getComputedStyle(img), r = img.getBoundingClientRect();
  for (const a of ["id", "data-act", "title", "loading"]) g.removeAttribute(a);
  g.setAttribute("aria-hidden", "true");
  Object.assign(g.style, { position: "absolute", left: "0", top: "0", margin: "0", pointerEvents: "none", boxShadow: "none", transform: "none",
    animation: "none", objectFit: cs.objectFit, objectPosition: cs.objectPosition, borderRadius: cs.borderRadius, transition: "opacity .4s ease" });
  img.after(g);
  const o = g.getBoundingClientRect();
  Object.assign(g.style, { left: `${r.left - o.left}px`, top: `${r.top - o.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  requestAnimationFrame(() => requestAnimationFrame(() => { g.style.opacity = "0"; }));
  setTimeout(() => g.remove(), 500);
}

/* a new song's title and line under it settle in (CSS .swapin, in each page's own styles) */
export function swapIn(...els) {
  if (calm()) return;
  for (const el of els) { el.classList.remove("swapin"); void el.offsetWidth; el.classList.add("swapin"); }
}

/* a cover that fails to load (YouTube sometimes refuses one) shows a drawn one, not the broken-image icon */
addEventListener("error", e => {
  const im = e.target;
  if (im.tagName === "IMG" && !im.src.startsWith("data:")) im.src = drawn(im.getAttribute("src"));
}, true);
