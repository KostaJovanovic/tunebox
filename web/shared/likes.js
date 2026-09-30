/* Liked songs: one list shared by the whole house. A heart is any element with data-like="<videoId>";
   paintLikes() fills or empties every heart on the page. Hearts for "the song playing now" carry the
   class like-now and follow the current song. */
import { $$ } from "./dom.js";
import { api, errText } from "./api.js";
import { state } from "./playback.js";
import { feat } from "./house.js";

let liked = new Set(), likedRev = null, toast = () => {}, changed = () => {};

export const isLiked = vid => liked.has(vid);

/* toaster: shows messages; onChange: runs after a like or unlike (e.g. to refresh an open Liked list) */
export function setupLikes(toaster, onChange = () => {}) { toast = toaster; changed = onChange; }

function paintLikes() {
  const cur = state.current?.videoId || "";
  $$(".like-now").forEach(b => b.dataset.like = cur);
  $$("[data-like]").forEach(b => {
    const on = !!b.dataset.like && liked.has(b.dataset.like);
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); b.title = on ? "Unlike" : "Like";
  });
}

/* Reloads the liked list when the server says playlists changed (state.listsRev) */
export async function syncLikes(rev) {
  if (!feat("likes")) { liked = new Set(); likedRev = null; return paintLikes(); }   /* switched off: no hearts */
  if (rev === likedRev) return paintLikes();
  try {
    const p = await api("api/lists/liked");
    liked = new Set(p.tracks.map(t => t.videoId)); likedRev = rev; paintLikes();
  } catch {}
}

export async function toggleLike(t) {
  if (!t) return;
  const on = !liked.has(t.videoId);
  on ? liked.add(t.videoId) : liked.delete(t.videoId); paintLikes();
  try { await api("api/like", { track: t, liked: on }); toast(on ? "Added to Liked songs" : "Removed from Liked songs"); }
  catch (e) { on ? liked.delete(t.videoId) : liked.add(t.videoId); paintLikes(); toast(errText(e)); }
  changed();
}

export const likeCurrent = () => toggleLike(state.current);
