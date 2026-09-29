/* Loaded as a plain (blocking) script in <head>, so theme and accent apply before the first paint.
   Device-only preferences live in localStorage: theme (tb_theme), accent (tb_accent). The modules reach
   these through shared/device.js. */
(() => {
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  const ACCENTS = {
    red:     { name: "Red",     c: "#E63B2E", on: "#FFFFFF" },
    orange:  { name: "Orange",  c: "#EE6A1F", on: "#111111" },
    yellow:  { name: "Yellow",  c: "#F2C230", on: "#111111" },
    green:   { name: "Green",   c: "#1E8F5A", on: "#FFFFFF" },
    blue:    { name: "Blue",    c: "#1F5FBF", on: "#FFFFFF" },
    magenta: { name: "Magenta", c: "#C8327A", on: "#FFFFFF" },
  };
  const lightBg = "#EFEBE1", darkBg = "#111111";

  function apply() {
    const theme = store.get("tb_theme", "auto"), acc = ACCENTS[store.get("tb_accent", "red")] || ACCENTS.red;
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
    root.style.setProperty("--red", acc.c); root.style.setProperty("--on-red", acc.on);
    const light = theme === "light" || (theme === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
    const m = document.getElementById("themeColor");
    if (m) m.content = light ? lightBg : darkBg;
  }

  window.look = { store, ACCENTS, apply };
  apply();
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", apply);
  try { localStorage.removeItem("tb_ui"); } catch {}      /* left from when there was a Classic interface */
})();
