/* The wallpaper (after Nothing OS 5's) in a song's cover colours: the wall's background, and the now
   playing canvas's. setupWallpaper() once, then wallpaperFor(song) whenever the song changes; it fills
   the window, and draws and moves itself (wallpaper.css only places it).

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
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* The wallpaper for these colours. Three to five big lights behind everything take them bright, the
   fewer the bigger, at even turns round the middle. Four soft discs take them muted, at every other of
   eight places round the edge, so they stay apart and balanced; the hairline circles start from the
   other four. Lights and discs each float on a slow path of their own; the circles turn slowly
   together, so they never cross, and the two dashed lines glide.
   The pieces stay from song to song: each goes to the nearest of the new places, changing size and
   colour on the way, and what a song has more or fewer of fades in or out.
   Everything moves slowly and not far: it is a background.

   It is drawn on two canvases, not built of elements: moving big soft elements about made the browser
   lay out and repaint the whole screen every frame for minutes after each song, which a TV or a tablet
   can't keep up with. The lights and discs go on a small canvas the browser stretches over the screen
   (they are soft, so nothing is lost), the hairlines on one at full size. Both are drawn about 15 times
   a second while something moves, and not at all while nothing does.
   The box's --wp (wallpaper.css) says how: "run", "still" (nothing drifts; a new song's pieces still
   glide to their places) or "hold" (nothing is drawn: the box is shut or being dragged). */
let wpPal = [[24, .35, .4], [200, .3, .4], [280, .3, .4]], wpSeed = "tunebox";
const RING = [[.12, .16], [.5, .06], [.88, .16], [.95, .5], [.88, .84], [.5, .94], [.12, .84], [.05, .5]];   /* clockwise */
const GLOW = 4;                                 /* the lights' canvas is this many times smaller than the screen */
const FPS = 15;

/* ---------- a number that glides to a new value, the way a CSS transition does ---------- */
function bezier(x1, y1, x2, y2) {
  const at = (t, a, b) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
  return x => {
    let lo = 0, hi = 1;
    for (let i = 0; i < 20; i++) { const m = (lo + hi) / 2; if (at(m, x1, x2) < x) lo = m; else hi = m; }
    return at((lo + hi) / 2, y1, y2);
  };
}
const EASE = { linear: x => x, ease: bezier(.25, .1, .25, 1), inOut: bezier(.42, 0, .58, 1),
  late: bezier(.45, 0, .85, .55), early: bezier(.15, .45, .55, 1) };
const clock = () => performance.now() / 1000;
function glide(v) {
  const g = { a: v, b: v, t0: 0, d: 0, e: EASE.linear,
    at: t => t >= g.t0 + g.d ? g.b : g.a + (g.b - g.a) * g.e((t - g.t0) / g.d),
    busy: t => t < g.t0 + g.d,
    to(b, d = 0, e = EASE.linear) { const t = clock(); g.a = g.at(t); g.b = b; g.t0 = t; g.d = d; g.e = e; } };
  return g;
}
/* a back-and-forth (CSS's `alternate`) of `dur` seconds, eased: 0 to 1 and back */
const swing = (t, dur) => { const c = t / dur, f = c - Math.floor(c); return EASE.inOut(Math.floor(c) % 2 ? 1 - f : f); };

const hslRgb = ([h, s, l]) => {
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  return [0, 8, 4].map(n => 255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))));
};

/* ---------- the pieces ---------- */
let wpBox = null, glowCv, lineCv;
const parts = { lights: [], discs: [], rings: [], dashes: [] };

/* Puts the pieces of `list` where `spots` say: each spot takes the nearest piece still there, new pieces
   fade in, the ones left over fade out. make() is a new piece, put(p, spot, move, born) moves one. A piece
   takes as long to get there as its way (or its change of size) takes at `speed` pixels a second: never fast. */
const moveTime = (way, speed) => clamp(way / speed, 10, 400);
function reconcile(list, spots, make, put, speed) {
  const free = list.filter(p => !p.gone);
  for (const sp of spots) {
    let best = -1, bd = Infinity;
    free.forEach((p, i) => { const d = Math.hypot(p.tx - sp.x, p.ty - sp.y); if (d < bd) { bd = d; best = i; } });
    let p, born = best < 0;
    if (!born) p = free.splice(best, 1)[0];
    else { p = make(); list.push(p); }
    const size = sp.size ?? sp.r * 2, way = born ? 0 : Math.max(Math.hypot(p.tx - sp.x, p.ty - sp.y), Math.abs(p.ts - size) / 2);
    p.tx = sp.x; p.ty = sp.y; p.ts = size;
    put(p, sp, moveTime(way, speed), born);
    if (born) p.o.to(1, 10, EASE.ease);
  }
  for (const p of free) { p.gone = true; p.o.to(0, 10, EASE.ease); }
}

