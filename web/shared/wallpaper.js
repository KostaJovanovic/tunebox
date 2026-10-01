/* The wallpaper (after Nothing OS 5's) in a song's cover colours: the wall's background, and the now
   playing canvas's. setupWallpaper() once, then wallpaperFor(song) whenever the song changes; it fills
   the window, and wallpaper.css draws and moves it.

   Three colours from the cover: its pixels grouped by hue, the groups that are most and most vividly
   there (paint() makes them chalky). A cover with too few hues borrows from
   the strongest one. YouTube's image servers allow reading the pixels (CORS); when that fails, colours
   from the song's id. */
let palFor = "";
export function wallpaperFor(c) {
  const key = c.thumb || c.videoId || "";
  if (key === palFor) return;
  palFor = key;
  const seed = c.videoId || c.title || "";
  const fallback = () => paint(hashed(seed), seed);
  if (!c.thumb) return fallback();
  const im = new Image();
  im.crossOrigin = "anonymous";
  im.onload = () => { if (palFor === key) try { paint(colours(im), seed); } catch { fallback(); } };
  im.onerror = fallback;
  im.src = c.thumb;
}
function colours(im) {
  const n = 24, cv = document.createElement("canvas");
  cv.width = cv.height = n;
  const x = cv.getContext("2d", { willReadFrequently: true });
  x.drawImage(im, 0, 0, n, n);
  const px = x.getImageData(0, 0, n, n).data, bins = Array.from({ length: 12 }, () => ({ w: 0, h: 0, s: 0, l: 0 }));
  for (let i = 0; i < px.length; i += 4) {
    const [h, s, l] = hsl(px[i], px[i + 1], px[i + 2]);
    if (l < .08 || l > .94) continue;
    const b = bins[Math.floor(h / 30) % 12], w = .15 + s;
    b.w += w; b.h += h * w; b.s += s * w; b.l += l * w;
  }
  const top = bins.filter(b => b.w > 1).sort((a, b) => b.w - a.w).slice(0, 3).map(b => [b.h / b.w, b.s / b.w, b.l / b.w]);
  if (!top.length) throw new Error("no colour");
  while (top.length < 3) top.push([(top[0][0] + 40 * top.length) % 360, top[0][1], top[0][2]]);
  return top;
}
function hsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}
const hashed = id => { const h = [...id].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7) % 360; return [h, h + 50, h + 160].map(x => [x % 360, .5, .45]); };

/* a song's own random numbers, so its wallpaper is the same every time it plays */
function rng(seed) {
  let a = [...String(seed)].reduce((h, ch) => Math.imul(h ^ ch.charCodeAt(0), 2654435761) >>> 0, 1779033703) || 1;
  return () => { a ^= a << 13; a >>>= 0; a ^= a >>> 17; a ^= a << 5; a >>>= 0; return a / 4294967296; };
}
const hslA = ([h, s, l], a = 1) => `hsl(${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}% / ${a})`;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* The wallpaper for these colours. Three to five big lights behind everything take them bright, the
   fewer the bigger, at even turns round the middle. Four soft discs take them muted, at every other of
   eight places round the edge, so they stay apart and balanced; the hairline circles start from the
   other four. Lights and discs each float on a slow path of their own (wallpaper.css); the circles turn slowly
   together, so they never cross, and the two dashed lines glide.
   The pieces stay from song to song: each goes to the nearest of the new places, changing size and
   colour on the way, and what a song has more or fewer of fades in or out (wallpaper.css times it all).
   Everything moves slowly and not far: it is a background. */
let wpPal = [[24, .35, .4], [200, .3, .4], [280, .3, .4]], wpSeed = "tunebox";
const RING = [[.12, .16], [.5, .06], [.88, .16], [.95, .5], [.88, .84], [.5, .94], [.12, .84], [.05, .5]];   /* clockwise */
const SVGNS = "http://www.w3.org/2000/svg";
let wpBuilt = null;
function wpParts() {
  if (wpBuilt) return wpBuilt;
  const wp = wpBox, svg = document.createElementNS(SVGNS, "svg");
  svg.innerHTML = `<g class="rings" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width="1"></g>
    <g class="dashes" stroke="#fff" stroke-opacity=".16" stroke-width="1.2" stroke-dasharray="8 8"></g>`;
  wp.append(Object.assign(document.createElement("div"), { className: "lights" }), Object.assign(document.createElement("div"), { className: "discs" }), svg);
  return wpBuilt = { lights: wp.querySelector(".lights"), discs: wp.querySelector(".discs"), svg, rings: svg.querySelector(".rings"), dashes: svg.querySelector(".dashes") };
}

