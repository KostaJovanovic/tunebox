/* Loaded as a plain (blocking) script in <head>, so the look is right before the first paint: this
   device's theme and accent (localStorage: tb_theme, tb_accent), and what the admin set for the house
   (tb_house, the last /api/house this device saw; shared/house.js keeps it fresh): its name, its accent
   for a device that picked none, and the features that are switched off. Also performance mode
   (tb_perf: auto, on or off), html[data-lite]: motion.css turns the moving and the blur off. The modules reach these through
   shared/device.js and shared/house.js. */
(() => {
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  const ACCENTS = {
    /* c: the colour, on: text on it, d and l: the colour as text on the dark and the light theme (4.5:1) */
    red:     { name: "Red",     c: "#D9352A", on: "#FFFFFF", d: "#E15F57", l: "#B82D24" },
    orange:  { name: "Orange",  c: "#EE6A1F", on: "#111111", d: "#EE6A1F", l: "#A24815" },
    yellow:  { name: "Yellow",  c: "#F2C230", on: "#111111", d: "#F2C230", l: "#775F18" },
    green:   { name: "Green",   c: "#1C8654", on: "#FFFFFF", d: "#40996F", l: "#187147" },
    blue:    { name: "Blue",    c: "#1F5FBF", on: "#FFFFFF", d: "#5B8AD0", l: "#1F5FBF" },
    magenta: { name: "Magenta", c: "#C8327A", on: "#FFFFFF", d: "#D56199", l: "#B22C6D" },
  };
  const lightBg = "#EFEBE1", darkBg = "#111111";
  /* a Tunebox nobody set up: what the pages assume until the server answers */
  const HOUSE = { name: "Tunebox", accent: "", tz: "", signups: "open", off: [],
    groups: { one: "Seminar", many: "Seminars", required: true, create: "open" }, newPerson: { groups: [] },
    wall: { lyrics: true, queue: false, who: false, clock: true, controls: true, night: "", qr: true }, quiet: { hours: "", max: 30 } };

  /* auto: a device with 2 GB of memory or less (only Chrome-based browsers say), or 2 cores or fewer */
  const weak = () => (navigator.deviceMemory > 0 && navigator.deviceMemory <= 2) || (navigator.hardwareConcurrency > 0 && navigator.hardwareConcurrency <= 2);
  const lite = () => { const m = store.get("tb_perf", "auto"); return m === "on" || (m === "auto" && weak()); };

  function house() {
    try { return { ...HOUSE, ...JSON.parse(store.get("tb_house", "{}")) }; } catch { return { ...HOUSE }; }
  }

  function apply() {
    const h = house(), root = document.documentElement;
    const own = !h.off.includes("look") || root.hasAttribute("data-admin");   /* off: the device's own picks are ignored, not forgotten */
    const theme = own ? store.get("tb_theme", "auto") : "auto";
    const acc = (own && ACCENTS[store.get("tb_accent", "")]) || ACCENTS[h.accent] || ACCENTS.red;   /* this device's own, else the house's */
    if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
    root.style.setProperty("--red", acc.c); root.style.setProperty("--on-red", acc.on);
    root.style.setProperty("--acc-d", acc.d); root.style.setProperty("--acc-l", acc.l);
    root.dataset.off = h.off.join(" ");
    offRules(h.off);
    root.toggleAttribute("data-lite", lite());
    root.style.setProperty("--house", JSON.stringify(h.name));   /* the name in the top bar (library.css) */
    const light = theme === "light" || (theme === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
    const m = document.getElementById("themeColor");
    if (m) m.content = light ? lightBg : darkBg;
    const app = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (app) app.content = h.name;
  }

  /* What is switched off: gone for everyone, faded for the admin (html[data-admin]). The playlists page
     (data-fall="lists") goes only when both playlists and likes are off. */
  function offRules(off) {
    let el = document.getElementById("offRules");
    if (!el) { el = document.createElement("style"); el.id = "offRules"; document.head.append(el); }
    const sel = off.filter(f => /^\w+$/.test(f)).map(f => `[data-f~="${f}"]`);
    if (off.includes("playlists") && off.includes("likes")) sel.push('[data-fall="lists"]');
    el.textContent = !sel.length ? "" : `html:not([data-admin]) :is(${sel.join(",")}) { display: none !important; }
      html[data-admin] :is(${sel.join(",")}) { opacity: .45; }`;
  }

  window.look = { store, ACCENTS, apply, house, lite, weak };
  apply();
  document.title = document.title.replace("Tunebox", house().name);
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", apply);
  try { localStorage.removeItem("tb_ui"); } catch {}      /* left from when there was a Classic interface */
})();