/* a light or a disc: its own slow drift, kept for good (changing it would make it jump) */
const floater = () => {
  const dur = 300 + Math.random() * 180;
  return { x: glide(0), y: glide(0), s: glide(0), far: glide(0), c: [0, 1, 2].map(() => glide(0)), o: glide(0),
    ft: Math.random() * 6.283, dur, off: Math.random() * dur, ds: .94 + Math.random() * .12 };
};
const putFloat = (p, sp, move, born) => {
  const d = born ? 0 : move;
  p.x.to(sp.x, d); p.y.to(sp.y, d); p.s.to(sp.size, d); p.far.to(sp.far, d);
  hslRgb(sp.c).forEach((v, i) => p.c[i].to(v, born ? 0 : 10, EASE.ease));
};

function paint(pal, seed = "") {
  wpPal = pal; wpSeed = seed;
  const W = innerWidth, H = innerHeight, M = Math.max(W, H), m = Math.min(W, H), R = rng(seed), speed = M * .004;

  const n = 3 + Math.floor(R() * 3), turn0 = R() * 6.283;
  reconcile(parts.lights, Array.from({ length: n }, (_, i) => {
    const [h, s, l] = pal[i % 3], hue = h + (i >= 3 ? (R() - .5) * 40 : 0), a = turn0 + i * 6.283 / n;
    return { x: W / 2 + Math.cos(a) * W * .42, y: H / 2 + Math.sin(a) * H * .42, size: M * .95 * Math.pow(3 / n, .7),
      far: M * (.04 + R() * .03), c: [(hue + 360) % 360, clamp(s, .45, .85), clamp(l, .36, .56)] };
  }), floater, putFloat, speed);

  const muted = ([h, s, l]) => [h, clamp(s * .6, .2, .45), clamp(l, .34, .46) + R() * .05];
  const turn = Math.floor(R() * 8), at = i => { const [u, v] = RING[(turn + i) % 8]; return [(u + (R() - .5) * .1) * W, (v + (R() - .5) * .1) * H]; };
  reconcile(parts.discs, [0, 2, 4, 6].map((p, i) => {
    const [x, y] = at(p), r = (M + m) / 2 * (.11 + R() * .08);
    return { x, y, size: r * 2 / .45, far: M * (.02 + R() * .015), c: muted(pal[i % 3]) };
  }), floater, putFloat, speed);

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
  reconcile(parts.rings, circles, () => ({ x: glide(0), y: glide(0), r: glide(0), o: glide(0) }),
    (p, c, move, born) => {
      /* mostly an arc, bowing one way or the other: one direction starts slow, the other ends slow */
      const bend = Math.random(), d = born ? 0 : move;
      p.x.to(c.x, d, bend < .2 ? EASE.linear : bend < .6 ? EASE.late : EASE.early);
      p.y.to(c.y, d, bend < .2 ? EASE.linear : bend < .6 ? EASE.early : EASE.late);
      p.r.to(c.r, d);
    }, speed * .85);                              /* an arc is a longer way than the straight line */

  /* two long dashed lines crossing near the middle: each a line through its own middle, turned */
  const dashes = [64 + R() * 14, -(10 + R() * 12)].map(deg => ({ x: W * (.35 + R() * .3), y: H * (.35 + R() * .3), deg }));
  if (!parts.dashes.length) parts.dashes = dashes.map(() => ({ x: glide(0), y: glide(0), deg: glide(0) }));
  parts.dashes.forEach((p, i) => {
    const d = dashes[i], born = p.tx == null;
    const way = born ? 0 : Math.max(Math.hypot(p.tx - d.x, p.ty - d.y), Math.abs(p.tdeg - d.deg) * Math.PI / 180 * m / 2);
    p.tx = d.x; p.ty = d.y; p.tdeg = d.deg;
    const t = born ? 0 : moveTime(way, speed);
    p.x.to(d.x, t); p.y.to(d.y, t); p.deg.to(d.deg, t);
  });
  wake();
}

/* ---------- drawing ---------- */
/* a disc blurred: its colour, fading the way a blur does (a disc of 45% of the size, its edge spread like
   a Gaussian blur of 45% of its radius) */
const SOFT = [1, .989, .971, .943, .903, .849, .781, .698, .605, .507, .408, .315, .232, .164, .110, .070, .043, .024, .013, .007, .003];
let drift = 0, last = 0, dirty = true, timer = 0;

