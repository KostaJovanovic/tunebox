/* This device's own preferences (set up early by look.js): theme and accent. */
import { ask } from "./dialog.js";

export const { store, ACCENTS, apply: applyLook, lite, weak } = window.look;

export async function clearLocal() {
  if (!(await ask("Reset theme, accent and performance mode on this device? Playlists, history and server settings stay.", { ok: "Reset" }))) return;
  try { localStorage.clear(); sessionStorage.clear(); } catch {}
  location.href = "./";
}