/* Puts the pieces in `box` where `spots` say: each spot takes the nearest piece still there, new pieces
   fade in, the ones left over fade out. make() is a new piece, put(el, spot) moves one. A piece takes as
   long to get there as its way (or its change of size) takes at `speed` pixels a second: never fast. */
const moveTime = (way, speed) => clamp(way / speed, 10, 400).toFixed(1) + "s";
function reconcile(box, spots, make, put, speed) {
  const free = [...box.children].filter(el => !el.classList.contains("gone"));
  const born = [];
  for (const sp of spots) {
    let best = -1, bd = Infinity;
    free.forEach((el, i) => { const d = Math.hypot(el._x - sp.x, el._y - sp.y); if (d < bd) { bd = d; best = i; } });
    let el;
    if (best >= 0) el = free.splice(best, 1)[0];
    else { el = make(); box.append(el); born.push(el); }
    const size = sp.size ?? sp.r * 2, way = el._x == null ? 0 : Math.max(Math.hypot(el._x - sp.x, el._y - sp.y), Math.abs(el._s - size) / 2);
    el.style.setProperty("--move", moveTime(way, speed));
    el._x = sp.x; el._y = sp.y; el._s = size;
    put(el, sp);
  }
  for (const el of free) { el.classList.add("gone"); el.classList.remove("on"); setTimeout(() => el.remove(), 10200); }
  requestAnimationFrame(() => requestAnimationFrame(() => born.forEach(el => el.classList.add("on"))));
}