function draw(t) {
  const W = innerWidth, H = innerHeight, M = Math.max(W, H), vmax = M / 100;
  const g = glowCv.getContext("2d"), k = glowCv.width / W;
  g.setTransform(k, 0, 0, k, 0, 0);
  g.globalAlpha = 1; g.fillStyle = "#060606"; g.fillRect(0, 0, W, H);
  const soft = (p, alpha, stops) => {
    const o = p.o.at(t) * alpha;
    if (o <= 0) return;
    const e = swing(drift + p.off, p.dur), far = p.far.at(t) * (2 * e - 1);
    const x = p.x.at(t) + Math.cos(p.ft) * far, y = p.y.at(t) + Math.sin(p.ft) * far, r = p.s.at(t) / 2 * (1 + (p.ds - 1) * e);
    const [cr, cg, cb] = p.c.map(c => Math.round(c.at(t))), grad = g.createRadialGradient(x, y, 0, x, y, r);
    stops.forEach((a, i) => grad.addColorStop(i / (stops.length - 1), `rgb(${cr} ${cg} ${cb} / ${a})`));
    g.globalAlpha = o; g.fillStyle = grad; g.fillRect(x - r, y - r, r * 2, r * 2);
  };
  parts.lights.forEach(p => soft(p, .8, [1, 0]));
  parts.discs.forEach(p => soft(p, .75, SOFT));

  const l = lineCv.getContext("2d"), dpr = lineCv.width / W;
  l.setTransform(dpr, 0, 0, dpr, 0, 0);
  l.clearRect(0, 0, W, H);
  /* the circles turn together round the middle, so they never cross */
  const er = swing(drift, 480);
  l.translate(W / 2, H / 2); l.rotate((-2.5 + 5 * er) * Math.PI / 180); l.translate((-.8 + 1.6 * er) * vmax, (.5 - er) * vmax); l.translate(-W / 2, -H / 2);
  l.lineWidth = 1;
  for (const p of parts.rings) {
    const o = p.o.at(t);
    if (o <= 0) continue;
    l.strokeStyle = `rgb(255 255 255 / ${.12 * o})`;
    l.beginPath(); l.arc(p.x.at(t), p.y.at(t), Math.max(0, p.r.at(t)), 0, 6.2832); l.stroke();
  }
  /* the lines glide their own way */
  const ed = swing(drift, 400);
  l.setTransform(dpr, 0, 0, dpr, 0, 0); l.translate((-1.2 + 2.4 * ed) * vmax, (.6 - 1.2 * ed) * vmax);
  l.strokeStyle = "rgb(255 255 255 / .16)"; l.lineWidth = 1.2; l.setLineDash([8, 8]);
  for (const p of parts.dashes) {
    l.save(); l.translate(p.x.at(t), p.y.at(t)); l.rotate(p.deg.at(t) * Math.PI / 180);
    l.beginPath(); l.moveTo(-M * 1.5, 0); l.lineTo(M * 1.5, 0); l.stroke(); l.restore();
  }
  l.setLineDash([]);
}

const all = () => [...parts.lights, ...parts.discs, ...parts.rings];
const moving = t => all().some(p => p.o.busy(t) || p.x.busy(t) || p.y.busy(t) || (p.s || p.r).busy(t) || p.c?.[0].busy(t))
  || parts.dashes.some(p => p.x.busy(t) || p.deg.busy(t));

function frame() {
  timer = 0;
  const t = clock(), mode = getComputedStyle(wpBox).getPropertyValue("--wp").trim() || "run";
  const dt = Math.min(.5, t - (last || t));
  last = t;
  if (mode === "hold") { dirty = true; return later(500); }
  if (mode === "run") drift += dt;
  /* what faded out is gone for good */
  for (const k of ["lights", "discs", "rings"]) parts[k] = parts[k].filter(p => !p.gone || p.o.busy(t));
  const busy = mode === "run" || moving(t);
  if (busy || dirty) { draw(t); dirty = false; }
  later(busy ? 1000 / FPS : 500);
}
/* the next frame: a timer, then the screen's own next frame (none while the page is hidden) */
function later(ms) { clearTimeout(timer); timer = setTimeout(() => requestAnimationFrame(frame), ms); }
function wake() { dirty = true; if (wpBox) later(0); }

function size() {
  const W = innerWidth, H = innerHeight, dpr = Math.min(2, devicePixelRatio || 1);
  glowCv.width = Math.ceil(W / GLOW); glowCv.height = Math.ceil(H / GLOW);
  lineCv.width = Math.round(W * dpr); lineCv.height = Math.round(H * dpr);
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
export function setupWallpaper(wp, grainEl) {
  wpBox = wp;
  glowCv = document.createElement("canvas"); lineCv = document.createElement("canvas");
  glowCv.className = "glow";
  wp.append(glowCv, lineCv);
  size();
  paint(wpPal, wpSeed);
  grain(grainEl);
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { size(); paint(wpPal, wpSeed); }, 400); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { last = 0; wake(); } });
}
