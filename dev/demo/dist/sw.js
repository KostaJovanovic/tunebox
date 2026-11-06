/* Tunebox demo: the server, inside the browser. This service worker answers every api/ request the
   pages make (fetches, uploads, covers, downloads) the way tunebox/api/ does, so the real web/ files run
   unchanged. Music comes from demo/music.json (recorded from a real server by dev/demo/capture.py);
   nothing plays out loud, the clock just moves through each song. Everything else (the queue, people,
   playlists, stats, the admin) lives in this browser and is kept in the Cache API between visits.
   It is a port of tunebox/: when a route there changes shape, change it here too. */
const STORE = "tunebox-demo", KEY = "demo/state-v1";
const MIN = 60, DAY = 86400, STATS_DAYS = 30, HISTORY_MAX = 300, UNDO_KEEP = 15, PLAYED_KEEP = 50;
const LIKED = "liked", TOP = "top", TOP_SIZE = 30, ADMIN_IDLE = 15 * MIN, MB = 1 << 20, GB = 1 << 30;
const FEATURES = { lyrics: "lyrics", wall: "the wall screen", stats: "stats", recap: "the recap", alarm: "the alarm",
  sleep: "the sleep timer", playlists: "playlists", likes: "likes", groups: "groups", people: "names", radio: "the radio",
  browse: "Home and Explore", eq: "the equaliser", links: "pasting links", local: "local songs",
  look: "choosing a theme and accent", namelist: "the names in Settings" };
const PRESETS = { home: [], office: ["recap", "alarm", "sleep", "eq"], party: ["people", "groups", "stats", "recap", "alarm", "sleep", "local"],
  solo: ["people", "groups", "recap", "wall"] };
const ACCENTS = ["", "red", "orange", "yellow", "green", "blue", "magenta"];
const HOUSE = { signups: "open", name: "TUNEBOX DEMO", accent: "", tz: "", network: "",
  features: Object.fromEntries(Object.keys(FEATURES).map(k => [k, true])),
  groups: { one: "Seminar", many: "Seminars", required: true, create: "open" }, newPerson: { groups: [] },
  wall: { lyrics: true, queue: false, who: false, clock: true, controls: true, night: "", qr: true },
  local: { capGB: null, reserveGB: 2, maxMB: 200 }, quiet: { hours: "", max: 30 }, welcome: true };
const SEMINARS = { ele: { id: "ele", name: "Ele", color: "#1F5FBF" }, fiz: { id: "fiz", name: "Fiz", color: "#E63B2E" },
  teh: { id: "teh", name: "Teh", color: "#1E8F5A" } };
const SEMINAR_COLORS = ["#6A4BC4", "#EE6A1F", "#C8327A", "#F2C230", "#0E8C8C", "#8A5A2B", "#5C5953"];
const EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const EQ_PRESETS = { flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], bass: [6, 5, 4, 2, 0, 0, 0, 0, 0, 0], treble: [0, 0, 0, 0, 0, 1, 2, 4, 5, 6],
  vocal: [-2, -2, -1, 1, 3, 4, 3, 1, 0, -1], rock: [4, 3, 2, 0, -1, -1, 1, 3, 4, 4], pop: [-1, 1, 3, 4, 3, 0, -1, -1, 0, 1],
  electronic: [5, 4, 1, 0, -2, 1, 0, 1, 4, 5], jazz: [3, 2, 1, 2, -1, -1, 0, 1, 2, 3], classical: [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
  loudness: [6, 4, 0, 0, -2, 0, -1, -2, 3, 4], night: [-3, -2, -1, 0, 1, 2, 2, 1, -1, -2] };
const QUALITIES = ["best", "balanced", "low"];
const TRACK_KEYS = ["videoId", "title", "artist", "album", "duration", "thumb", "artistId", "albumId"];
const HOURS = /^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$/;
const YTDLP = "2026.8.19";

/* ---------- plumbing ---------- */
class HTTP extends Error { constructor(status, detail) { super(detail); this.status = status; this.detail = detail; } }
const fail = (status, detail) => { throw new HTTP(status, detail); };
const now = () => Date.now() / 1000;
const int = x => Math.floor(x);
const hex = n => [...crypto.getRandomValues(new Uint8Array(n))].map(b => b.toString(16).padStart(2, "0")).join("");
const squeeze = s => String(s ?? "").split(/\s+/).filter(Boolean).join(" ");
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const jsonRes = (o, status = 200, headers = {}) => new Response(JSON.stringify(o), {
  status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers } });
