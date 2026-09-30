/* Loaded as a plain (blocking) script in <head>, so the look is right before the first paint: this
   device's theme and accent (localStorage: tb_theme, tb_accent), and what the admin set for the house
   (tb_house, the last /api/house this device saw; shared/house.js keeps it fresh): its name, its accent
   for a device that picked none, and the features that are switched off. The modules reach these through
   shared/device.js and shared/house.js. */
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
  /* a Tunebox nobody set up: what the pages assume until the server answers */
  const HOUSE = { name: "Tunebox", accent: "", tz: "", signups: "open", off: [],
    groups: { one: "Seminar", many: "Seminars", required: true, create: "open" }, newPerson: { groups: [] },
    wall: { lyrics: true, queue: false, who: false, clock: true, controls: true } };

  function house() {
    try { return { ...HOUSE, ...JSON.parse(store.get("tb_house", "{}")) }; } catch { return { ...HOUSE }; }
  }

  function apply() {
    const h = house(), theme = store.get("tb_theme", "auto");
    const acc = ACCENTS[store.get("tb_accent", "")] || ACCENTS[h.accent] || ACCENTS.red;   /* this device's own, else the house's */
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
    root.style.setProperty("--red", acc.c); root.style.setProperty("--on-red", acc.on);
    root.dataset.off = h.off.join(" ");                       /* base.css hides what is off */
    root.style.setProperty("--house", JSON.stringify(h.name));   /* the name in the top bar (library.css) */
    const light = theme === "light" || (theme === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
    const m = document.getElementById("themeColor");
    if (m) m.content = light ? lightBg : darkBg;
    const app = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (app) app.content = h.name;
  }

  window.look = { store, ACCENTS, apply, house };
  apply();
  document.title = document.title.replace("Tunebox", house().name);
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", apply);
  try { localStorage.removeItem("tb_ui"); } catch {}      /* left from when there was a Classic interface */
})();