function paint(pal, seed = "") {
  wpPal = pal; wpSeed = seed;
  const W = innerWidth, H = innerHeight, M = Math.max(W, H), m = Math.min(W, H), R = rng(seed), parts = wpParts(), speed = M * .004;
  /* a new floating piece: its own slow path, kept for good (changing it would make it jump) */
  const floater = cls => () => {
    const el = document.createElement("i"), t = Math.random() * 6.283, dur = 300 + Math.random() * 180;
    el.className = cls;
    el.style.animationDuration = dur + "s";
    el.style.animationDelay = -Math.random() * dur + "s";
    el.style.setProperty("--ft", t);
    el.style.setProperty("--ds", (.94 + Math.random() * .12).toFixed(2));
    return el;
  };
  const putFloat = (el, sp) => {
    const t = +el.style.getPropertyValue("--ft");
    Object.assign(el.style, { left: sp.x - sp.size / 2 + "px", top: sp.y - sp.size / 2 + "px", width: sp.size + "px", height: sp.size + "px" });
    el.style.setProperty("--c", sp.c);
    el.style.setProperty("--dx", (Math.cos(t) * sp.far | 0) + "px");
    el.style.setProperty("--dy", (Math.sin(t) * sp.far | 0) + "px");
  };

  const n = 3 + Math.floor(R() * 3), turn0 = R() * 6.283;
  reconcile(parts.lights, Array.from({ length: n }, (_, i) => {
    const [h, s, l] = pal[i % 3], hue = h + (i >= 3 ? (R() - .5) * 40 : 0), a = turn0 + i * 6.283 / n;
    return { x: W / 2 + Math.cos(a) * W * .42, y: H / 2 + Math.sin(a) * H * .42, size: M * .95 * Math.pow(3 / n, .7),
      far: M * (.04 + R() * .03), c: hslA([hue, clamp(s, .45, .85), clamp(l, .36, .56)]) };
  }), floater("light"), putFloat, speed);

  const muted = ([h, s, l]) => [h, clamp(s * .6, .2, .45), clamp(l, .34, .46) + R() * .05];
  const turn = Math.floor(R() * 8), at = i => { const [u, v] = RING[(turn + i) % 8]; return [(u + (R() - .5) * .1) * W, (v + (R() - .5) * .1) * H]; };
  reconcile(parts.discs, [0, 2, 4, 6].map((p, i) => {
    const [x, y] = at(p), r = (M + m) / 2 * (.11 + R() * .08);
    return { x, y, size: r * 2 / .45, far: M * (.02 + R() * .015), c: hslA(muted(pal[i % 3])) };
  }), floater("disc"), putFloat, speed);

  /* hairline circles that never cross. Each grows to the size it wants, or only as far as the nearest
     circle (just touching it), from outside or, when it starts inside one, within it */
  const circles = [];
  const ringAt = (x, y, want) => {
    let room = want;
    for (const c of circles) {
      const d = Math.hypot(x - c.x, y - c.y);
      room = Math.min(room, d >= c.r ? d - c.r : c.r - d);
    }
    if (room > m * .04) circles.push({ x, y, r: room });
  };
  [1, 3, 5, 7].forEach(p => { const [x, y] = at(p); ringAt(x, y, m * (.18 + R() * .2)); });
  for (let i = 0; i < 3; i++) {                 /* a few more: one inside another, or meeting it */
    const c = circles[Math.floor(R() * circles.length)];
    if (!c) break;
    const t = R() * 6.283, o = c.r * (R() < .5 ? .35 : 1.4);
    ringAt(c.x + Math.cos(t) * o, c.y + Math.sin(t) * o, m * (.1 + R() * .15));
  }
  parts.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  reconcile(parts.rings, circles, () => document.createElementNS(SVGNS, "circle"),
    (el, c) => {
      /* mostly an arc, bowing one way or the other: one direction starts slow, the other ends slow */
      const bend = Math.random(), late = "cubic-bezier(.45, 0, .85, .55)", early = "cubic-bezier(.15, .45, .55, 1)";
      el.style.setProperty("--ex", bend < .2 ? "linear" : bend < .6 ? late : early);
      el.style.setProperty("--ey", bend < .2 ? "linear" : bend < .6 ? early : late);
      Object.assign(el.style, { cx: c.x.toFixed(1) + "px", cy: c.y.toFixed(1) + "px", r: c.r.toFixed(1) + "px" });
    }, speed * .85);                              /* an arc is a longer way than the straight line */

  /* two long dashed lines crossing near the middle: each a line through its own middle, turned */
  const dashes = [64 + R() * 14, -(10 + R() * 12)].map(deg => ({ x: W * (.35 + R() * .3), y: H * (.35 + R() * .3), deg }));
  if (!parts.dashes.children.length) parts.dashes.innerHTML = dashes.map(() => `<g class="dash"><line x1="${-M * 1.5 | 0}" y1="0" x2="${M * 1.5 | 0}" y2="0"/></g>`).join("");
  [...parts.dashes.children].forEach((g, i) => {
    const d = dashes[i], way = g._x == null ? 0 : Math.max(Math.hypot(g._x - d.x, g._y - d.y), Math.abs(g._deg - d.deg) * Math.PI / 180 * m / 2);
    g.style.setProperty("--move", moveTime(way, speed));
    g._x = d.x; g._y = d.y; g._deg = d.deg;
    g.style.transform = `translate(${d.x | 0}px, ${d.y | 0}px) rotate(${d.deg.toFixed(1)}deg)`;
  });
}
/* the grain: random grey specks, one per screen pixel, drawn once and tiled */
function grain(el) {
  const r = Math.min(2, devicePixelRatio || 1), n = Math.round(256 * r), cv = document.createElement("canvas");
  cv.width = cv.height = n;
  const x = cv.getContext("2d"), d = x.createImageData(n, n);
  for (let i = 0; i < d.data.length; i += 4) { const v = Math.random() * 255; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
  x.putImageData(d, 0, 0);
  el.style.backgroundImage = `url(${cv.toDataURL()})`;
}

/* wp: an empty box for the wallpaper, grainEl: one over it for the grain (wallpaper.css styles both) */
let wpBox = null;
export function setupWallpaper(wp, grainEl) {
  wpBox = wp;
  paint(wpPal, wpSeed);
  grain(grainEl);
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => paint(wpPal, wpSeed), 400); });
}