const download = (body, type, name) => new Response(body, { headers: { "Content-Type": type, "Content-Disposition": `attachment; filename="${name}"` } });
const secs = d => { let n = 0; for (const p of String(d || "").split(":")) { if (!/^\d+$/.test(p)) return 0; n = n * 60 + +p; } return n; };
const clock = s => { s = Math.round(s || 0); return s >= 3600 ? `${int(s / 3600)}:${String(int(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
  : s ? `${int(s / 60)}:${String(s % 60).padStart(2, "0")}` : ""; };
const today = () => new Date().toISOString().slice(0, 10);

let M = null, S = null, booting = null, dirty = false;
const T = new Map(), ALBUMS = new Map(), ARTISTS = new Map(), PLAYLISTS = new Map(), SEARCH = new Map(), PAGES = new Map();
const blobs = () => caches.open(STORE);

function ready() {
  return booting ||= (async () => {
    M = await (await fetch(new URL("demo/music.json", self.registration.scope), { cache: "no-cache" })).json();
    indexMusic();
    const saved = await (await blobs()).match(KEY);
    S = saved ? await saved.json() : seedHouse();
    if (!saved) dirty = true;
  })().catch(e => { booting = null; throw e; });
}
const save = async () => { dirty = false; await (await blobs()).put(KEY, jsonRes(S)); };

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url), scope = self.registration.scope;
  if (!url.href.startsWith(scope)) return;
  const path = url.pathname.slice(new URL(scope).pathname.length);
  if (path.startsWith("api/")) e.respondWith(handle(e, path, url.searchParams));
});

/* ---------- the music: every song, album, artist and playlist the recording knows ---------- */
function indexMusic() {
  const walk = x => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (!x || typeof x !== "object") return;
    if (typeof x.videoId === "string" && /^[\w-]{11}$/.test(x.videoId) && x.title) {
      const t = pick(x), had = T.get(t.videoId);
      if (!had || (!had.duration && t.duration)) T.set(t.videoId, t);
    } else if (x.type === "album" && x.id) ALBUMS.has(x.id) || ALBUMS.set(x.id, x);
    else if (x.type === "artist" && x.id) ARTISTS.has(x.id) || ARTISTS.set(x.id, x);
    else if (x.type === "playlist" && x.id) PLAYLISTS.has(x.id) || PLAYLISTS.set(x.id, x);
    Object.values(x).forEach(walk);
  };
  for (const [k, v] of Object.entries(M.pages)) {
    const [path, qs] = k.split("?"), q = new URLSearchParams(qs || "");
    if (path === "api/search") SEARCH.set(`${q.get("kind")}|${q.get("q").toLowerCase()}`, v);
    else if (path === "api/mood") PAGES.set("mood|" + q.get("params"), v);
    else PAGES.set(path.split("/").map(decodeURIComponent).join("/"), v);
    const m = path.match(/^api\/(album|artist|playlist)\/(.+)$/);
    if (m && v.title) ({ album: ALBUMS, artist: ARTISTS, playlist: PLAYLISTS })[m[1]].set(decodeURIComponent(m[2]),
      { type: m[1], id: decodeURIComponent(m[2]), title: v.title, subtitle: v.subtitle, thumb: v.thumb });
    walk(v);
  }
  Object.values(M.radio).forEach(walk);
}
const pick = t => Object.fromEntries(TRACK_KEYS.map(k => [k, String(t[k] ?? "").slice(0, 300)]));

/* ---------- the state: a fresh house, and the demo's house with a year of listening ---------- */
const mergedHouse = saved => {
  const out = structuredClone(HOUSE);
  for (const [k, v] of Object.entries(saved && typeof saved === "object" ? saved : {})) {
    if (out[k] && typeof out[k] === "object" && v && typeof v === "object") for (const kk in v) { if (kk in out[k]) out[k][kk] = v[kk]; }
    else if (k in out && typeof out[k] !== "object") out[k] = v;
  }
  return out;
};
const settingsDefault = () => ({ volume: 70, volume_scale: "db", eq: { preset: "flat", custom: Array(10).fill(0) }, normalize: false,
  autoplay: true, quality: "best", turns: true, alarm: { enabled: false, time: "07:00", days: [0, 1, 2, 3, 4], list: null, level: 45, ramp: 5, last: "" } });
const liked = () => ({ id: LIKED, name: "Liked songs", tracks: [], created: int(now()), updated: int(now()) });

function fresh(keep = {}) {
  return { v: 1, house: mergedHouse({}), settings: settingsDefault(), people: {}, seminars: structuredClone(SEMINARS),
    playlists: { [LIKED]: liked() }, history: [], plays: [], open: null, blocks: { songs: {}, artists: {}, radio: {} }, wall: [],
    audit: keep.audit || [], local: {}, keys: {}, admin: keep.admin || { hash: null, seen: 0, fails: 0, lockedUntil: 0 },
    rev: { house: Date.now(), lists: Date.now(), people: Date.now() },
    player: { queue: [], index: -1, at: 0, pos: 0, paused: false, idle: true, resume: 0, error: "", seed: null, undo: [], sleep: null, ramp: null } };
}

function seedHouse() {
  S = fresh();
  let r = 20261106;                                   // a fixed seed: every visitor's house starts the same
  const rnd = () => (r = (r * 1664525 + 1013904223) >>> 0) / 2 ** 32;
  const any = a => a[int(rnd() * a.length)];
  Object.assign(S.house, { name: "TUNEBOX DEMO", welcome: false, network: "TUNEBOX DEMO",
    groups: { one: "Floor", many: "Floors", required: true, create: "open" } });
  S.seminars = { upstairs: { id: "upstairs", name: "Upstairs", color: "#1F5FBF" }, downstairs: { id: "downstairs", name: "Downstairs", color: "#E63B2E" },
    attic: { id: "attic", name: "Attic", color: "#1E8F5A" } };
  const who = [["mila", "Mila", "#E63B2E", "🎧", "upstairs"], ["jonas", "Jonas", "#1F5FBF", "🎸", "downstairs"], ["ana", "Ana", "#1E8F5A", "🎹", "upstairs"],
    ["theo", "Theo", "#F2C230", "🥁", "attic"], ["sara", "Sara", "#6A4BC4", "🎤", "downstairs"], ["luka", "Luka", "#EE6A1F", "💿", "attic"]];
  for (const [id, name, color, emoji, sem] of who) S.people[id] = { id, name, color, emoji, seminars: [sem] };
  const ids = who.map(w => w[0]);
  const pool = {};
  for (const a of M.artists) {
    const ts = (SEARCH.get(`songs|${a.toLowerCase()}`) || []).filter(t => t.duration).slice(0, 14).map(pick);
    if (ts.length) pool[a] = ts;
  }
  const artists = Object.keys(pool), all = Object.values(pool).flat();
  const fav = Object.fromEntries(ids.map((id, i) => [id, [0, 1, 2, 3].map(k => artists[(i * 4 + k) % artists.length])]));
  const songFor = pid => pick(any(pool[pid && rnd() < 0.75 ? any(fav[pid]) : any(artists)]));

  // a year of plays: busier lately and at weekends, mostly in the evening
  const HOUR_W = [2, 1, 1, 0, 0, 0, 1, 3, 5, 4, 3, 3, 4, 3, 3, 3, 4, 6, 9, 10, 10, 8, 6, 4];
  const hourOf = () => { let x = rnd() * HOUR_W.reduce((a, b) => a + b); for (let h = 0; h < 24; h++) if ((x -= HOUR_W[h]) < 0) return h; return 20; };
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  for (let d = 370; d >= 0; d--) {
    const day = new Date(midnight); day.setDate(day.getDate() - d);
    const weekend = [0, 6].includes(day.getDay());
    const n = (d > 45 ? 3 + int(rnd() * 8) : 8 + int(rnd() * 14)) + (weekend ? 5 : 0);
    const times = Array.from({ length: n }, () => day / 1000 + hourOf() * 3600 + int(rnd() * 3600)).filter(t => t < now() - 900).sort((a, b) => a - b);
    for (const t of times) {
      const user = rnd() < 0.72, by = user ? any(ids) : "", tr = user ? songFor(by) : pick(any(all)), d0 = secs(tr.duration);
      const p = { t: int(t), v: tr.videoId, ti: tr.title, ar: tr.artist, al: tr.album, th: tr.thumb, ai: tr.artistId, d: d0, s: d0,
        by, sem: by ? [...S.people[by].seminars] : [], src: user ? "user" : "auto", a: user ? int(t - rnd() * 900) : 0 };
      const x = rnd();
      if (x < 0.1) Object.assign(p, { x: "skip", xb: rnd() < 0.5 && by ? by : any(ids), s: 5 + int(rnd() * 60) });
      else if (x < 0.13) Object.assign(p, { x: "cut", xb: any(ids), s: 20 + int(rnd() * 90) });
      S.plays.push(p);
    }
  }
  S.history = S.plays.slice(-HISTORY_MAX).reverse().map(p => ({ ...trackFor(p.v, p), by: p.by, src: p.src, at: p.a || p.t, playedAt: p.t }));
  S.wall = Array.from({ length: 24 }, () => int(now() - rnd() * 60 * DAY)).sort();

  // likes and playlists
  const seen = new Set();
  for (let i = 0; i < 26; i++) {
    const by = any(ids), t = songFor(by);
    if (seen.has(t.videoId)) continue;
    seen.add(t.videoId);
    S.playlists[LIKED].tracks.push({ ...t, likedBy: rnd() < 0.3 ? [by, any(ids.filter(x => x !== by))] : [by] });
  }
  const lists = [["Sunday morning", "ana", ["Nina Simone", "Air", "Khruangbin", "Bonobo", "Miles Davis", "Fleetwood Mac"]],
    ["Dinner party", "jonas", ["Amy Winehouse", "Stevie Wonder", "Fela Kuti", "Khruangbin", "Daft Punk"]],
    ["Deep focus", "sara", ["Bonobo", "Massive Attack", "Portishead", "Air", "Radiohead"]],
    ["Friday night", "mila", ["Dua Lipa", "Daft Punk", "Beyonce", "Bad Bunny", "Rosalia", "Kendrick Lamar"]],
    ["House classics", "", artists]];
  lists.forEach(([name, owner, from], i) => {
    const src = from.filter(a => pool[a]), id = hex(4), ts = [], have = new Set();
    for (let k = 0; k < 40 && ts.length < 16; k++) { const t = pick(any(pool[any(src)])); if (!have.has(t.videoId)) { have.add(t.videoId); ts.push(t); } }
    S.playlists[id] = { id, name, tracks: ts, created: int(now() - (40 - i) * DAY), updated: int(now() - i * 3 * DAY), owner };
  });

  // what plays now: Mila's song, a minute in, then four more people's, then the radio (gentle ones: it's the first thing anyone sees)
  for (const [by, a] of [["mila", "Fleetwood Mac"], ["jonas", "Khruangbin"], ["ana", "Nina Simone"], ["theo", "Daft Punk"], ["sara", "Air"]])
    add([pick(any(pool[a] || all))], by, "add");
  S.player.at = Date.now() - 70 * 1000;
  S.open.t -= 70;
  return S;
}

/* ---------- the house, people, the admin ---------- */
const on = name => S.house.features[name] !== false;
const label = name => name === "groups" ? S.house.groups.many.toLowerCase() : FEATURES[name];
const tzName = () => S.house.tz || "";
const fmts = new Map();
function zparts(ts) {
  const tz = tzName();
  if (!fmts.has(tz)) fmts.set(tz, new Intl.DateTimeFormat("en-GB", { hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", weekday: "short", ...(tz ? { timeZone: tz } : {}) }));
  const p = Object.fromEntries(fmts.get(tz).formatToParts(new Date(ts * 1000)).map(x => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, month: `${p.year}-${p.month}`, year: +p.year, mon: +p.month, day: +p.day,
    hour: +p.hour % 24, hm: `${p.hour}:${p.minute}`, weekday: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(p.weekday) };
}
function within(hours, ts) {
  const m = HOURS.exec(hours || "");
  if (!m) return false;
  const z = zparts(ts), [hh, mm] = z.hm.split(":").map(Number), n = hh * 60 + mm, a = +m[1] * 60 + +m[2], b = +m[3] * 60 + +m[4];
  return a <= b ? a <= n && n < b : n >= a || n < b;
}
const quietCap = () => within(S.house.quiet.hours, now()) ? +S.house.quiet.max : null;
const housePublic = () => ({ name: S.house.name, accent: S.house.accent, tz: tzName(), signups: S.house.signups, network: S.house.network,
  off: Object.keys(FEATURES).filter(k => !on(k)), groups: S.house.groups, newPerson: S.house.newPerson, wall: S.house.wall,
  local: { maxMB: S.house.local.maxMB }, quiet: S.house.quiet, rev: S.rev.house });
const saveHouse = () => { S.rev.house++; };
const savePeople = () => { S.rev.people++; };
const saveLists = () => { S.rev.lists++; };

function isAdmin(touch = true) {
  const a = S.admin;
  if (!a.seen) return false;
  if (now() - a.seen > ADMIN_IDLE) { a.seen = 0; return false; }
  if (touch) a.seen = now();
  return true;
}
const needAdmin = () => isAdmin() || fail(403, "admin");
const needFeature = (...names) => names.some(on) || isAdmin() || fail(403, `The admin switched off ${label(names[0])}`);
const keyFor = p => `${p.phrase.salt}:${p.kv || 0}`;
const holdsKey = pid => { const p = S.people[pid]; return !p || !p.phrase || S.keys[pid] === keyFor(p); };
const giveKey = pid => { const p = S.people[pid]; if (p.phrase) S.keys[pid] = keyFor(p); };
const whoOf = req => {
  if (!on("people") && !isAdmin(false)) return "";
  const pid = req.headers.get("x-demo-who") || "";
  return S.people[pid] && holdsKey(pid) ? pid : "";
};
const needWho = c => c.who || !on("people") ? c.who : fail(401, "pick");
const personPublic = p => {
  const { phrase, kv, ...out } = p;
  out.locked = !!phrase;
  if (out.locked) out.mine = holdsKey(p.id);
  return out;
};
async function sha(text) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))].map(b => b.toString(16).padStart(2, "0")).join("");
}
const cleanPhrase = s => { s = squeeze(s); if (s.length < 4) fail(400, "A pass phrase needs at least 4 characters"); return s.slice(0, 200); };
const hashPhrase = async (phrase, salt = hex(16)) => ({ salt, hash: await sha(salt + phrase) });
async function matches(phrase, stored) {
  if (!stored) return true;
  if (phrase && (await hashPhrase(squeeze(phrase).slice(0, 200), stored.salt)).hash === stored.hash) return true;
  await new Promise(r => setTimeout(r, 600));
  return false;
}
function audit(ev, msg, c) {
  S.audit.push({ t: int(now()), ev, msg: msg.slice(0, 200), ip: "192.168.1.23", ua: c?.req.headers.get("user-agent")?.slice(0, 120) || "" });
  S.audit.splice(0, S.audit.length - 300);
}

/* ---------- songs ---------- */
const isLocal = v => String(v || "").startsWith("local:");
const localTrack = s => ({ videoId: "local:" + s.id, title: s.title, artist: s.artist, album: s.album, duration: clock(s.secs),
  thumb: s.cv ? `api/local/${s.id}/cover?v=${s.cv}` : "", artistId: "", albumId: "" });
function cleanTrack(t) {
  if (t && typeof t === "object" && isLocal(t.videoId)) { const s = S.local[t.videoId.slice(6)]; return s ? localTrack(s) : null; }
  if (!t || typeof t !== "object" || !/^[\w-]{11}$/.test(String(t.videoId || ""))) return null;
  return pick(t);
}
const trackFor = (v, p) => (isLocal(v) && S.local[v.slice(6)] ? localTrack(S.local[v.slice(6)]) : T.get(v))
  || { videoId: v, title: p.ti, artist: p.ar, album: p.al, duration: clock(p.d), thumb: p.th, artistId: p.ai || "", albumId: "" };
const trackOfPlay = p => ({ videoId: p.v, title: p.ti, artist: p.ar, album: p.al, thumb: p.th, artistId: p.ai || "" });
const artistsOf = t => String(t.artist || "").split(",").map(a => a.trim().toLowerCase()).filter(Boolean);
function blocked(t) {
  const b = S.blocks;
  if (b.songs[t.videoId]) return true;
  const ids = new Set(Object.values(b.artists).map(a => a.id).filter(Boolean));
  return (t.artistId && ids.has(t.artistId)) || artistsOf(t).some(a => b.artists[a]);
}
const forRadio = t => !S.blocks.radio[t.videoId] && !blocked(t);

/* YouTube Music's radio for a song, as recorded; for any other song, more by its artist and then the rest */
function radioFor(vid, limit = 30) {
  let items = M.radio[vid];
  if (!items) {
    const base = isLocal(vid) ? null : T.get(vid);
    const mine = base ? [...T.values()].filter(t => t.artistId && t.artistId === base.artistId) : [];
    const rest = isLocal(vid) ? Object.values(S.local).map(localTrack) : [...T.values()].filter(t => t.duration);
    items = [...shuffle(mine).slice(0, 8), ...shuffle(rest).slice(0, limit)];
  }
  return items.filter(t => t.videoId !== vid && forRadio(t)).slice(0, limit).map(pick);
}
const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = int(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

function mostPlayed(n) {
  const cut = now() - STATS_DAYS * DAY, c = new Map();
  for (const p of allPlays()) if (p.t > cut) { const x = c.get(p.v) || { n: 0, last: 0, p }; x.n++; x.last = Math.max(x.last, p.t); x.p = p; c.set(p.v, x); }
  return [...c.values()].sort((a, b) => b.n - a.n || b.last - a.last).slice(0, n).map(x => [x.n, trackFor(x.p.v, x.p)]);
}
const allPlays = () => S.open ? [...S.plays, { ...S.open, s: Math.round(Math.max(0, position() - S.open.p0)) }] : S.plays;
const counted = p => p.s >= 30 || (p.d && p.s >= p.d / 2);

/* ---------- the player (tunebox/player.py): the clock moves through each song, nothing sounds ---------- */
const P = () => S.player;
const cur = () => P().queue[P().index] || null;
const dur = t => secs(t?.duration) || 200;
function position() {
  const p = P(), c = cur();
  if (!c) return 0;
  if (p.idle) return p.resume || 0;
  return p.paused ? p.pos : clamp((Date.now() - p.at) / 1000, 0, dur(c));
}
function beginPlay(t, when, from) {
  const by = t.by || "";
  S.open = { t: int(when), v: t.videoId, ti: t.title || "", ar: t.artist || "", al: t.album || "", th: t.thumb || "", ai: t.artistId || "",
    d: secs(t.duration), s: 0, by, sem: [...(S.people[by]?.seminars || [])], src: t.src || "user", a: int(t.at || 0), p0: from };
}
function finishPlay(at) {
  const o = S.open;
  if (!o) return;
  S.open = null;
  o.s = Math.round(Math.max(0, at - o.p0));
  delete o.p0;
  if (o.s >= 1) S.plays.push(o);
}
function addHistory(t, when) {
  const h = S.history;
  if (!t || (h[0] && h[0].videoId === t.videoId)) return;
  h.unshift({ ...t, playedAt: int(when) });
  h.splice(HISTORY_MAX);
}
function startAt(i, from, whenMs) {
  const p = P();
  p.index = i; p.idle = false; p.paused = false; p.at = whenMs - from * 1000; p.resume = 0; p.error = "";
  trimPlayed();
  const c = cur();
  addHistory(c, whenMs / 1000);
  beginPlay(c, whenMs / 1000, from);
  refill();
}
function playIndex(i, from = 0) {
  const p = P();
  if (i < 0 || i >= p.queue.length) return;
  finishPlay(position());
  startAt(i, from, Date.now());
}
function trimPlayed() {
  const p = P(), drop = p.index - PLAYED_KEEP;
  if (drop > 0) { p.queue.splice(0, drop); p.index -= drop; }
}
function pause() { const p = P(); if (cur() && !p.idle && !p.paused) { p.pos = position(); p.paused = true; } }
function unpause() { const p = P(); if (cur() && !p.idle && p.paused) { p.at = Date.now() - p.pos * 1000; p.paused = false; } }
function seek(v) {
  const p = P(), c = cur();
  if (!c || p.idle) return;
  v = clamp(v, 0, dur(c) - 0.5);
  if (p.paused) p.pos = v; else p.at = Date.now() - v * 1000;
}
function stop() {
  const p = P();
  finishPlay(position());
  Object.assign(p, { queue: [], index: -1, idle: true, paused: false, resume: 0 });
}
function cutShort(how, by) {
  const p = P(), c = cur();
  if (!c || p.idle) return;
  if (dur(c) - position() > 10 && S.open && S.open.v === c.videoId && !S.open.x) Object.assign(S.open, { x: how, xb: by });
}

/* Time passed since the last request: songs that ended hand over to the next, the sleep timer runs out,
   the alarm rings. Returns whether anything changed. */
function tick() {
  const p = P();
  let changed = false;
  const cap = quietCap();
  if (cap !== null && S.settings.volume > cap && !p.ramp) { S.settings.volume = cap; changed = true; }
  changed = alarmCheck() || changed;
  for (let guard = 0; guard < 400; guard++) {
    const c = cur();
    if (!c || p.paused || p.idle) break;
    const end = p.at + dur(c) * 1000, sl = p.sleep && !p.sleep.mode ? p.sleep.until * 1000 : 0;
    if (sl && sl <= Date.now() && sl < end) { p.pos = (sl - p.at) / 1000; p.paused = true; p.sleep = null; changed = true; break; }
    if (end > Date.now()) break;
    changed = true;
    if (Date.now() - end > 3 * 3600 * 1000) { finishPlay(dur(c)); p.paused = true; p.pos = 0; beginPlay(c, now(), 0); break; }   // nobody came back for hours: it waits
    finishPlay(dur(c));
    if (p.sleep?.mode === "track") { p.sleep = null; if (p.index + 1 < p.queue.length) p.index++; p.idle = true; p.resume = 0; break; }
    if (p.index + 1 < p.queue.length) startAt(p.index + 1, 0, end);
    else { p.idle = true; p.resume = 0; }
  }
  if (p.sleep && !p.sleep.mode && p.sleep.until <= now()) { p.sleep = null; changed = true; }
  if (p.ramp && now() > p.ramp[0] + p.ramp[1]) { p.ramp = null; changed = true; }
  return changed;
}
function alarmCheck() {
  const a = S.settings.alarm, z = zparts(now()), stamp = `${z.date} ${a.time}`;
  if (!(a.enabled && on("alarm") && a.days.includes(z.weekday) && z.hm === a.time && a.last !== stamp)) return false;
  a.last = stamp;
  fireAlarm();
  return true;
}
function fireAlarm(rampS) {
  const a = S.settings.alarm, p = P();
  p.sleep = null;
  S.settings.volume = a.level || S.settings.volume;
  p.ramp = [now(), rampS || Math.max(0.2, +a.ramp || 0) * 60];
  const tracks = S.playlists[a.list || ""]?.tracks;
  if (tracks?.length) replace(tracks, 0, "", "Alarm");
  else if (cur() && p.idle) playIndex(p.index, p.resume);
  else if (cur()) unpause();
  else if (S.history.length) replace([{ ...S.history[0] }], 0, "", "Alarm");
}
function sleepLeft() {
  const s = P().sleep;
  if (!s) return null;
  if (s.mode === "track") return Math.max(0, dur(cur()) - position());
  return Math.max(0, s.until - now());
}
function playerState() {
  const p = P(), c = cur(), off = Math.max(p.index, 0), left = sleepLeft();
  const idle = p.idle || !c;
  return { current: c, index: p.index, queue: p.queue.slice(off, off + 60), offset: off,
    paused: idle || !!p.paused, position: idle ? p.resume || 0 : position(), duration: idle ? 0 : dur(c), volume: S.settings.volume,
    loading: false, error: p.error, idle,
    sleep: left === null ? null : { mode: p.sleep.mode || "timer", left: Math.round(left), minutes: p.sleep.minutes ?? null },
    alarm: !!S.settings.alarm.enabled, ramping: !!p.ramp, listsRev: S.rev.lists, peopleRev: S.rev.people,
    userCount: c ? userEnd() - off - 1 : 0, seed: p.seed, turns: S.settings.turns,
    undo: p.undo.length ? { n: p.undo.length, label: p.undo.at(-1).label } : null };
}

/* the two-part queue: now playing, the songs people added (src "user"), the radio (src "auto") */
function userEnd() { const p = P(); let i = p.index + 1; while (i < p.queue.length && p.queue[i].src === "user") i++; return i; }
function turnSlot(by) {
  const p = P(), start = p.index + 1, end = userEnd();
  if (!S.settings.turns) return end;
  const k = p.queue.slice(start, end).filter(t => t.by === by).length, rounds = {};
  for (let j = start; j < end; j++) { const b = p.queue[j].by || ""; rounds[b] = (rounds[b] || 0) + 1; if (rounds[b] > k + 1) return j; }
  return end;
}
const finished = () => !cur() || (P().idle && !P().resume && P().index + 1 >= P().queue.length);
function add(tracks, by, mode = "add", label = "") {
  const p = P(), items = tracks.filter(t => !blocked(t)).map(t => ({ ...t, by, src: "user", at: int(now()) }));
  if (!items.length) return 0;
  snapshot(label || (items.length === 1 ? `Added "${items[0].title}"` : `Added ${items.length} songs`), by);
  const startNow = mode === "now" || finished();
  if (mode === "now") cutShort("cut", by);
  if (!cur()) { p.queue = []; p.index = -1; }
  let pos = 0;
  if (mode === "next" || mode === "now" || startNow) { p.queue.splice(p.index + 1, 0, ...items); pos = startNow ? 0 : 1; }
  else for (const it of items) { const j = turnSlot(by); p.queue.splice(j, 0, it); pos ||= j - p.index; }
  if (startNow) playIndex(p.index + 1);
  follow([], !p.queue.slice(userEnd()).length);
  return pos;
}
function replace(tracks, start = 0, by = "", label = "") {
  const p = P(), items = tracks.filter(t => t && !blocked(t)).map(t => ({ ...t, by, src: "user", at: int(now()) }));
  if (!items.length) return;
  snapshot(label || `Played "${items[0].title}"`, by);
  cutShort("cut", by);
  const keep = cur() ? p.queue.slice(0, p.index + 1) : [];
  finishPlay(position());
  p.queue = [...keep, ...items];
  reseed(items.at(-1));
  startAt(keep.length + clamp(start, 0, items.length - 1), 0, Date.now());
}
function follow(gone = [], force = false) {
  const p = P(), end = userEnd();
  let last = end > 0 ? p.queue[end - 1] : null;
  if (!last || last.src !== "user") last = p.seed && gone.some(t => t.videoId === p.seed.videoId) ? cur() : null;
  if (last && (force || !p.seed || last.videoId !== p.seed.videoId)) reseed(last);
}
function reseed(t, fill = true) {
  P().seed = Object.fromEntries(["videoId", "title", "artist", "thumb"].map(k => [k, String(t[k] || "")]));
  if (fill && S.settings.autoplay && on("radio")) fillRadio();
}
function fillRadio(fresh = false) {
  const p = P();
  let items = radioFor(p.seed.videoId, fresh ? 50 : 30);
  const end = userEnd(), known = new Set(p.queue.slice(0, end).map(t => t.videoId));
  if (fresh) { p.queue.slice(end).forEach(t => known.add(t.videoId)); items = shuffle(items); }
  const nu = pickRadio(items, known, p.queue.slice(0, end)).map(t => ({ ...t, by: "", src: "auto" }));
  if (nu.length) p.queue.splice(end, p.queue.length - end, ...nu.slice(0, 30));
}
function refill(force = false) {
  const p = P();
  if (!(S.settings.autoplay || force) || !cur() || p.queue.length - p.index > 3 || !on("radio")) return;
  for (const seed of [p.seed, cur()]) {
    if (!seed) continue;
    const known = new Set(p.queue.map(t => t.videoId));
    const nu = pickRadio(radioFor(seed.videoId), known, p.queue).map(t => ({ ...t, by: "", src: "auto" }));
    if (nu.length) { p.queue.push(...nu); return; }
  }
}
function pickRadio(items, known, before) {
  const recent = new Set(S.history.slice(0, 100).map(t => t.videoId)), GAP = 4;
  const artist = t => (t.artist || "").split(",")[0].trim().toLowerCase();
  let last = before.slice(-GAP).map(artist);
  const out = [], held = [];
  for (const t of items) {
    if (known.has(t.videoId)) continue;
    known.add(t.videoId);
    if (recent.has(t.videoId) || (artist(t) && last.includes(artist(t)))) { held.push(t); continue; }
    out.push(t); last = [...last, artist(t)].slice(-GAP);
  }
  for (const t of held.filter(t => !recent.has(t.videoId))) {
    if (!(artist(t) && last.includes(artist(t)))) { held.splice(held.indexOf(t), 1); out.push(t); last = [...last, artist(t)].slice(-GAP); }
  }
  if (out.length < 5) out.push(...held.slice(0, 5 - out.length));
  return out;
}
function snapshot(label, by = "") {
  const p = P(), c = Math.max(p.index, 0);
  p.undo.push({ id: hex(3), label: label.slice(0, 90), by, at: int(now()), queue: cur() ? p.queue.slice(c, c + 200).map(t => ({ ...t })) : [],
    position: Math.round(position() * 10) / 10, seed: p.seed });
  p.undo.splice(0, p.undo.length - UNDO_KEEP);
}
function restore(snap) {
  const p = P(), q = snap.queue.map(t => ({ ...t })), c = cur();
  p.seed = snap.seed;
  if (q.length && c && c.videoId === q[0].videoId) p.queue.splice(p.index + 1, p.queue.length, ...q.slice(1));
  else if (!q.length) stop();
  else {
    const keep = c ? p.queue.slice(0, p.index + 1) : [];
    p.queue = [...keep, ...q];
    playIndex(keep.length, snap.position || 0);
  }
  const k = p.index + 1;
  p.queue.splice(k, p.queue.length, ...p.queue.slice(k).filter(t => !blocked(t)));
}
function dropBlocked(label) {
  const p = P(), k = p.index + 1, gone = p.queue.slice(k).filter(blocked);
  if (gone.length) { snapshot(label); p.queue.splice(k, p.queue.length, ...p.queue.slice(k).filter(t => !blocked(t))); follow(gone); }
  return gone.length;
}

/* ---------- routes ---------- */
const routes = [];
const route = (method, pattern, fn, ...deps) => routes.push({ method, fn, deps,
  re: new RegExp("^" + pattern.replace(/\{(\w+)(:path)?\}/g, (_, n, all) => `(?<${n}>${all ? ".+" : "[^/]+"})`) + "$") });
const ADMIN = "admin";

async function handle(e, path, q) {
  const req = e.request;
  try {
    await ready();
    if (tick()) dirty = true;
    for (const r of routes) {
      const m = r.method === req.method && r.re.exec(path);
      if (!m) continue;
      const params = Object.fromEntries(Object.entries(m.groups || {}).map(([k, v]) => [k, decodeURIComponent(v)]));
      for (const d of r.deps) d === ADMIN ? needAdmin() : needFeature(...d.split("|"));
      let body = {};
      if (!["GET", "HEAD"].includes(req.method) && (req.headers.get("content-type") || "").startsWith("application/json")) {
        try { body = await req.json() ?? {}; } catch { fail(422, "request: invalid JSON"); }
      }
      const c = { req, q, params, body, who: whoOf(req), path };
      const out = await r.fn(c);
      if (req.method !== "GET") dirty = true;
      return out instanceof Response ? out : jsonRes(out);
    }
    return jsonRes({ detail: "Not Found" }, 404);
  } catch (err) {
    if (err instanceof HTTP) return jsonRes({ detail: err.detail }, err.status);
    console.error(err);
    return jsonRes({ detail: `The demo tripped: ${err.message}` }, 500);
  } finally {
    if (dirty && S) e.waitUntil(save());
  }
}
const num = (v, d = 0) => (v === null || v === undefined || v === "" || isNaN(+v)) ? d : +v;

/* queue.py */
const here = new Map();
route("GET", "api/state", c => {
  const ua = c.req.headers.get("user-agent") || "";
  here.set(ua, { ip: "192.168.1.23", device: deviceOf(ua), who: c.who, wall: (c.req.referrer || "").includes("/wall"), at: now() });
  return { ...playerState(), admin: isAdmin(false), houseRev: S.rev.house, ytdlp: null };
});
function mayAdd(by, n, replacing = false) {
  const p = S.people[by] || {}, pl = P();
  if (p.noAdd) fail(403, "You can't add songs right now");
  if (p.cap) {
    const waiting = replacing ? 0 : pl.queue.slice(pl.index + 1, userEnd()).filter(t => t.by === by).length;
    if (waiting + n - replacing > p.cap) fail(403, `You can have ${plural(p.cap, "song")} waiting`
      + (waiting ? `, and ${waiting} of yours ${waiting === 1 ? "is" : "are"} already` : ""));
  }
}
const nth = n => `${n}${n % 100 >= 10 && n % 100 <= 20 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
const leftOut = n => n ? ` · ${plural(n, "blocked song")} left out` : "";
const localAllowed = tracks => tracks.some(t => isLocal(t.videoId)) && needFeature("local");
route("POST", "api/play", c => {
  const b = c.body;
  if (b.wall) { needFeature("wall"); if (!S.house.wall.controls && !isAdmin(false)) fail(403, "The wall only shows here"); }
  const by = b.wall ? "" : needWho(c);
  let tracks = (b.tracks || []).map(cleanTrack).filter(Boolean);
  if (!tracks.length) fail(400, "no tracks");
  localAllowed(tracks);
  const first = tracks[clamp(b.start || 0, 0, tracks.length - 1)], allowed = tracks.filter(t => !blocked(t));
  if (!allowed.length) fail(403, tracks.length === 1 ? "That song is blocked here" : "Those songs are blocked here");
  const start = Math.max(0, allowed.indexOf(first)), skipped = tracks.length - allowed.length;
  tracks = allowed;
  const mode = b.mode || "replace";
  mayAdd(by, tracks.length, mode === "replace");
  const lbl = String(b.label || "").trim().slice(0, 60);
  if (["add", "next", "now"].includes(mode)) {
    const pos = add(tracks, by, mode, lbl ? `Added "${lbl}"` : "");
    if (b.wall) S.wall.push(...Array(tracks.length).fill(int(now())));
    const msg = pos === 0 ? "Playing now" : pos === 1 || mode === "next" ? "Plays next" : `Added · ${nth(pos)} in queue`;
    return { ok: true, position: pos, message: msg + leftOut(skipped) };
  }
  if (mode !== "replace") fail(400, "unknown mode");
  replace(tracks, start, by, lbl ? `Played "${lbl}"` : "");
  return { ok: true, message: (lbl ? `Playing "${lbl}"` : "Playing") + leftOut(skipped) };
});
route("POST", "api/queue", c => {
  const by = needWho(c), t = cleanTrack(c.body.track) || fail(400, "not a track");
  localAllowed([t]);
  if (blocked(t)) fail(403, "That song is blocked here");
  mayAdd(by, 1);
  return { ok: true, position: add([t], by, c.body.next ? "next" : "add") };
});
route("GET", "api/radio/skips", () => Object.entries(S.blocks.radio).sort((a, b) => (b[1].at || 0) - (a[1].at || 0)).map(([k, v]) => ({ videoId: k, ...v })));
route("POST", "api/radio/skips", c => {
  const t = cleanTrack(c.body.track) || fail(400, "not a track"), p = P(), end = userEnd();
  S.blocks.radio[t.videoId] = { title: t.title, artist: t.artist, at: int(now()), by: c.who };
  const gone = p.queue.slice(end).filter(x => x.videoId === t.videoId);
  if (gone.length) p.queue.splice(end, p.queue.length, ...p.queue.slice(end).filter(x => x.videoId !== t.videoId));
  return { ok: true, message: `The radio won't pick "${t.title}" again` + (gone.length ? " · taken out of up next" : "") };
});
route("DELETE", "api/radio/skips/{vid}", c => {
  if (!S.blocks.radio[c.params.vid]) fail(404, "The radio already plays that one");
  delete S.blocks.radio[c.params.vid];
  return { ok: true, message: "Back on the radio" };
});
route("GET", "api/queue/history", () => [...P().undo].reverse().map(s => ({ id: s.id, label: s.label, by: s.by, at: s.at, count: s.queue.length,
  current: s.queue[0]?.title || "", thumb: s.queue[0]?.thumb || "" })));
const queueAt = (i, vid) => (i >= 0 && i < P().queue.length && (vid == null || P().queue[i].videoId === vid)) ? i : fail(409, "The queue changed, try again");
route("POST", "api/control", c => {
  const { action: a, videoId } = c.body, v = c.body.value, by = c.who, p = P();
  let msg = "";
  if (a === "toggle") { if (p.idle && cur()) playIndex(p.index, p.resume); else if (p.paused) unpause(); else pause(); }
  else if (a === "next") { if (p.index + 1 < p.queue.length) { cutShort("skip", by); playIndex(p.index + 1); } }
  else if (a === "prev") { if (position() > 5 || p.index === 0) seek(0); else playIndex(p.index - 1); }
  else if (a === "seek" && v != null) seek(+v);
  else if (a === "volume" && v != null) {
    let vol = Math.round(clamp(+v, 0, 100));
    const cap = quietCap();
    if (cap !== null && vol > cap && !isAdmin()) { vol = cap; msg = `Quiet hours: the volume goes up to ${cap}`; }
    S.settings.volume = vol;
    p.ramp = null;
  } else if (a === "jump" && v != null) {
    const i = queueAt(int(v), videoId);
    if (i !== p.index) cutShort(i > p.index ? "skip" : "cut", by);
    playIndex(i);
  } else if (a === "remove" && v != null) {
    const i = queueAt(int(v), videoId);
    if (p.index < i) { snapshot(`Removed "${p.queue[i].title}"`, by); follow(p.queue.splice(i, 1)); msg = "Removed"; }
  } else if ((a === "move" || a === "promote") && v != null) {
    const i = queueAt(int(v), videoId);
    if (i <= p.index) fail(400, "Only songs that are up next can be moved");
    const t = p.queue[i];
    snapshot(`Moved "${t.title}"`, by);
    p.queue.splice(i, 1);
    const to = a === "promote" ? p.index + 1 : clamp(int(c.body.to ?? i), p.index + 1, p.queue.length);
    if (to <= userEnd()) { if (t.src !== "user") Object.assign(t, { src: "user", by, at: int(now()) }); } else t.src = "auto";
    p.queue.splice(to, 0, t);
    if (t.src === "user") follow();
    msg = a === "promote" ? "Plays next" : "";
  } else if (a === "shuffle") {
    const end = userEnd(), rest = p.queue.slice(p.index + 1, end);
    if (rest.length > 1) { snapshot("Shuffled up next", by); p.queue.splice(p.index + 1, rest.length, ...shuffle(rest)); follow(); msg = "Shuffled"; }
  } else if (a === "clear") {
    const end = userEnd();
    if (end > p.index + 1) { snapshot("Cleared up next", by); follow(p.queue.splice(p.index + 1, end - p.index - 1)); msg = "Cleared"; }
  } else if (a === "clear_mine") {
    const end = userEnd(), mid = p.queue.slice(p.index + 1, end), gone = mid.filter(t => by && t.by === by);
    if (gone.length) {
      snapshot("Took their songs out", by);
      p.queue.splice(p.index + 1, mid.length, ...mid.filter(t => t.by !== by));
      follow(gone); msg = `Took out ${plural(gone.length, "song")}`;
    }
  } else if (a === "clear_auto") {
    const end = userEnd();
    if (end < p.queue.length) { snapshot("Cleared the radio", by); p.queue.splice(end); p.seed = null; msg = "Radio cleared"; }
  } else if (a === "refresh") {
    needFeature("radio");
    const seed = p.seed || cur();
    if (seed) { snapshot("New radio songs", by); reseed(seed, false); fillRadio(true); msg = "New radio songs"; }
  } else if (a === "stop") { if (cur()) snapshot("Stopped", by); stop(); }
  else if (a === "undo") {
    if (!p.undo.length) fail(400, "Nothing to undo");
    const snap = p.undo.pop();
    restore(snap); msg = `Undone: ${snap.label}`;
  } else if (a === "restore") {
    const snap = p.undo.find(s => s.id === c.body.id) || fail(404, "That queue is gone");
    snapshot("Before restoring an earlier queue", by); restore(snap); msg = "Restored";
  } else fail(400, "unknown action");
  return { ok: true, message: msg };
});

/* browse.py: the recorded answers, and a search over everything recorded for what wasn't */
const words = q => q.toLowerCase().split(/\s+/).filter(Boolean);
const hits = (items, q, text) => { const w = words(q); return items.filter(x => { const s = text(x).toLowerCase(); return w.every(k => s.includes(k)); }); };
route("GET", "api/search", c => {
  const q = c.q.get("q") || "", kind = ["songs", "albums", "artists", "playlists"].includes(c.q.get("kind")) ? c.q.get("kind") : "songs";
  if (!q.trim()) return [];
  const mine = kind === "songs" && (on("local") || isAdmin(false))
    ? hits(Object.values(S.local), q, s => `${s.title} ${s.artist} ${s.album}`).slice(0, 20).map(s => ({ type: "song", ...localTrack(s) })) : [];
  let res = SEARCH.get(`${kind}|${q.trim().toLowerCase()}`);
  if (!res) {
    const pool = { songs: [...T.values()].map(t => ({ type: "song", ...t })), albums: [...ALBUMS.values()], artists: [...ARTISTS.values()], playlists: [...PLAYLISTS.values()] }[kind];
    res = hits(pool, q, x => `${x.title} ${x.artist || ""} ${x.album || ""} ${x.subtitle || ""}`).slice(0, 30);
  }
  return [...mine, ...res];
});
route("GET", "api/home", () => PAGES.get("api/home") || [], "browse");
route("GET", "api/explore", () => PAGES.get("api/explore") || { releases: [], moods: [] }, "browse");
route("GET", "api/mood", c => PAGES.get("mood|" + c.q.get("params")) || shuffle([...PLAYLISTS.values()]).slice(0, 18), "browse");
route("GET", "api/album/{id}", c => {
  const a = PAGES.get(`api/album/${c.params.id}`);
  if (a) return a;
  const ts = [...T.values()].filter(t => t.albumId === c.params.id), card = ALBUMS.get(c.params.id);
  if (!ts.length) fail(404, "Couldn't find that album on YouTube Music");
  return { title: card?.title || ts[0].album, subtitle: ts[0].artist, artistId: ts[0].artistId, thumb: card?.thumb || ts[0].thumb, tracks: ts };
});
route("GET", "api/artist/{id}", c => {
  const a = PAGES.get(`api/artist/${c.params.id}`);
  if (a) return a;
  const ts = [...T.values()].filter(t => t.artistId === c.params.id);
  if (!ts.length) fail(404, "Couldn't find that artist on YouTube Music");
  const albums = [...new Set(ts.map(t => t.albumId).filter(Boolean))].map(id => ALBUMS.get(id)).filter(Boolean);
  return { title: ARTISTS.get(c.params.id)?.title || ts[0].artist.split(",")[0], subtitle: "Artist", thumb: ARTISTS.get(c.params.id)?.thumb || ts[0].thumb, tracks: ts.slice(0, 20), albums };
});
route("GET", "api/playlist/{id}", c => {
  const id = c.params.id.replace(/^VL/, ""), p = PAGES.get(`api/playlist/${c.params.id}`) || PAGES.get(`api/playlist/${id}`);
  if (p) return p;
  if (id.startsWith("RD") && !id.startsWith("RDCLAK")) {
    const vid = id.replace(/^RD(AMVM)?/, ""), tracks = [T.get(vid), ...radioFor(vid, 40)].filter(Boolean);
    return { title: "Mix", subtitle: "YouTube Music mix", thumb: tracks[0]?.thumb || "", tracks };
  }
  fail(404, "Couldn't find that playlist on YouTube Music");
});
route("GET", "api/where/{vid}", c => {
  const t = isLocal(c.params.vid) ? null : T.get(c.params.vid);
  if (!t && !isLocal(c.params.vid)) fail(404, "Couldn't find that song on YouTube Music");
  return { artistId: t?.artistId || "", albumId: t?.albumId || "" };
});
route("GET", "api/resolve", c => {
  const raw = (c.q.get("url") || "").trim();
  let u;
  try { u = new URL(raw.includes("://") ? raw : "https://" + raw); } catch { fail(400, "That isn't a link"); }
  const host = u.hostname.toLowerCase();
  if (!["youtu.be", "youtube.com"].includes(host) && !host.endsWith(".youtube.com")) fail(400, "Only YouTube and YouTube Music links work here");
  const parts = u.pathname.split("/").filter(Boolean), lst = u.searchParams.get("list");
  let vid = u.searchParams.get("v");
  if (host === "youtu.be" && parts.length) vid = parts[0];
  else if (parts.length > 1 && ["shorts", "live", "embed"].includes(parts[0])) vid = parts[1];
  let kind = null, ident = null;
  if (parts.length > 1 && ["browse", "channel"].includes(parts[0])) { ident = parts[1]; kind = ident.startsWith("MPRE") ? "album" : ident.startsWith("UC") ? "artist" : "playlist"; }
  else if (lst && (!vid || parts[0] === "playlist")) [kind, ident] = ["playlist", lst];
  else if (lst && (!lst.startsWith("RD") || lst.startsWith("RDCLAK"))) [kind, ident] = ["playlist", lst];
  else if (vid) [kind, ident] = ["song", vid];
  if (!kind || !/^[\w-]{2,80}$/.test(ident || "")) fail(400, "That link doesn't point to a song, album, playlist or artist");
  if (kind !== "song") return { type: kind, id: ident };
  const t = T.get(ident) || fail(404, "Couldn't find that song");
  return { type: "song", track: t };
}, "links");
route("GET", "api/forme", () => {
  const most = mostPlayed(24).map(([, t]) => t);
  const likes = shuffle(S.playlists[LIKED].tracks.map(t => ({ ...pick(t), likedBy: t.likedBy || [] })));
  const shelves = [];
  if (most.length) shelves.push({ key: "most", title: "Most played", subtitle: `The house, last ${STATS_DAYS} days`, items: most });
  if (on("stats") || isAdmin(false)) { const day = onThisDay(); if (day) { day.items = day.items.filter(t => !blocked(t)); shelves.push(day); } }
  if (likes.length && (on("likes") || isAdmin(false))) shelves.push({ key: "likedmix", title: "Liked mix", subtitle: "Everyone's likes, shuffled", items: likes.slice(0, 30) });
  const seeds = (most.length ? most : likes).slice(0, 5).map(t => t.videoId), seed = seeds.length ? seeds[int(Math.random() * seeds.length)] : null;
  const recent = S.history.slice(0, 15).filter(h => h.videoId && h.videoId !== seed && !isLocal(h.videoId)), pk = recent.length ? recent[int(Math.random() * recent.length)] : null;
  const mix = seed ? radioFor(seed, 40) : [];
  if (mix.length) shelves.push({ key: "housemix", title: "House mix", subtitle: "New songs like the ones you play", items: mix.slice(0, 30) });
  const known = new Set([...most, ...mix.slice(0, 30)].map(t => t.videoId));
  const recs = pk ? radioFor(pk.videoId, 40).filter(t => !known.has(t.videoId)) : [];
  if (recs.length >= 5) shelves.push({ key: "recs", title: "Recommended", subtitle: `Because you played ${pk.title}`, items: recs.slice(0, 30) });
  return shelves;
}, "browse");

/* lyrics.py: recorded for the house's songs, asked of LRCLIB for any other */
const lyricsCache = new Map();
route("GET", "api/lyrics", async c => {
  const vid = c.q.get("videoId") || "";
  if (M.lyrics[vid]) return M.lyrics[vid];
  if (!lyricsCache.has(vid)) lyricsCache.set(vid, await lrclib(c.q.get("title") || "", c.q.get("artist") || "", c.q.get("album") || "", secs(c.q.get("duration"))));
  return lyricsCache.get(vid);
}, "lyrics");
async function lrclib(title, artist, album, d) {
  const get = async (path, params) => {
    const r = await fetch(`https://lrclib.net/api/${path}?` + new URLSearchParams(Object.entries(params).filter(([, v]) => v)));
    return r.ok ? r.json() : null;
  };
  const a1 = artist.split(",")[0].trim();
  let hit = null;
  try {
    hit = await get("get", { track_name: title, artist_name: a1, album_name: album, duration: d || "" });
    if (!hit || !(hit.syncedLyrics || hit.plainLyrics)) {
      const found = ((await get("search", { track_name: title.replace(/\s*[([][^)\]]*(remaster|version|live|edit|mix|feat\.?|ft\.)[^)\]]*[)\]]/gi, ""), artist_name: a1 })) || [])
        .filter(f => f.syncedLyrics || f.plainLyrics).sort((x, y) => (!x.syncedLyrics - !y.syncedLyrics) || (d ? Math.abs((x.duration || 0) - d) - Math.abs((y.duration || 0) - d) : 0));
      hit = found[0] && (!d || Math.abs((found[0].duration || 0) - d) < 15) ? found[0] : null;
    }
  } catch { hit = null; }
  if (hit?.instrumental) return { instrumental: true, source: "LRCLIB" };
  if (!hit) return { none: true };
  const synced = (hit.syncedLyrics || "").split("\n").map(l => /^\[(\d+):(\d+(?:\.\d+)?)\](.*)/.exec(l.trim())).filter(Boolean)
    .map(m => [Math.round((+m[1] * 60 + +m[2]) * 100) / 100, m[3].trim()]);
  return { synced: synced.length ? synced : null, plain: hit.plainLyrics || "", source: "LRCLIB" };
}

