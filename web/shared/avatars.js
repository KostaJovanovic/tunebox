/* The icons a name can wear: drawn lines on a 24-unit grid, keyed by the emoji that is saved with the
   person (people.json keeps the emoji, so the CLI and the terminal interface still show something).
   An emoji not drawn here (set from the command line) is shown as it is. */
const PATHS = {
  /* music */
  "🎸": '<path d="M12 9c-2.2 0-3.5 1.3-3.5 3 0 1 .7 1.5.7 2.3 0 .9-2.2 1.5-2.2 3.7 0 2.4 2.2 4 5 4s5-1.6 5-4c0-2.2-2.2-2.8-2.2-3.7 0-.8.7-1.3.7-2.3 0-1.7-1.3-3-3.5-3zM12 9V2M10.5 2.5h3M10.5 19.5h3"/><circle cx="12" cy="16" r="1.4"/>',
  "🎧": '<path d="M4 17v-5a8 8 0 0 1 16 0v5"/><rect x="3" y="14" width="4" height="7" rx="1"/><rect x="17" y="14" width="4" height="7" rx="1"/>',
  "🎹": '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M7.5 13v7M12 13v7M16.5 13v7"/><path d="M5.8 4h3.4v9H5.8zM10.3 4h3.4v9h-3.4zM14.8 4h3.4v9h-3.4z" fill="currentColor" stroke="none"/>',
  "🥁": '<ellipse cx="12" cy="11" rx="8" ry="3"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6M8 14v6M16 14v6M10 8 5 2M14 8l5-6"/>',
  "🎤": '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
  "💿": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r=".8" fill="currentColor"/><path d="M12 6a6 6 0 0 1 6 6"/>',
  "🎺": '<path d="M2 10h14l5-4v12l-5-4H2zM6 10V6M9 10V6M12 10V6M5 6h2M8 6h2M11 6h2M6 14v3h6v-3"/>',
  "🎻": '<path d="M10 7c-2 0-3.2 1-3.2 2.5 0 .8.6 1.3.6 2S5.5 13 5.5 15.2c0 2.2 2 3.8 4.5 3.8s4.5-1.6 4.5-3.8c0-2.2-1.9-3-1.9-3.7s.6-1.2.6-2C13.2 8 12 7 10 7zM10 7V2.5M8 12.5v2.5M12 12.5v2.5M8.5 17h3M20 2 17 22M21.3 4.5l-2.2 15"/><circle cx="10" cy="2.2" r=".6" fill="currentColor"/>',
  /* animals */
  "🐱": '<path d="M4 20V5l4.5 4h7L20 5v15z"/><circle cx="9" cy="13" r="1" fill="currentColor"/><circle cx="15" cy="13" r="1" fill="currentColor"/><path d="M11 16.5h2"/>',
  "🐶": '<path d="M7 5h10v9a5 5 0 0 1-10 0zM7 5 3 7v6l4 1M17 5l4 2v6l-4 1"/><circle cx="10" cy="10" r="1" fill="currentColor"/><circle cx="14" cy="10" r="1" fill="currentColor"/><circle cx="12" cy="14" r="1.4" fill="currentColor"/>',
  "🦊": '<path d="M3 4l5 5h8l5-5-2 9-7 7-7-7z"/><circle cx="9" cy="12.5" r="1" fill="currentColor"/><circle cx="15" cy="12.5" r="1" fill="currentColor"/><circle cx="12" cy="17" r="1" fill="currentColor"/>',
  "🐻": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="13" r="7"/><ellipse cx="12" cy="16" rx="2.5" ry="2"/><circle cx="9.5" cy="11" r="1" fill="currentColor"/><circle cx="14.5" cy="11" r="1" fill="currentColor"/>',
  "🦉": '<path d="M5 8v9a7 5 0 0 0 14 0V8l-3-4-4 2-4-2z"/><circle cx="9" cy="11" r="2.5"/><circle cx="15" cy="11" r="2.5"/><circle cx="9" cy="11" r=".8" fill="currentColor"/><circle cx="15" cy="11" r=".8" fill="currentColor"/><path d="M11 14.5h2l-1 1.5z"/>',
  "🐰": '<rect x="7.5" y="2" width="3" height="8" rx="1.5"/><rect x="13.5" y="2" width="3" height="8" rx="1.5"/><circle cx="12" cy="15" r="6"/><circle cx="9.5" cy="14" r="1" fill="currentColor"/><circle cx="14.5" cy="14" r="1" fill="currentColor"/><path d="M11 17h2"/>',
  "🐸": '<circle cx="7.5" cy="8" r="3"/><circle cx="16.5" cy="8" r="3"/><circle cx="7.5" cy="8" r="1" fill="currentColor"/><circle cx="16.5" cy="8" r="1" fill="currentColor"/><path d="M4.8 9.4C3.6 10.7 3 12.3 3 14c0 3.3 4 6 9 6s9-2.7 9-6c0-1.7-.6-3.3-1.8-4.6M8 15.5q4 2.5 8 0"/>',
  "🐧": '<path d="M12 3c-4 0-6 3.5-6 8v6c0 2.5 2.5 4 6 4s6-1.5 6-4v-6c0-4.5-2-8-6-8zM12 10c-2 0-3 1.8-3 4v3c0 1.4 1.3 2 3 2s3-.6 3-2v-3c0-2.2-1-4-3-4zM11 8h2l-1 1.2zM6 11.5 3 16M18 11.5l3 4.5M8.5 21.5h2.5M13 21.5h2.5"/><circle cx="10.5" cy="6.5" r=".8" fill="currentColor"/><circle cx="13.5" cy="6.5" r=".8" fill="currentColor"/>',
  /* nature and sky */
  "🌻": '<circle cx="12" cy="9" r="3"/><path d="M12 2v2M12 14v2M5 9h2M17 9h2M7 4l1.5 1.5M15.5 12.5 17 14M17 4l-1.5 1.5M8.5 12.5 7 14M12 16v6M12 19.5c1.5-2 3.5-2.5 5-2"/>',
  "⭐": '<path d="M12 3l2.6 6 6.4.3-5 4.1 1.7 6.6L12 16.3 6.3 20 8 13.4 3 9.3 9.4 9z"/>',
  "🌙": '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
  "⚡": '<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>',
  "🔥": '<path d="M12 22c4 0 7-2.8 7-7 0-3.5-2.5-6-4-8-.3 2-1.3 3-2.5 3.5C12.5 7 11 4 8 2c.5 3-1.5 5.5-2.8 7.5C4.5 11 5 12.5 5 15c0 4.2 3 7 7 7zM12 22c-1.7 0-3-1.2-3-3 0-1.5 1.5-2.5 2-4 1.5 1 4 2.5 4 4 0 1.8-1.3 3-3 3z"/>',
  "⛰": '<path d="M2 20 9 7l4 7 3-4 6 10zM7 10.7 9 12.5l2-1.5"/>',
  "🌊": '<path d="M3 12c0-4.5 3.5-8 8-8 2.8 0 4.5 1.7 4.5 3.8 0 1.6-1.2 2.7-2.7 2.7-1.1 0-1.8-.8-1.8-1.8M2 16c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 20c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>',
  /* things */
  "🚀": '<path d="M12 2c3 2.5 4.5 6 4.5 10v5h-9v-5C7.5 8 9 4.5 12 2zM7.5 13l-3 4v2h3M16.5 13l3 4v2h-3M10 20l2 2.5 2-2.5"/><circle cx="12" cy="9" r="1.5"/>',
  "🍕": '<path d="M4 6l8 16 8-16M3 5q9-4 18 0"/><circle cx="10" cy="9.5" r="1.3" fill="currentColor"/><circle cx="14.5" cy="10.5" r="1.3" fill="currentColor"/><circle cx="12" cy="15" r="1.3" fill="currentColor"/>',
  "⚽": '<circle cx="12" cy="12" r="9"/><path d="M12 8.5l3.3 2.4-1.3 3.9h-4l-1.3-3.9z" fill="currentColor"/><path d="M12 8.5V3M15.3 10.9l4.8-1.6M14 14.8l3 4.2M10 14.8l-3 4.2M8.7 10.9 3.9 9.3"/>',
  "☕": '<path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 10h1.5a2.5 2.5 0 0 1 0 5H17M3 22h16M8 3v3M12 3v3"/>',
  "🎮": '<path d="M6 7h12a4 4 0 0 1 4 4v4.5a2.5 2.5 0 0 1-4.5 1.5L16 15H8l-1.5 2A2.5 2.5 0 0 1 2 15.5V11a4 4 0 0 1 4-4zM7 10v4M5 12h4"/><circle cx="16" cy="11" r="1" fill="currentColor"/><circle cx="18" cy="13" r="1" fill="currentColor"/>',
  "👻": '<path d="M5 21V11a7 7 0 0 1 14 0v10l-2.3-2-2.3 2-2.4-2-2.3 2-2.4-2z"/><circle cx="9.5" cy="11" r="1.2" fill="currentColor"/><circle cx="14.5" cy="11" r="1.2" fill="currentColor"/>',
  "👑": '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-2 10H5zM5 21h14"/>',
};

/* the icons offered when picking, in the order above */
export const ICONS = Object.keys(PATHS);

const svg = inner => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

/* the icon for an emoji, or null when it isn't one of ours */
export function iconFor(e) {
  const d = PATHS[String(e || "").replace(/️/g, "")];   /* with or without "show as emoji" (U+FE0F), the same icon */
  return d ? svg(d) : null;
}

/* the padlock beside a name with a pass phrase */
export const LOCK = '<svg class="lockic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
