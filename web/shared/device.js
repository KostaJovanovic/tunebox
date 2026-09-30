/* This device's own preferences (set up early by look.js): theme and accent. */
export const { store, ACCENTS, apply: applyLook, lite, weak } = window.look;

export function clearLocal() {
  if (!confirm("Reset theme, accent and performance mode on this device? Playlists, history and server settings stay.")) return;
  try { localStorage.clear(); sessionStorage.clear(); } catch {}
  location.href = "./";
}