/* lists.py */
const listSummary = p => ({ id: p.id, name: p.name, count: p.tracks.length, updated: p.updated, thumbs: p.tracks.slice(0, 4).map(t => t.thumb),
  liked: p.id === LIKED, owner: p.owner || "", auto: !!p.auto });
const sortedLists = () => Object.values(S.playlists).sort((a, b) => (a.id !== LIKED) - (b.id !== LIKED) || b.updated - a.updated);
const topList = () => ({ id: TOP, name: `Top ${TOP_SIZE}`, tracks: mostPlayed(TOP_SIZE * 2).filter(([, t]) => !blocked(t)).slice(0, TOP_SIZE).map(([n, t]) => ({ ...t, plays: n })),
  created: int(now()), updated: int(now()), owner: "", auto: true, days: STATS_DAYS });
const mayManage = (p, c) => (!!p.owner && p.owner === c.who) || isAdmin();
function getList(id) {
  needFeature(id === LIKED ? "likes" : "playlists");
  if (id === TOP) fail(400, `Top ${TOP_SIZE} makes itself from what plays here`);
  return S.playlists[id] || fail(404, "No such playlist");
}
route("GET", "api/history", c => S.history.slice(0, clamp(num(c.q.get("limit"), 100), 1, HISTORY_MAX)));
route("DELETE", "api/history", c => { S.history = []; audit("history", "Cleared the history", c); return { ok: true }; }, ADMIN);
route("GET", "api/lists", () => {
  const adm = isAdmin(false), ls = sortedLists().filter(p => adm || on(p.id === LIKED ? "likes" : "playlists")), top = topList();
  if (top.tracks.length && (adm || on("playlists"))) ls.splice(ls[0]?.id === LIKED ? 1 : 0, 0, top);
  return ls.map(listSummary);
});
route("POST", "api/lists", c => {
  const name = String(c.body.name || "").trim().slice(0, 80) || "New playlist", p = P();
  const src = c.body.fromQueue ? p.queue.slice(Math.max(p.index, 0)) : c.body.tracks || [], id = hex(4);
  S.playlists[id] = { id, name, tracks: src.map(cleanTrack).filter(Boolean), created: int(now()), updated: int(now()), owner: c.who };
  saveLists();
  return S.playlists[id];
}, "playlists");
route("GET", "api/lists/{id}", c => { if (c.params.id === TOP) { needFeature("playlists"); return topList(); } return getList(c.params.id); });
route("PATCH", "api/lists/{id}", c => {
  const p = getList(c.params.id), name = String(c.body.name || "").trim().slice(0, 80);
  if (name && name !== p.name && p.id !== LIKED) { if (!mayManage(p, c)) fail(403, "Only its owner or the admin can rename it"); p.name = name; }
  if (Array.isArray(c.body.tracks)) {
    const likedBy = Object.fromEntries(p.tracks.filter(t => t.likedBy).map(t => [t.videoId, t.likedBy]));
    p.tracks = c.body.tracks.map(cleanTrack).filter(Boolean).map(t => likedBy[t.videoId] ? { ...t, likedBy: likedBy[t.videoId] } : t);
  }
  p.updated = int(now()); saveLists();
  return p;
});
route("PATCH", "api/lists/{id}/tracks", c => {
  const p = getList(c.params.id), ts = p.tracks, b = c.body;
  let i = b.at;
  if (i == null || !(i >= 0 && i < ts.length) || ts[i].videoId !== b.videoId) i = ts.findIndex(t => t.videoId === b.videoId);
  if (i < 0) fail(404, "That song is no longer in the playlist");
  if (b.op === "remove") ts.splice(i, 1);
  else if (b.op === "move" && b.to != null) ts.splice(clamp(b.to, 0, ts.length - 1), 0, ts.splice(i, 1)[0]);
  else fail(400, "unknown op");
  p.updated = int(now()); saveLists();
  return p;
});
route("POST", "api/lists/{id}/tracks", c => {
  const t = cleanTrack(c.body.track) || fail(400, "not a track"), p = getList(c.params.id), dup = p.tracks.some(x => x.videoId === t.videoId);
  if (!dup) { p.tracks.splice(p.id === LIKED ? 0 : p.tracks.length, 0, t); p.updated = int(now()); saveLists(); }
  return { ok: true, duplicate: dup, count: p.tracks.length };
});
route("POST", "api/like", c => {
  const t = cleanTrack(c.body.track) || fail(400, "not a track"), by = c.who, p = S.playlists[LIKED], have = p.tracks.find(x => x.videoId === t.videoId);
  if (c.body.liked && !have) p.tracks.unshift({ ...t, likedBy: by ? [by] : [] });
  else if (c.body.liked && by && !(have.likedBy ||= []).includes(by)) have.likedBy.push(by);
  else if (!c.body.liked && have) p.tracks = p.tracks.filter(x => x.videoId !== t.videoId);
  else return { liked: !!c.body.liked, count: p.tracks.length };
  p.updated = int(now()); saveLists();
  return { liked: !!c.body.liked, count: p.tracks.length };
}, "likes");
route("DELETE", "api/lists/{id}", c => {
  if (c.params.id === LIKED) fail(400, "Liked songs can't be deleted");
  if (!mayManage(getList(c.params.id), c)) fail(403, "Only its owner or the admin can delete it");
  delete S.playlists[c.params.id];
  if (S.settings.alarm.list === c.params.id) S.settings.alarm.list = null;
  saveLists();
  return { ok: true };
});

