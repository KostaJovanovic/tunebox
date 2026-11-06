// A check of the demo's server without a browser: sw.js runs in a Node vm with stand-ins for the
// worker's globals, and every route the pages use is asked once. `node dev/demo/test.mjs`
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const here = new URL(".", import.meta.url);
const store = new Map();
const caches = { open: async () => ({
  match: async k => store.has(k) ? new Response(store.get(k)) : undefined,
  put: async (k, r) => { store.set(k, await r.arrayBuffer()); },
  delete: async k => store.delete(k) }) };
let skew = 0;
const RealDate = Date;
class FakeDate extends RealDate {
  constructor(...a) { a.length ? super(...a) : super(RealDate.now() + skew); }
  static now() { return RealDate.now() + skew; }
}
let onFetch;
const self = { registration: { scope: "http://localhost/" }, location: new URL("http://localhost/sw.js"),
  addEventListener: (type, fn) => { if (type === "fetch") onFetch = fn; } };
const ctx = vm.createContext({ self, caches, console, Response, Request, Headers, Blob, URL, URLSearchParams, TextEncoder, Intl,
  crypto, structuredClone, setTimeout, Date: FakeDate,
  fetch: async url => new Response(readFileSync(new URL("music.json", here))) });
vm.runInContext(readFileSync(new URL("sw.js", here), "utf8"), ctx);

let who = "";
async function call(path, body, method, expect = 200) {
  const init = { method: method || (body === undefined ? "GET" : "POST"), headers: { "X-Demo-Who": who } };
  if (body instanceof Blob) Object.assign(init, { body, headers: { ...init.headers, "Content-Type": "application/octet-stream" } });
  else if (body !== undefined) Object.assign(init, { body: JSON.stringify(body), headers: { ...init.headers, "Content-Type": "application/json" } });
  let res;
  const e = { request: new Request("http://localhost/" + path, init), respondWith: p => { res = p; }, waitUntil: () => {} };
  onFetch(e);
  assert.ok(res, `${path} was not answered`);
  const r = await res;
  const text = await r.text();
  assert.equal(r.status, expect, `${init.method} ${path}: ${r.status} ${text.slice(0, 200)}`);
  return (r.headers.get("content-type") || "").includes("json") ? JSON.parse(text) : text;
}

const s = await call("api/state");
assert.ok(s.current && s.queue.length > 5, "a song plays, with more up next");
assert.ok(s.position > 60, "a minute into the first song");
assert.match(s.current.artist, /Fleetwood Mac/, "the demo opens on a gentle song");
const people = await call("api/people");
assert.equal(people.length, 6);
await call("api/seminars");
await call("api/house");
const lists = await call("api/lists");
assert.ok(lists.find(l => l.id === "top") && lists.length >= 7, "Liked, Top 30 and five playlists");
await call("api/lists/liked"); await call("api/lists/top");
assert.ok((await call("api/history")).length > 50);
await call("api/settings"); await call("api/network");
const home = await call("api/home"); assert.ok(home.length);
const ex = await call("api/explore");
await call(`api/mood?params=${encodeURIComponent(ex.moods[0].items[0].params)}`);
const songs = await call("api/search?q=Daft%20Punk&kind=songs"); assert.ok(songs.length > 10);
assert.ok((await call("api/search?q=dreams&kind=songs")).length, "a search nobody recorded still finds songs");
const albums = await call("api/search?q=Radiohead&kind=albums");
await call(`api/album/${albums[0].id}`);
const artists = await call("api/search?q=Bjork&kind=artists");
assert.ok((await call(`api/artist/${artists[0].id}`)).tracks.length);
const pls = await call("api/search?q=Bonobo&kind=playlists");
await call(`api/playlist/${pls[0].id}`);
await call(`api/where/${songs[0].videoId}`);
const forme = await call("api/forme"); assert.ok(forme.find(x => x.key === "most"));
const st = await call("api/stats?since=0&until=0&who="); assert.ok(st.plays > 1000 && st.fun.awards.length);
await call("api/stats?since=0&until=0&who=mila"); await call("api/stats?since=0&until=0&who=sem:attic");
await call(`api/stats/song/${s.current.videoId}`);
assert.ok((await call("api/stats/export.csv")).startsWith("time,title"));   // text() drops the BOM
await call(`api/lyrics?videoId=${songs[0].videoId}&title=x`);
await call("api/queue/history"); await call("api/radio/skips");
await call("api/resolve?url=" + encodeURIComponent(`https://music.youtube.com/watch?v=${songs[0].videoId}`));

