/* This device's own preferences (set up early by look.js): interface, theme, accent. */
import { setCookie } from "./dom.js";

export const { store, ACCENTS, apply: applyLook } = window.look;

/* Switch between the Bauhaus and Classic interfaces on this device */
export function useUi(ui) {
  store.set("tb_ui", ui);
  setCookie("tb_ui", ui);
  location.href = ui === "classic" ? "classic" : "./";
}

export function clearLocal() {
  if (!confirm("Reset interface, theme and accent on this device? Playlists, history and server settings stay.")) return;
  try { localStorage.clear(); sessionStorage.clear(); } catch {}
  setCookie("tb_ui", "", 0);
  location.href = "./";
}