/* people.py */
function personFields(p, b, mayCreate) {
  if (b.name != null) {
    const name = squeeze(b.name).slice(0, 24);
    if (!name) fail(400, "Type a name");
    if (Object.values(S.people).some(q => q.name.toLowerCase() === name.toLowerCase() && q.id !== p.id)) fail(409, "That name is taken");
    p.name = name;
  }
  if (b.color != null) { if (!/^#[0-9a-fA-F]{6}$/.test(b.color)) fail(400, "bad colour"); p.color = b.color.toUpperCase(); }
  if (b.emoji != null) { const e = String(b.emoji).trim().slice(0, 8); if ([...e].some(ch => ch.charCodeAt(0) < 128 && !"#*0123456789".includes(ch))) fail(400, "Pick an emoji"); p.emoji = e; }
  if (b.seminars != null) p.seminars = pickSeminars(b.seminars, mayCreate);
}
const findSeminar = name => { const low = name.trim().toLowerCase(); return S.seminars[low] ? low : Object.keys(S.seminars).find(k => S.seminars[k].name.toLowerCase() === low) ?? null; };
function addSeminar(name) {
  name = squeeze(name).slice(0, 24);
  const base = name.toLowerCase().replace(/[^\w]+/g, "-").replace(/^-+|-+$/g, "") || "group";
  let sid = base, n = 1;
  while (S.seminars[sid]) sid = `${base}-${++n}`;
  S.seminars[sid] = { id: sid, name, color: SEMINAR_COLORS[Object.keys(S.seminars).length % SEMINAR_COLORS.length] };
  savePeople();
  return S.seminars[sid];
}
function pickSeminars(names, mayCreate) {
  const g = S.house.groups, out = [];
  for (let n of names.slice(0, 12)) {
    n = squeeze(n).slice(0, 24);
    if (!n) continue;
    let sid = findSeminar(n);
    if (sid === null) { if (!mayCreate) fail(400, `Pick a ${g.one.toLowerCase()} from the list`); sid = addSeminar(n).id; }
    if (!out.includes(sid)) out.push(sid);
  }
  if (!out.length && g.required && on("groups")) fail(400, `Pick your ${g.one.toLowerCase()}`);
  return out;
}
const mayCreate = () => S.house.groups.create === "open" || isAdmin(false);
async function setPhrase(p, phrase) {
  if (phrase == null) return;
  if (phrase) p.phrase = await hashPhrase(cleanPhrase(phrase)); else delete p.phrase;
}
async function newPerson(b, create) {
  const p = { id: hex(4), name: "", color: "#1F5FBF", emoji: "", seminars: [] };
  const start = S.house.newPerson.groups.filter(s => S.seminars[s]);
  personFields(p, { name: b.name || "", color: b.color, emoji: b.emoji, seminars: b.seminars?.length ? b.seminars : start }, create);
  await setPhrase(p, b.phrase || null);
  S.people[p.id] = p;
  return p;
}
route("GET", "api/people", () => Object.values(S.people).map(personPublic).sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())));
route("GET", "api/seminars", () => Object.values(S.seminars).sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())));
route("POST", "api/people", async c => {
  needFeature("people");
  if (S.house.signups !== "open" && !isAdmin()) fail(403, "New names are added by the admin here");
  const p = await newPerson(c.body, mayCreate());
  savePeople(); giveKey(p.id);
  return { ...personPublic(p), mine: true };
});
route("PATCH", "api/people/{pid}", async c => {
  const p = S.people[c.params.pid] || fail(404, "No such person");
  if (!holdsKey(p.id)) fail(403, "Only they can change it: that name has a pass phrase");
  personFields(p, c.body, mayCreate());
  await setPhrase(p, c.body.phrase);
  savePeople(); giveKey(p.id);
  return { ...personPublic(p), mine: true };
});
route("POST", "api/people/{pid}/unlock", async c => {
  const p = S.people[c.params.pid] || fail(404, "No such person");
  if (!await matches(c.body.phrase, p.phrase)) fail(403, "Wrong pass phrase");
  giveKey(p.id);
  return { ok: true };
});