// adding songs needs a name
await call("api/play", { tracks: [songs[1]], mode: "add" }, "POST", 401);
who = "mila";
const added = await call("api/play", { tracks: [songs[1], songs[2]], mode: "add", label: "Two" });
assert.match(added.message, /in queue|next/);
await call("api/play", { tracks: [songs[3]], mode: "now" });
assert.equal((await call("api/state")).current.videoId, songs[3].videoId);
for (const action of ["next", "prev", "toggle", "toggle", "shuffle", "refresh", "undo"]) await call("api/control", { action });
await call("api/control", { action: "seek", value: 30 });
await call("api/control", { action: "volume", value: 40 });
let q = await call("api/state");
await call("api/control", { action: "promote", value: q.offset + 3, videoId: q.queue[3].videoId });
q = await call("api/state");
await call("api/control", { action: "move", value: q.offset + 2, videoId: q.queue[2].videoId, to: q.offset + 4 });
q = await call("api/state");
await call("api/control", { action: "remove", value: q.offset + 1, videoId: q.queue[1].videoId });
await call("api/control", { action: "jump", value: q.offset + 1, videoId: "wrongwrongx" }, "POST", 409);
const hist = await call("api/queue/history");
await call("api/control", { action: "restore", id: hist[1].id });
await call("api/radio/skips", { track: q.queue.at(-1) });
await call(`api/radio/skips/${q.queue.at(-1).videoId}`, undefined, "DELETE");
await call("api/like", { track: songs[4], liked: true });
const mineList = await call("api/lists", { name: "Mine", tracks: [songs[5]] });
await call(`api/lists/${mineList.id}/tracks`, { track: songs[6] });
await call(`api/lists/${mineList.id}/tracks`, { op: "move", videoId: songs[6].videoId, to: 0 }, "PATCH");
await call(`api/lists/${mineList.id}`, { name: "Mine too" }, "PATCH");
await call(`api/lists/${mineList.id}`, undefined, "DELETE");
await call("api/sleep", { minutes: 30 }); await call("api/sleep", {});
await call("api/eq", { preset: "rock" });
await call("api/options", { turns: false });
await call("api/people", { name: "Visitor", seminars: ["attic"] });

// time passes: songs end and the next ones start, the play log grows
const before = (await call("api/stats?since=0&until=0&who=")).plays;
skew = 20 * 60 * 1000;
const later = await call("api/state");
assert.ok(!later.paused && later.current, "still playing 20 minutes later");
assert.ok((await call("api/stats?since=0&until=0&who=")).plays > before, "the songs that ended were logged");

// local songs
const up = await call("api/local/upload?name=My%20song.mp3", new Blob(["ID3" + "x".repeat(5000)]));
await call("api/local/upload?name=list.mp3", new Blob(["#EXTM3U\nhttp://x"]), "POST", 400);
const png = new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3])], { type: "image/png" });
const withCover = await call(`api/local/${up.videoId.slice(6)}/cover`, png);
await call(withCover.thumb);
await call(`api/local/${up.videoId.slice(6)}`, { title: "Renamed" }, "PATCH");
assert.equal((await call("api/local")).songs[0].title, "Renamed");
await call("api/play", { tracks: [up], mode: "next" });

// the admin
await call("api/admin/house", undefined, "GET", 403);
assert.equal((await call("api/admin")).set, false);
await call("api/admin/login", { password: "letmein", create: true });
await call("api/admin/logout", {});
await call("api/admin/login", { password: "wrong" }, "POST", 403);
await call("api/admin/login", { password: "letmein" });
const setup = await call("api/admin/house");
await call("api/admin/house", { name: "Our house", tz: "Europe/Belgrade", quiet: { hours: "22:00-08:00", max: 40 }, wall: { queue: true } }, "PATCH");
await call("api/admin/features", { features: { recap: false } }, "PATCH");
await call("api/admin/features/preset", { name: "home" });
const file = await call("api/admin/features/export");
await call("api/admin/features/import", { setup: file });
const g = await call("api/admin/groups", { name: "Garden" });
await call(`api/admin/groups/${g.id}`, { color: "#123456" }, "PATCH");
await call(`api/admin/groups/${g.id}`, undefined, "DELETE");
await call("api/admin/blocks", { kind: "artist", track: songs[0] });
const blocks = await call("api/admin/blocks");
await call(`api/admin/blocks/artists/${encodeURIComponent(blocks.artists[0].key)}`, undefined, "DELETE");
await call("api/admin/audit"); await call("api/admin/ytdlp"); await call("api/admin/ytdlp", {});
const ap = await call("api/admin/people"); assert.ok(ap[0].plays);
await call("api/admin/people/jonas/detail");
await call("api/admin/people/jonas", { phrase: "open sesame", cap: 3 }, "PATCH");
await call("api/admin/people/jonas/signout", {});
await call("api/admin/plays?who=luka&limit=5");
await call("api/admin/people/merge", { source: "luka", into: "theo" });
await call("api/admin/people/sara?mode=purge", undefined, "DELETE");
await call("api/admin/here"); await call("api/admin/local/disk");
await call("api/admin/local/limits", { maxMB: 100 }, "PATCH");
await call("api/alarm", { enabled: true, time: "07:30", days: [0, 1], list: "liked", test: true });
const backup = await call("api/backup");
assert.equal(backup.tunebox, 1);
const zip = await call("api/backup/full");
assert.ok(zip.startsWith("PK"));
await call("api/restore", { backup });
await call(`api/local/${up.videoId.slice(6)}`, undefined, "DELETE");
await call("api/history", undefined, "DELETE");
await call("api/admin/wipe", { confirm: "delete" });
assert.equal((await call("api/setup")).show, false, "the welcome card goes once an admin password exists");
assert.equal((await call("api/people")).length, 0);
console.log(`ok: ${setup.features.length} features, ${st.plays} plays in the seeded year, every route answered`);