/* settings.py */
const eqBands = () => S.settings.eq.preset === "custom" ? S.settings.eq.custom : EQ_PRESETS[S.settings.eq.preset] || EQ_PRESETS.flat;
const getSettings = () => ({ volume: S.settings.volume, eq: S.settings.eq, bands: eqBands(), freqs: EQ_FREQS, presets: EQ_PRESETS,
  account: { signedIn: false }, normalize: S.settings.normalize, autoplay: S.settings.autoplay, turns: S.settings.turns,
  quality: S.settings.quality, qualities: QUALITIES, alarm: { ...S.settings.alarm, tz: tzName() }, lists: sortedLists().map(listSummary) });
route("GET", "api/network", () => ({ ip: self.location.hostname, host: "tunebox", wifi: S.house.network || null }));
route("GET", "api/settings", getSettings);
route("POST", "api/options", c => {
  const b = c.body;
  if (b.quality != null && !QUALITIES.includes(b.quality)) fail(400, "unknown quality");
  for (const k of ["autoplay", "turns", "normalize", "quality"]) if (b[k] != null) S.settings[k] = b[k];
  if (b.autoplay) refill();
  return getSettings();
});
route("POST", "api/sleep", c => {
  const p = P(), m = num(c.body.minutes);
  if (c.body.track) p.sleep = { mode: "track" };
  else if (m > 0) p.sleep = { until: now() + Math.min(m, 1440) * 60, minutes: Math.min(m, 1440) };
  else p.sleep = null;
  return playerState().sleep || {};
}, "sleep");
route("POST", "api/alarm", c => {
  const b = c.body, a = S.settings.alarm;
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(b.time || "")) fail(400, "time must be HH:MM");
  Object.assign(a, { enabled: !!b.enabled, time: b.time, days: [...new Set((b.days || []).filter(d => d >= 0 && d <= 6))].sort(),
    list: S.playlists[b.list] ? b.list : null, level: clamp(num(b.level, 45), 1, 100), ramp: clamp(num(b.ramp, 5), 0, 30) });
  if (b.test) fireAlarm(10);
  return getSettings();
}, "alarm");
route("POST", "api/eq", c => {
  const b = c.body;
  if (b.preset !== "custom" && !EQ_PRESETS[b.preset]) fail(400, "unknown preset");
  if (b.custom != null) {
    if (b.custom.length !== EQ_FREQS.length) fail(400, "need 10 bands");
    S.settings.eq.custom = b.custom.map(g => Math.round(clamp(+g, -12, 12) * 10) / 10);
  }
  S.settings.eq.preset = b.preset;
  return getSettings();
}, "eq");
route("POST", "api/account", () => fail(400, "Signing in to YouTube Music isn't part of the demo"), ADMIN);
route("DELETE", "api/account", () => ({ signedIn: false }), ADMIN);

/* stats.py */
function summary(ps, earlier) {
  const songs = new Map(), artists = new Map(), songMin = new Map(), artistMin = new Map(), artistThumb = {}, artistId = {}, first = {};
  const hours = Array(24).fill(0), weekdays = Array(7).fill(0), days = new Map(), months = new Map();
  const bump = (m, k, n) => m.set(k, (m.get(k) || 0) + n);
  for (const p of ps) {
    const m = p.s / 60, z = zparts(p.t);
    bump(songs, p.v, 1); bump(songMin, p.v, m); first[p.v] ||= p;
    const a = (p.ar || "").split(",").map(x => x.trim()).filter(Boolean)[0];
    if (a) { bump(artists, a, 1); bump(artistMin, a, m); artistThumb[a] ||= p.th; if (p.ai) artistId[a] ||= p.ai; }
    hours[z.hour] += m; weekdays[z.weekday] += m; bump(days, z.date, m); bump(months, z.month, m);
  }
  let streak = 0, best = 0, prev = null;
  for (const d of [...days.keys()].sort()) {
    const day = Date.parse(d);
    streak = prev !== null && Math.round((day - prev) / 864e5) === 1 ? streak + 1 : 1;
    best = Math.max(best, streak); prev = day;
  }
  const busiest = [...days].sort((a, b) => b[1] - a[1])[0];
  const top = m => [...m].sort((a, b) => b[1] - a[1]).slice(0, 10);
  return { plays: ps.length, minutes: Math.round(ps.reduce((s, p) => s + p.s, 0) / 60), songs: songs.size, artists: artists.size, days: days.size,
    newSongs: [...songs.keys()].filter(v => !earlier.has(v)).length,
    radioShare: ps.length ? Math.round(100 * ps.filter(p => p.src === "auto").length / ps.length) : 0, streak: best,
    busiestDay: busiest ? { date: busiest[0], minutes: Math.round(busiest[1]) } : null,
    topSongs: top(songs).map(([v, n]) => ({ ...trackOfPlay(first[v]), plays: n, minutes: Math.round(songMin.get(v)) })),
    topArtists: top(artists).map(([a, n]) => ({ name: a, plays: n, minutes: Math.round(artistMin.get(a)), thumb: artistThumb[a], id: artistId[a] || "" })),
    hours: hours.map(Math.round), weekdays: weekdays.map(Math.round),
    months: [...months].sort((a, b) => a[0] < b[0] ? -1 : 1).map(([month, m]) => ({ month, minutes: Math.round(m) })) };
}
const AWARDS = [["added", "The DJ", "added the most songs", "song"], ["again", "On repeat", "added the same song the most times", "time"],
  ["skips", "Itchy finger", "skipped the most songs", "skip"], ["cuts", "Can't wait", "cut the most songs short with Play now", "time"],
  ["skipped", "Tough crowd", "had the most songs skipped by others", "skip"], ["night", "Night owl", "had the most minutes after midnight", "minute"],
  ["artists", "Explorer", "added the most different artists", "artist"]];
function fun(ps, shown) {
  const adds = {}, again = {}, arts = {}, rows = {}, first = {};
  const row = id => rows[id] ||= { skipped: 0, night: 0, skips: 0, cuts: 0, ownSkips: 0 };
  let skips = 0, cuts = 0;
  for (const p of ps) {
    const by = p.by, x = p.x, xb = p.xb || "";
    if (by && p.src === "user") {
      const key = `${p.v}|${p.a || p.t}`;
      adds[by] ||= new Set(); again[by] ||= {};
      if (!adds[by].has(key)) { adds[by].add(key); again[by][p.v] = (again[by][p.v] || 0) + 1; first[p.v] ||= p; }
      if (x === "skip" && xb !== by) row(by).skipped++;
      if (counted(p)) {
        if (zparts(p.t).hour < 5) row(by).night += p.s / 60;
        const a = (p.ar || "").split(",")[0].trim();
        if (a) (arts[by] ||= new Set()).add(a);
      }
    }
    if (x && (shown(xb) || (!xb && shown(null)))) { skips += x === "skip"; cuts += x === "cut"; }
    if (x && xb) { row(xb)[x === "skip" ? "skips" : "cuts"]++; if (x === "skip" && xb === by) row(xb).ownSkips++; }
  }
  const people = [];
  for (const pid of new Set([...Object.keys(rows), ...Object.keys(adds)])) {
    if (!S.people[pid] || !shown(pid)) continue;
    const r = row(pid), [v, n] = Object.entries(again[pid] || {}).sort((a, b) => b[1] - a[1])[0] || ["", 0];
    people.push({ id: pid, added: adds[pid]?.size || 0, skips: r.skips, ownSkips: r.ownSkips, cuts: r.cuts, skipped: r.skipped, night: Math.round(r.night),
      artists: arts[pid]?.size || 0, again: n > 1 ? n : 0, againTrack: n > 1 ? trackOfPlay(first[v]) : null });
  }
  people.sort((a, b) => b.added - a.added || S.people[a.id].name.toLowerCase().localeCompare(S.people[b.id].name.toLowerCase()));
  const awards = [];
  for (const [key, title, what, unit] of AWARDS) {
    const best = Math.max(0, ...people.map(r => r[key]));
    if (!best) continue;
    const won = people.filter(r => r[key] === best), same = key === "again" && new Set(won.map(r => r.againTrack.videoId)).size === 1;
    awards.push({ key, title, what, unit, n: best, ids: won.map(r => r.id), track: same ? won[0].againTrack : null });
  }
  return { skips, cuts, people, awards };
}
const mine = who => p => !who || (who.startsWith("sem:") ? (p.sem || []).includes(who.slice(4)) : p.by === who);
const STATS = "stats|recap";
route("GET", "api/stats", c => {
  const who = c.q.get("who") || "", since = num(c.q.get("since")), until = num(c.q.get("until")) || now() + 1;
  if (who.startsWith("sem:")) needFeature("groups");
  else if (who) { needFeature("people"); if (!S.people[who]) fail(404, "No such person"); }
  const raw = allPlays().filter(p => p.t < until), every = raw.filter(counted), m = mine(who);
  const ps = every.filter(p => p.t >= since && m(p)), earlier = new Set(every.filter(p => p.t < since && m(p)).map(p => p.v));
  const out = summary(ps, earlier), pm = {}, sm = {};
  for (const p of every.filter(q => q.t >= since)) {
    if (S.people[p.by]) pm[p.by] = (pm[p.by] || 0) + p.s / 60;
    for (const s of p.sem || []) if (S.seminars[s]) sm[s] = (sm[s] || 0) + p.s / 60;
  }
  const ranked = o => Object.entries(o).sort((a, b) => b[1] - a[1]).filter(([, v]) => Math.round(v)).map(([id, v]) => ({ id, minutes: Math.round(v) }));
  const adm = isAdmin(false);
  out.people = on("people") || adm ? ranked(pm) : [];
  out.seminars = on("groups") || adm ? ranked(sm) : [];
  const shown = pid => who.startsWith("sem:") ? !!pid && (S.people[pid]?.seminars || []).includes(who.slice(4)) : who ? pid === who : true;
  out.fun = fun(raw.filter(p => p.t >= since), shown);
  if (!(on("people") || adm)) Object.assign(out.fun, { people: [], awards: [] });
  else if (who && !who.startsWith("sem:")) out.fun.awards = [];
  out.first = every.reduce((m, p) => Math.min(m, p.t), Infinity);
  if (out.first === Infinity) out.first = null;
  out.wallAdds = who ? 0 : S.wall.filter(t => since <= t && t < until).length;
  return out;
}, STATS);
route("GET", "api/stats/song/{vid}", c => {
  const ps = allPlays().filter(p => counted(p) && p.v === c.params.vid);
  if (!ps.length) return { plays: 0 };
  const adders = {};
  for (const p of ps) if (p.src === "user" && S.people[p.by]) adders[p.by] = (adders[p.by] || 0) + 1;
  const top = Object.entries(adders).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
  return { plays: ps.length, first: ps[0].t, last: ps.at(-1).t, by: on("people") || isAdmin(false) ? top : "", radio: ps.filter(p => p.src === "auto").length };
}, STATS);
route("GET", "api/stats/export.csv", c => {
  const who = c.q.get("who") || "", since = num(c.q.get("since")), until = num(c.q.get("until")) || now() + 1, names = on("people") || isAdmin(false);
  const cell = v => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  const rows = [["time", "title", "artist", "album", "seconds heard", "length", "added by", "from", "ended"]];
  for (const p of allPlays().filter(p => since <= p.t && p.t < until && mine(who)(p))) {
    const z = zparts(p.t);
    rows.push([`${z.date} ${z.hm}`, p.ti, p.ar, p.al, Math.round(p.s), p.d || "", names ? S.people[p.by]?.name || "" : "", p.src === "auto" ? "radio" : "added", p.x || "played"]);
  }
  return download("﻿" + rows.map(r => r.map(cell).join(",")).join("\r\n") + "\r\n", "text/csv; charset=utf-8", `tunebox-plays-${today()}.csv`);
}, STATS);
function onThisDay() {
  const z = zparts(now());
  for (const [months, lbl] of [[12, "A year ago today"], [1, "A month ago today"]]) {
    let y = z.year, m = z.mon - months;
    while (m < 1) { m += 12; y--; }
    const probe = new Date(Date.UTC(y, m - 1, z.day));
    if (probe.getUTCMonth() !== m - 1) continue;           // the 31st, in a shorter month
    const date = probe.toISOString().slice(0, 10);
    const ps = S.plays.filter(p => counted(p) && zparts(p.t).date === date), songs = new Map();
    for (const p of ps) { if (!songs.has(p.v)) songs.set(p.v, { n: 0, p }); songs.get(p.v).n++; }
    if (songs.size >= 3) return { key: "onthisday", title: "On this day",
      subtitle: `${lbl}, ${z.day} ${probe.toLocaleString("en-GB", { month: "long", timeZone: "UTC" })} ${y}`,
      items: [...songs.values()].sort((a, b) => b.n - a.n).slice(0, 30).map(x => trackOfPlay(x.p)) };
  }
  return null;
}

/* house.py */
route("GET", "api/house", housePublic);
route("GET", "api/admin/house", () => ({ ...housePublic(), features: Object.keys(FEATURES), presets: PRESETS, accents: ACCENTS }), ADMIN);
route("GET", "api/setup", () => { if (S.house.welcome && S.admin.hash) { S.house.welcome = false; saveHouse(); } return { show: !!S.house.welcome }; });
route("POST", "api/setup/done", () => { if (S.house.welcome) { S.house.welcome = false; saveHouse(); } return { ok: true }; });
const word = (v, fallback) => squeeze(v).slice(0, 24) || fallback;
const savedHouse = (c, ev, msg) => { saveHouse(); audit(ev, msg, c); return housePublic(); };
route("PATCH", "api/admin/house", c => {
  const b = c.body, h = S.house, what = [];
  if (b.name != null) { h.name = word(b.name, "Tunebox"); what.push(`name "${h.name}"`); }
  if (b.accent != null) { if (!ACCENTS.includes(b.accent)) fail(400, "unknown accent"); h.accent = b.accent; what.push("accent"); }
  if (b.tz != null) {
    if (b.tz) try { new Intl.DateTimeFormat("en", { timeZone: b.tz }); } catch { fail(400, "unknown time zone"); }
    h.tz = b.tz; what.push("time zone " + (b.tz || "the server's"));
  }
  if (b.network != null) { h.network = squeeze(b.network).slice(0, 32); what.push(h.network ? `network "${h.network}"` : "network: detected"); }
  if (b.signups != null) { if (!["open", "closed"].includes(b.signups)) fail(400, "signups: open or closed"); h.signups = b.signups; what.push(b.signups === "open" ? "anyone can add a name" : "only the admin adds names"); }
  if (b.groups != null) {
    const g = h.groups;
    if ("one" in b.groups) g.one = word(b.groups.one, g.one);
    if ("many" in b.groups) g.many = word(b.groups.many, g.many);
    if ("required" in b.groups) g.required = !!b.groups.required;
    if (["open", "admin"].includes(b.groups.create)) g.create = b.groups.create;
    what.push(`groups are "${g.many}"`);
  }
  if (b.newPerson != null) { h.newPerson.groups = (b.newPerson.groups || []).filter(s => S.seminars[s]).slice(0, 12); what.push("a new person's groups"); }
  if (b.wall != null) {
    const { night, ...rest } = b.wall;
    if (night != null) { if (night && !HOURS.test(String(night))) fail(400, "Night hours look like 23:00-07:00"); h.wall.night = String(night); }
    for (const [k, v] of Object.entries(rest)) if (k in h.wall && k !== "night") h.wall[k] = !!v;
    what.push("the wall screen");
  }
  if (b.quiet != null) {
    const q = h.quiet;
    if (b.quiet.hours != null) { if (b.quiet.hours && !HOURS.test(String(b.quiet.hours))) fail(400, "Quiet hours look like 22:00-08:00"); q.hours = String(b.quiet.hours); }
    if (b.quiet.max != null) q.max = clamp(int(+b.quiet.max), 0, 100);
    what.push(q.hours ? `quiet hours ${q.hours} at most ${q.max}` : "no quiet hours");
  }
  return savedHouse(c, "house", "House: " + (what.join(", ") || "nothing"));
}, ADMIN);
route("PATCH", "api/admin/features", c => {
  const changed = Object.entries(c.body.features || {}).filter(([k, v]) => FEATURES[k] && on(k) !== !!v);
  for (const [k, v] of changed) S.house.features[k] = !!v;
  return savedHouse(c, "features", "Switched " + (changed.map(([k, v]) => `${label(k)} ${v ? "on" : "off"}`).join(", ") || "nothing"));
}, ADMIN);
route("POST", "api/admin/features/preset", c => {
  const off = PRESETS[c.body.name] || fail(404, "No such preset");
  for (const k in FEATURES) S.house.features[k] = !off.includes(k);
  return savedHouse(c, "features", `Preset: ${c.body.name}`);
}, ADMIN);
const SETUP_KEYS = ["name", "accent", "features", "groups", "wall", "signups", "quiet"];
route("GET", "api/admin/features/export", () => download(JSON.stringify({ tunebox_setup: 1, ...Object.fromEntries(SETUP_KEYS.map(k => [k, S.house[k]])) }, null, 1),
  "application/json", "tunebox-setup.json"), ADMIN);
route("POST", "api/admin/features/import", c => {
  const s = c.body.setup || {};
  if (s.tunebox_setup !== 1) fail(400, "That isn't a Tunebox setup file");
  const nu = mergedHouse(Object.fromEntries(SETUP_KEYS.filter(k => k in s).map(k => [k, s[k]])));
  nu.features = Object.fromEntries(Object.keys(FEATURES).map(k => [k, nu.features[k] !== false]));
  if (!ACCENTS.includes(nu.accent) || !["open", "closed"].includes(nu.signups)) fail(400, "That setup file has a value this Tunebox doesn't know");
  for (const k of SETUP_KEYS) S.house[k] = nu[k];
  return savedHouse(c, "features", "Loaded a setup file");
}, ADMIN);
function groupFields(g, b) {
  if (b.name != null) {
    const name = squeeze(b.name).slice(0, 24);
    if (!name) fail(400, "Type a name");
    if (Object.values(S.seminars).some(x => x.name.toLowerCase() === name.toLowerCase() && x.id !== g.id)) fail(409, "That name is taken");
    g.name = name;
  }
  if (b.color != null) { if (!/^#[0-9a-fA-F]{6}$/.test(b.color)) fail(400, "bad colour"); g.color = b.color.toUpperCase(); }
}
route("POST", "api/admin/groups", c => {
  const probe = {};
  groupFields(probe, { name: c.body.name || "", color: c.body.color });
  const g = Object.assign(addSeminar(probe.name), probe);
  audit("group", `Added the group ${g.name}`, c);
  return g;
}, ADMIN);
route("PATCH", "api/admin/groups/{gid}", c => {
  const g = S.seminars[c.params.gid] || fail(404, "No such group");
  groupFields(g, c.body); savePeople();
  audit("group", `Changed the group ${g.name}`, c);
  return g;
}, ADMIN);
route("DELETE", "api/admin/groups/{gid}", c => {
  const gid = c.params.gid, g = S.seminars[gid] || fail(404, "No such group");
  delete S.seminars[gid];
  for (const p of Object.values(S.people)) p.seminars = (p.seminars || []).filter(s => s !== gid);
  if (S.house.newPerson.groups.includes(gid)) { S.house.newPerson.groups = S.house.newPerson.groups.filter(s => s !== gid); saveHouse(); }
  savePeople();
  audit("group", `Removed the group ${g.name}`, c);
  return { ok: true };
}, ADMIN);
const byAt = o => Object.entries(o).sort((a, b) => (b[1].at || 0) - (a[1].at || 0));
route("GET", "api/admin/blocks", () => ({ songs: byAt(S.blocks.songs).map(([id, v]) => ({ id, ...v })),
  artists: byAt(S.blocks.artists).map(([key, v]) => ({ key, ...v })), radio: byAt(S.blocks.radio).map(([id, v]) => ({ id, ...v })) }), ADMIN);
route("POST", "api/admin/blocks", c => {
  const b = c.body, t = b.track ? cleanTrack(b.track) : null;
  let what;
  if (b.kind === "song") {
    if (!t) fail(400, "not a track");
    S.blocks.songs[t.videoId] = { title: t.title, artist: t.artist, at: int(now()) };
    what = `the song "${t.title}"`;
  } else if (b.kind === "artist") {
    const name = squeeze(b.name || (t && t.artist.split(",")[0]) || "").slice(0, 100) || fail(400, "Which artist?");
    S.blocks.artists[name.toLowerCase()] = { name, id: t && !b.name ? t.artistId : "", at: int(now()) };
    what = `the artist ${name}`;
  } else fail(400, "kind: song or artist");
  const n = dropBlocked(`Blocked ${what}`);
  audit("block", `Blocked ${what}`, c);
  return { ok: true, removed: n, message: `Blocked ${what}` + (n ? ` · ${n} taken out of up next` : "") };
}, ADMIN);
route("DELETE", "api/admin/blocks/{kind}/{key:path}", c => {
  const was = S.blocks[c.params.kind]?.[c.params.key] || fail(404, "That isn't blocked");
  delete S.blocks[c.params.kind][c.params.key];
  audit("block", `Unblocked ${was.title || was.name || c.params.key}`, c);
  return { ok: true };
}, ADMIN);

/* admin.py */
route("GET", "api/admin", () => ({ set: !!S.admin.hash, admin: isAdmin(false), lockedFor: Math.max(0, Math.ceil(S.admin.lockedUntil - now())) }));
async function checkPassword(password, c) {
  const a = S.admin;
  if (a.lockedUntil > now()) fail(403, `Too many wrong passwords. Try again in ${Math.ceil((a.lockedUntil - now()) / 60)} min`);
  if (await matches(password, a.hash)) { a.fails = 0; return; }
  a.fails++;
  audit("fail", `Wrong admin password (${a.fails} in a row)`, c);
  if (a.fails >= 5) { a.fails = 0; a.lockedUntil = now() + 300; audit("lockout", "Admin locked for 5 min", c); }
  dirty = true;
  fail(403, "Wrong admin password");
}
route("POST", "api/admin/login", async c => {
  if (!S.admin.hash) {
    if (!c.body.create) fail(409, "No admin password is set yet");
    S.admin.hash = await hashPhrase(cleanPhrase(c.body.password || ""));
    audit("password", "The admin password was set for the first time", c);
  } else await checkPassword(c.body.password, c);
  S.admin.seen = now();
  audit("unlock", "Admin unlocked", c);
  return { ok: true };
});
route("POST", "api/admin/logout", c => { if (isAdmin(false)) audit("logout", "Admin locked", c); S.admin.seen = 0; return { ok: true }; });
route("POST", "api/admin/password", async c => {
  const nu = cleanPhrase(c.body.new || "");
  await checkPassword(c.body.old, c);
  S.admin.hash = await hashPhrase(nu); S.admin.seen = now();
  audit("password", "The admin password was changed", c);
  return { ok: true };
}, ADMIN);
route("POST", "api/admin/reset", () => fail(403, "Only from the server itself"));
route("GET", "api/admin/audit", c => S.audit.slice(-clamp(num(c.q.get("limit"), 300), 1, 300)).reverse(), ADMIN);
route("GET", "api/admin/ytdlp", () => ({ running: YTDLP, installed: YTDLP, latest: YTDLP, outdated: false, restart: false, busy: false, warning: null,
  last: S.ytdlpLast || { ok: null, msg: "", at: 0 } }), ADMIN);
route("POST", "api/admin/ytdlp", c => {
  S.ytdlpLast = { ok: true, msg: `yt-dlp ${YTDLP} is already the newest.`, at: int(now()) };
  audit("ytdlp", S.ytdlpLast.msg, c);
  return { ...S.ytdlpLast, before: YTDLP, after: YTDLP, restart: false };
}, ADMIN);
function listening() {
  const out = {};
  for (const p of allPlays()) if (p.by && counted(p)) {
    const s = out[p.by] ||= { plays: 0, secs: 0, last: 0, songs: {}, track: {} };
    s.plays++; s.secs += p.s; s.last = Math.max(s.last, p.t); s.songs[p.v] = (s.songs[p.v] || 0) + 1; s.track[p.v] = p;
  }
  return out;
}
function adminView(p, h) {
  h ||= { plays: 0, secs: 0, last: 0, songs: {}, track: {} };
  const { phrase, kv, ...rest } = p;
  return { ...rest, locked: !!phrase, plays: h.plays, minutes: Math.round(h.secs / 60), last: h.last,
    top: Object.entries(h.songs).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([v, n]) => ({ title: h.track[v].ti, artist: h.track[v].ar, plays: n })),
    lists: Object.values(S.playlists).filter(l => l.owner === p.id).length, likes: S.playlists[LIKED].tracks.filter(t => (t.likedBy || []).includes(p.id)).length };
}
async function adminFields(p, b) {
  personFields(p, b, true);
  await setPhrase(p, b.phrase);
  if (b.noAdd != null) { if (b.noAdd) p.noAdd = true; else delete p.noAdd; }
  if (b.cap != null) { const cap = clamp(int(+b.cap || 0), 0, 999); if (cap) p.cap = cap; else delete p.cap; }
}
const getPerson = pid => S.people[pid] || fail(404, "No such person");
const nameOf = pid => S.people[pid]?.name || "someone removed";
const rewrite = fn => {
  let n = 0;
  S.plays = S.plays.map(p => { const q = fn({ ...p }); if (JSON.stringify(q) !== JSON.stringify(p)) n++; return q; }).filter(Boolean);
  if (S.open) { const q = fn({ ...S.open }); if (JSON.stringify(q) !== JSON.stringify(S.open)) n++; S.open = q; }
  return n;
};
function rename(pid, to) {
  const p = P();
  for (const t of p.queue) if (t.by === pid) t.by = to;
  for (const s of p.undo) { if (s.by === pid) s.by = to; for (const t of s.queue) if (t.by === pid) t.by = to; }
  for (const h of S.history) if (h.by === pid) h.by = to;
}
route("GET", "api/admin/people", () => { const h = listening(); return Object.values(S.people).map(p => adminView(p, h[p.id])).sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())); }, ADMIN);
route("POST", "api/admin/people", async c => {
  const p = await newPerson(c.body, true);
  await adminFields(p, { noAdd: c.body.noAdd, cap: c.body.cap });
  savePeople(); audit("person.add", `Added ${p.name}`, c);
  return adminView(p, null);
}, ADMIN);
route("POST", "api/admin/people/merge", c => {
  const { source: a, into: b } = c.body;
  if (a === b) fail(400, "Pick two different people");
  const pa = getPerson(a), pb = getPerson(b), n = rewrite(p => p.by === a ? { ...p, by: b } : p);
  rename(a, b);
  for (const t of S.playlists[LIKED].tracks) if ((t.likedBy || []).includes(a)) t.likedBy = [...t.likedBy.filter(x => x !== a), ...(t.likedBy.includes(b) ? [] : [b])];
  for (const l of Object.values(S.playlists)) if (l.owner === a) l.owner = b;
  pb.seminars = [...(pb.seminars || []), ...(pa.seminars || []).filter(s => !(pb.seminars || []).includes(s))];
  delete S.people[a];
  saveLists(); savePeople();
  audit("person.merge", `Merged ${pa.name} into ${pb.name} (${n} plays)`, c);
  return { ok: true, plays: n };
}, ADMIN);
route("PATCH", "api/admin/people/{pid}", async c => {
  const p = getPerson(c.params.pid), b = c.body;
  await adminFields(p, b); savePeople();
  audit("person.edit", `${p.name}: ${b.phrase === "" ? "pass phrase removed" : b.phrase ? "pass phrase set" : b.noAdd ? "blocked from adding songs" : "changed"}`, c);
  return adminView(p, listening()[p.id]);
}, ADMIN);
route("POST", "api/admin/people/{pid}/signout", c => {
  const p = getPerson(c.params.pid);
  if (!p.phrase) fail(400, "That name has no pass phrase, so no device is signed in to it");
  p.kv = (p.kv || 0) + 1; savePeople();
  audit("person.signout", `Signed every device out of ${p.name}`, c);
  return { ok: true };
}, ADMIN);
route("DELETE", "api/admin/people/{pid}", c => {
  const pid = c.params.pid, mode = c.q.get("mode") || "keep";
  if (!["keep", "purge"].includes(mode)) fail(400, "unknown mode");
  const p = getPerson(pid);
  let n = 0;
  if (mode === "purge") {
    n = rewrite(q => q.by === pid ? null : q);
    const l = S.playlists[LIKED];                       // a song only they liked leaves Liked songs
    l.tracks = l.tracks.filter(t => { if (!(t.likedBy || []).includes(pid)) return true; t.likedBy = t.likedBy.filter(x => x !== pid); return t.likedBy.length > 0; });
    for (const x of Object.values(S.playlists)) if (x.owner === pid) { delete S.playlists[x.id]; if (S.settings.alarm.list === x.id) S.settings.alarm.list = null; }
    rename(pid, "");
  } else for (const x of Object.values(S.playlists)) if (x.owner === pid) x.owner = "";
  delete S.people[pid];
  saveLists(); savePeople();
  audit("person.delete", `Removed ${p.name}` + (mode === "purge" ? ` with ${n} plays, their likes and playlists` : ""), c);
  return { ok: true };
}, ADMIN);
route("GET", "api/admin/people/{pid}/detail", c => {
  getPerson(c.params.pid);
  return { lists: sortedLists().filter(l => l.owner === c.params.pid).map(listSummary),
    likes: S.playlists[LIKED].tracks.filter(t => (t.likedBy || []).includes(c.params.pid)).map(t => ({ videoId: t.videoId, title: t.title, artist: t.artist, thumb: t.thumb })) };
}, ADMIN);
route("POST", "api/admin/people/{pid}/unlike", c => {
  const pid = c.params.pid, p = getPerson(pid), l = S.playlists[LIKED];
  let n = 0;
  const keep = [];
  for (const t of l.tracks) {
    if ((t.likedBy || []).includes(pid) && (c.body.all || t.videoId === c.body.videoId)) { n++; t.likedBy = t.likedBy.filter(x => x !== pid); if (!t.likedBy.length) continue; }
    keep.push(t);
  }
  if (n) { l.tracks = keep; l.updated = int(now()); saveLists(); audit("likes.delete", `Removed ${n} of ${p.name}'s likes`, c); }
  return { removed: n };
}, ADMIN);
route("GET", "api/admin/plays", c => {
  const who = c.q.get("who") || "", before = num(c.q.get("before")) || Infinity;
  return allPlays().filter(p => p.t < before && (!who || p.by === who)).reverse().slice(0, clamp(num(c.q.get("limit"), 100), 1, 500));
}, ADMIN);
route("DELETE", "api/admin/plays", c => {
  const b = c.body;
  let n;
  if (b.all) {
    if (!b.who) fail(400, "Whose plays?");
    n = rewrite(p => p.by === b.who ? null : p);
    audit("plays.delete", `Removed all ${n} plays of ${nameOf(b.who)}`, c);
  } else {
    const gone = new Set((b.plays || []).map(x => `${int(+x.t || 0)}|${x.v}`));
    n = rewrite(p => gone.has(`${p.t}|${p.v}`) ? null : p);
    if (n) audit("plays.delete", `Removed ${plural(n, "play")} from the log`, c);
  }
  return { removed: n };
}, ADMIN);
function deviceOf(ua) {
  const sys = [["iPhone", "iPhone"], ["iPad", "iPad"], ["Android", "Android"], ["CrOS", "ChromeOS"], ["Windows", "Windows"], ["Macintosh", "Mac"], ["Linux", "Linux"]].find(([k]) => ua.includes(k))?.[1] || "";
  const br = [["Firefox/", "Firefox"], ["Edg/", "Edge"], ["OPR/", "Opera"], ["SamsungBrowser", "Samsung Internet"], ["Chrome/", "Chrome"], ["Safari/", "Safari"]].find(([k]) => ua.includes(k))?.[1] || "";
  return [sys, br].filter(Boolean).join(" · ") || "Something";
}
route("GET", "api/admin/here", () => {
  // this browser, and the house's other devices (made up: the demo has only you)
  const others = [{ ip: "192.168.1.31", device: "Android · Chrome", who: "mila", wall: false }, { ip: "192.168.1.40", device: "iPhone · Safari", who: "jonas", wall: false },
    { ip: "192.168.1.52", device: "Linux · Firefox", who: "", wall: true }].filter(d => !d.who || S.people[d.who]).map(d => ({ ...d, at: now() - 2 }));
  return [...here.values()].filter(d => d.at > now() - 60).concat(others).map(d => ({ ...d, name: S.people[d.who]?.name || "" }));
}, ADMIN);

/* local.py: the file stays in this browser (Cache API); it isn't converted or read for tags */
const SNIFF = [["flac", h => h.startsWith("fLaC")], ["wav", h => h.startsWith("RIFF") && h.slice(8, 12) === "WAVE"], ["aiff", h => h.startsWith("FORM") && /AIF[FC]/.test(h.slice(8, 12))],
  ["opus", h => h.startsWith("OggS") && h.slice(0, 64).includes("OpusHead")], ["ogg", h => h.startsWith("OggS")], ["m4a", h => h.slice(4, 8) === "ftyp"],
  ["mp3", h => h.startsWith("ID3")], ["aac", h => h.charCodeAt(0) === 0xFF && (h.charCodeAt(1) & 0xF6) === 0xF0], ["mp3", h => h.charCodeAt(0) === 0xFF && (h.charCodeAt(1) & 0xE0) === 0xE0]];
const sniff = h => SNIFF.find(([, f]) => f(h))?.[0] || null;
const IMAGES = { jpg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif" };
const imageKind = h => h.startsWith("\xff\xd8\xff") ? "jpg" : h.startsWith("\x89PNG\r\n\x1a\n") ? "png" : h.startsWith("RIFF") && h.slice(8, 12) === "WEBP" ? "webp" : /^GIF8[79]a/.test(h) ? "gif" : null;
const head = async (blob, n = 64) => String.fromCharCode(...new Uint8Array(await blob.slice(0, n).arrayBuffer()));
const usedLocal = () => Object.values(S.local).reduce((s, x) => s + (x.size || 0), 0);
const DISK = { total: 64 * GB, free: 41 * GB };
const disk = () => ({ total: DISK.total, free: DISK.free - usedLocal(), used: usedLocal(), count: Object.keys(S.local).length });
function room() {
  const lim = S.house.local, d = disk();
  let left = d.free - int((lim.reserveGB || 0) * GB);
  if (lim.capGB != null) left = Math.min(left, int(lim.capGB * GB) - d.used);
  return Math.max(0, left);
}
const mayEdit = (s, c, touch = true) => isAdmin(touch) || (!!s.by && c.who === s.by);
const localView = (s, c) => ({ ...localTrack(s), by: s.by || "", at: s.at, size: s.size, ext: s.ext, was: s.was || s.ext, mine: mayEdit(s, c, false) });
const owned = (sid, c) => { const s = S.local[sid] || fail(404, "No such local song"); if (!mayEdit(s, c)) fail(403, "Only whoever uploaded this song, or the admin, can change it"); return s; };
function everywhere(vid, fn) {
  const p = P(), spots = [p.queue, S.history, ...p.undo.map(s => s.queue), ...Object.values(S.playlists).map(l => l.tracks)];
  for (const ts of spots) for (let i = ts.length - 1; i >= 0; i--) if (ts[i].videoId === vid) fn(ts, i);
}
function refreshLocal(s) {
  const t = localTrack(s);
  everywhere(t.videoId, (ts, i) => Object.assign(ts[i], t));
  const seed = P().seed;
  if (seed?.videoId === t.videoId) Object.assign(seed, { title: t.title, artist: t.artist, thumb: t.thumb });
  saveLists();
}
route("GET", "api/local", c => ({ songs: Object.values(S.local).sort((a, b) => b.at - a.at).map(s => localView(s, c)), maxMB: S.house.local.maxMB, room: room(), used: usedLocal() }), "local");
route("POST", "api/local/upload", async c => {
  needFeature("local");
  const by = needWho(c), maxMB = S.house.local.maxMB, file = await c.req.blob();
  if (file.size > maxMB * MB) fail(413, `Too big: a file can be ${maxMB} MB at most`);
  if (file.size > room()) fail(413, "There is no room left for local songs");
  if (!file.size) fail(400, "That file is empty");
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()))].map(b => b.toString(16).padStart(2, "0")).join("");
  if (Object.values(S.local).some(s => s.sha === digest)) fail(409, "Already here");
  const kind = sniff(await head(file)) || fail(400, "That isn't an audio file");
  const name = (c.q.get("name") || "").replace(/\\/g, "/").split("/").pop().slice(0, 200), sid = hex(8);
  const stem = name.replace(/\.[^.]*$/, "").replace(/_/g, " ");
  await (await blobs()).put(`demo/local/${sid}`, new Response(file));
  // shortcut: the length is guessed from the size at 256 kbit/s (no decoder here); fine for a demo
  S.local[sid] = { id: sid, title: squeeze(stem).slice(0, 300) || "Untitled", artist: "", album: "", secs: Math.round(file.size * 8 / 256000),
    ext: kind, size: file.size, sha: digest, by, at: int(now()), orig: name, was: kind, cv: 0, cx: "" };
  return localView(S.local[sid], c);
});
route("GET", "api/local/{sid}/cover", async c => {
  const s = S.local[c.params.sid], hit = s?.cv && await (await blobs()).match(`demo/cover/${s.id}`);
  return hit ? new Response(hit.body, { headers: { "Content-Type": IMAGES[s.cx] } }) : fail(404, "No cover");
});
route("PATCH", "api/local/{sid}", c => {
  const s = owned(c.params.sid, c);
  for (const k of ["title", "artist", "album"]) if (c.body[k] != null) s[k] = squeeze(c.body[k]).slice(0, 300);
  if (!s.title) fail(400, "A song needs a title");
  refreshLocal(s);
  return localView(s, c);
}, "local");
route("POST", "api/local/{sid}/cover", async c => {
  needFeature("local");
  const s = owned(c.params.sid, c), pic = await c.req.blob();
  if (pic.size > 5 * MB) fail(413, "That picture is too big (5 MB at most)");
  const kind = imageKind(await head(pic, 16)) || fail(400, "That isn't a picture (JPEG, PNG or WebP)");
  await (await blobs()).put(`demo/cover/${s.id}`, new Response(pic));
  s.cv = (s.cv || 0) + 1; s.cx = kind;
  refreshLocal(s);
  return localView(s, c);
});
route("DELETE", "api/local/{sid}", async c => {
  const s = owned(c.params.sid, c), vid = "local:" + s.id, p = P();
  if (cur()?.videoId === vid) { if (p.index + 1 < p.queue.length) playIndex(p.index + 1); else stop(); }
  everywhere(vid, (ts, i) => { if (ts === p.queue && i === p.index) return; if (ts === p.queue && i < p.index) p.index--; ts.splice(i, 1); });
  delete S.local[s.id];
  const store = await blobs();
  await Promise.all([store.delete(`demo/local/${s.id}`), store.delete(`demo/cover/${s.id}`)]);
  saveLists();
  if (isAdmin(false) && !(s.by && c.who === s.by)) audit("local.delete", `Removed the local song "${s.title}"`, c);
  return { ok: true };
}, "local");
const space = () => ({ ...disk(), ...S.house.local, room: room(), encoders: { mpv: true, flac: true, opus: true } });
route("GET", "api/admin/local/disk", space, ADMIN);
route("PATCH", "api/admin/local/limits", c => {
  const lim = S.house.local, b = c.body;
  if (b.capGB != null) lim.capGB = b.capGB < 0 ? null : Math.round(Math.min(b.capGB, 100000) * 100) / 100;
  if (b.reserveGB != null) lim.reserveGB = Math.round(clamp(b.reserveGB, 0, 100000) * 100) / 100;
  if (b.maxMB != null) lim.maxMB = clamp(int(b.maxMB), 1, 4096);
  saveHouse();
  audit("local.limits", `Local songs: ${lim.capGB === null ? "no cap" : lim.capGB + " GB"}, ${lim.reserveGB} GB kept free, files up to ${lim.maxMB} MB`, c);
  return space();
}, ADMIN);

/* backup.py: the same file a real Tunebox writes, so a demo house can move into a real one */
function snapshotFiles(secrets) {
  const stats = {};
  for (const p of allPlays()) if (p.t > now() - STATS_DAYS * DAY) (stats[p.v] ||= { track: trackFor(p.v, p), plays: [] }).plays.push(p.t);
  const people = structuredClone(S.people);
  if (!secrets) for (const p of Object.values(people)) { delete p.phrase; delete p.kv; }
  const logs = {};
  for (const p of allPlays()) { const { p0, ...q } = p; (logs[zparts(p.t).month + ".jsonl"] ||= []).push(JSON.stringify(q)); }
  const files = { settings: S.settings, history: S.history, playlists: S.playlists, people, seminars: { v: 2, groups: S.seminars }, stats,
    house: S.house, blocklist: S.blocks, local: S.local, wall: { adds: S.wall }, ...(secrets ? { keys: { secret: "demo", admin: S.admin.hash } } : {}) };
  return { tunebox: 1, made: int(now()), files, plays: Object.fromEntries(Object.entries(logs).map(([k, v]) => [k, v.join("\n") + "\n"])), ...(secrets ? {} : { stripped: true }) };
}
route("GET", "api/backup", () => download(JSON.stringify(snapshotFiles(isAdmin())), "application/json", `tunebox-backup-${today()}.json`));
route("GET", "api/backup/full", async c => {
  audit("backup", "Downloaded a full backup, with the local songs", c);
  const store = await blobs(), enc = new TextEncoder(), files = [{ name: "tunebox-backup.json", data: enc.encode(JSON.stringify(snapshotFiles(true))) }];
  for (const s of Object.values(S.local)) {
    const a = await store.match(`demo/local/${s.id}`), b = s.cv && await store.match(`demo/cover/${s.id}`);
    if (a) files.push({ name: `local/${s.id}.${s.ext}`, data: new Uint8Array(await a.arrayBuffer()) });
    if (b) files.push({ name: `local/covers/${s.id}.${s.cx}`, data: new Uint8Array(await b.arrayBuffer()) });
  }
  return download(zip(files), "application/zip", `tunebox-full-${today()}.zip`);
}, ADMIN);
function putBack(files, logs) {
  const keep = { audit: S.audit, admin: S.admin }, rev = S.rev, player = S.player, ytdlpLast = S.ytdlpLast;
  S = Object.assign(fresh(keep), { player, ytdlpLast });
  S.rev = { house: rev.house + 1, lists: rev.lists + 1, people: rev.people + 1 };
  const s = settingsDefault(), saved = files.settings || {};
  Object.assign(s.alarm, saved.alarm || {});
  Object.assign(s, { ...saved, alarm: s.alarm });
  S.settings = s;
  S.history = Array.isArray(files.history) ? files.history : [];
  S.playlists = files.playlists && typeof files.playlists === "object" ? files.playlists : {};
  S.playlists[LIKED] ||= liked();
  S.people = files.people || {};
  S.seminars = files.seminars?.v === 2 ? files.seminars.groups || {} : { ...SEMINARS, ...(files.seminars || {}) };
  S.house = mergedHouse(files.house);
  S.blocks = { songs: {}, artists: {}, radio: {}, ...(files.blocklist || {}) };
  S.local = Object.fromEntries(Object.entries(files.local || {}).filter(([k, v]) => /^[0-9a-f]{16}$/.test(k) && v?.id === k));
  S.wall = files.wall?.adds || [];
  S.plays = Object.keys(logs).sort().flatMap(k => String(logs[k]).split("\n").map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean))
    .sort((a, b) => a.t - b.t);
  S.open = null;
}
route("POST", "api/restore", c => {
  const b = c.body.backup || {}, files = b.files, logs = b.plays || {};
  if (b.tunebox !== 1 || !files || typeof files !== "object" || typeof logs !== "object") fail(400, "That isn't a Tunebox backup");
  if (Object.keys(logs).some(n => !n.endsWith(".jsonl") || /[/\\]/.test(n) || n.startsWith("."))) fail(400, "That backup has a bad play log file name");
  if (!files.keys && files.people) for (const [pid, p] of Object.entries(files.people)) { const nowP = S.people[pid] || {}; if (nowP.phrase) p.phrase = nowP.phrase; if (nowP.kv) p.kv = nowP.kv; }
  putBack(files, logs);
  audit("restore", `Restored a backup from ${new Date((b.made || 0) * 1000).toISOString().slice(0, 10)}`, c);
  return { ok: true, before: `before-restore-${today()}.json` };
}, ADMIN);
route("POST", "api/admin/wipe", c => {
  if (c.body.confirm !== "delete") fail(400, "Not confirmed");
  stop();
  const keep = { audit: S.audit, admin: S.admin }, rev = S.rev;
  S = fresh(keep);
  S.rev = { house: rev.house + 1, lists: rev.lists + 1, people: rev.people + 1 };
  audit("wipe", "Deleted the house's data", c);
  return { ok: true, before: `before-wipe-${today()}.json` };
}, ADMIN);

/* a zip that stores its files as they are (audio doesn't compress) */
const CRC = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = buf => { let c = ~0; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return ~c >>> 0; };
function zip(files) {
  const enc = new TextEncoder(), parts = [], central = [];
  let off = 0;
  for (const f of files) {
    const name = enc.encode(f.name), crc = crc32(f.data), n = f.data.length, h = new DataView(new ArrayBuffer(30)), cd = new DataView(new ArrayBuffer(46));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x800, 2], [12, 33, 2], [14, crc, 4], [18, n, 4], [22, n, 4], [26, name.length, 2]].forEach(([o, v, w]) => w === 4 ? h.setUint32(o, v, true) : h.setUint16(o, v, true));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x800, 2], [14, 33, 2], [16, crc, 4], [20, n, 4], [24, n, 4], [28, name.length, 2], [42, off, 4]].forEach(([o, v, w]) => w === 4 ? cd.setUint32(o, v, true) : cd.setUint16(o, v, true));
    parts.push(h, name, f.data); central.push(cd, name);
    off += 30 + name.length + n;
  }
  const size = central.reduce((s, b) => s + b.byteLength, 0), end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true); end.setUint32(12, size, true); end.setUint32(16, off, true);
  return new Blob([...parts, ...central, end], { type: "application/zip" });
}
