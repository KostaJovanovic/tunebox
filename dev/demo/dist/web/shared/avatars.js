/* The icons a name can wear: small full-colour stickers on a 24-unit grid (flat fills, one dark outline),
   keyed by the emoji that is saved with the person (people.json keeps the emoji, so the CLI and the
   terminal interface still show something). An emoji not drawn here (set from the command line) is shown as it is.
   The outline comes from svg() below; a shape that must not have one says stroke="none". */
const PATHS = {
  /* music */
  "🎸": '<path d="M10.8 14.8 19.8 5.8 18.2 4.2 9.2 13.2z" fill="#9A6332"/><path d="M18.4 3.6 20.4 1.6 22.4 3.6 20.4 5.6z" fill="#5A3418"/>'
      + '<path d="M9 11.6A3.5 3.5 0 1 1 12.9 15.5 5 5 0 1 1 9 11.6z" fill="#E8552B"/><circle cx="9.3" cy="15.2" r="1.5" fill="#26221F" stroke="none"/><path d="M5.6 18.4l2 2" stroke-width="1.2"/>',
  "🎧": '<path d="M3.5 15v-2a8.5 8.5 0 0 1 17 0v2h-2v-2a6.5 6.5 0 0 0-13 0v2z" fill="#8A93A3"/>'
      + '<rect x="2.5" y="12.5" width="5" height="8.5" rx="2" fill="#E8456B"/><rect x="16.5" y="12.5" width="5" height="8.5" rx="2" fill="#E8456B"/>',
  "🎹": '<rect x="2.5" y="4.5" width="19" height="15" rx="1.5" fill="#FFFFFF"/><path d="M2.5 9V6a1.5 1.5 0 0 1 1.5-1.5h16A1.5 1.5 0 0 1 21.5 6v3z" fill="#D7263D"/>'
      + '<path d="M7.3 9v10.5M12 9v10.5M16.7 9v10.5" stroke-width="1"/><path d="M5.9 9h2.8v5.5H5.9zM10.6 9h2.8v5.5h-2.8zM15.3 9h2.8v5.5h-2.8z" fill="#26221F" stroke="none"/>',
  "🥁": '<path d="M8.5 9 4.5 3M15.5 9l4-6" stroke-width="3"/><path d="M8.5 9 4.5 3M15.5 9l4-6" stroke="#F2D29B" stroke-width="1.4"/>'
      + '<path d="M3.5 11v6c0 1.9 3.8 3.5 8.5 3.5s8.5-1.6 8.5-3.5v-6z" fill="#E53935"/><path d="M3.5 16.6c0 1.9 3.8 3.5 8.5 3.5s8.5-1.6 8.5-3.5" fill="none"/>'
      + '<ellipse cx="12" cy="11" rx="8.5" ry="3.2" fill="#F7F1E3"/>',
  "🎤": '<path d="M9.6 11.5 10.6 21.5h2.8l1-10z" fill="#5E6675"/><circle cx="12" cy="7" r="5" fill="#C3CAD6"/>'
      + '<path d="M8.5 5.5h7M7.8 8.2h8.4M10.5 2.6v8.8M13.5 2.6v8.8" stroke="#8E97A6" stroke-width=".9"/><circle cx="12" cy="7" r="5" fill="none"/>'
      + '<rect x="9" y="11" width="6" height="2" rx=".7" fill="#F2C230"/>',
  "💿": '<circle cx="12" cy="12" r="9.5" fill="#D9DEE7"/><path d="M12 8.8V2.5a9.5 9.5 0 0 1 8.2 4.7l-5.4 3.2A3.2 3.2 0 0 0 12 8.8z" fill="#9EDCF2" stroke="none"/>'
      + '<path d="M12 15.2v6.3a9.5 9.5 0 0 1-8.2-4.7l5.4-3.2a3.2 3.2 0 0 0 2.8 1.6z" fill="#F7B4D0" stroke="none"/><circle cx="12" cy="12" r="9.5" fill="none"/>'
      + '<circle cx="12" cy="12" r="3.2" fill="#F5F6F8"/><circle cx="12" cy="12" r="1.2" fill="#26221F" stroke="none"/>',
  "🎺": '<path d="M5.5 14.5v3h7v-3" fill="none" stroke-width="3"/><path d="M5.5 14.5v3h7v-3" fill="none" stroke="#F2B822" stroke-width="1.2"/>'
      + '<rect x="5" y="6.5" width="2" height="4" fill="#E0A516"/><rect x="8.5" y="6.5" width="2" height="4" fill="#E0A516"/><rect x="12" y="6.5" width="2" height="4" fill="#E0A516"/>'
      + '<path d="M1.5 10H13c3 0 5-2.5 8-4.5v13c-3-2-5-4.5-8-4.5H1.5z" fill="#F7C531"/><ellipse cx="21" cy="12" rx="1.2" ry="6.5" fill="#FFE58A"/>',
  "🎻": '<path d="M20.5 2 17.5 22" stroke-width="3"/><path d="M20.5 2 17.5 22" stroke="#E9D3A8" stroke-width="1.2"/>'
      + '<rect x="10.9" y="2.5" width="2.2" height="9" fill="#4A2E18"/><circle cx="12" cy="2.6" r="1.3" fill="#4A2E18"/>'
      + '<path d="M12 8c-3.5 0-4.5 1.5-4.5 3 0 1.2 1.1 1.6 1.1 2.5S7 15 7 17.2c0 2.6 2.2 4.3 5 4.3s5-1.7 5-4.3c0-2.2-1.6-2.8-1.6-3.7s1.1-1.3 1.1-2.5c0-1.5-1-3-4.5-3z" fill="#D2691E"/>'
      + '<rect x="11" y="10.5" width="2" height="6" rx=".8" fill="#4A2E18"/><path d="M9.3 13.5v3M14.7 13.5v3" stroke-width="1"/><rect x="10.8" y="17.3" width="2.4" height="3.2" rx=".8" fill="#4A2E18"/>',
  /* animals */
  "🐱": '<path d="M4.5 11 5 3.5l4.5 3.5q2.5-.7 5 0L19 3.5l.5 7.5c1 6-2.5 9.5-7.5 9.5S3.5 17 4.5 11z" fill="#A9B3C1"/>'
      + '<path d="M6.2 6.2 6.4 9l2-1.4zM17.8 6.2 17.6 9l-2-1.4z" fill="#F4A3B5" stroke="none"/><ellipse cx="9" cy="13" rx="1.1" ry="1.5" fill="#26221F" stroke="none"/><ellipse cx="15" cy="13" rx="1.1" ry="1.5" fill="#26221F" stroke="none"/>'
      + '<path d="M10.9 15.6h2.2L12 16.9z" fill="#F07F9A" stroke-width="1"/>',
  "🐶": '<path d="M12 4.5c-4 0-6 2.5-6 6.5v3c0 4 2.7 6.5 6 6.5s6-2.5 6-6.5v-3c0-4-2-6.5-6-6.5z" fill="#DDA466"/>'
      + '<path d="M7.5 5C4 5 2.4 7.5 2.9 12c.3 2 2 2.6 3.6 1.2L8.5 6zM16.5 5C20 5 21.6 7.5 21.1 12c-.3 2-2 2.6-3.6 1.2L15.5 6z" fill="#7A4A26"/>'
      + '<ellipse cx="12" cy="16.4" rx="3.7" ry="3" fill="#F7E6C8"/><ellipse cx="12" cy="14.6" rx="1.5" ry="1.1" fill="#26221F" stroke="none"/>'
      + '<circle cx="9.5" cy="11" r="1" fill="#26221F" stroke="none"/><circle cx="14.5" cy="11" r="1" fill="#26221F" stroke="none"/>',
  "🦊": '<path d="M2.5 3.5 8 8.5h8l5.5-5L20 12l-8 8.5L4 12z" fill="#F07A22"/><path d="M4.4 6.2 7.2 8.7 5 9.8zM19.6 6.2l-2.8 2.5 2.2 1.1z" fill="#5A2D12" stroke="none"/>'
      + '<path d="M4.6 12.6c2.9-.3 5.3.6 7.4 2.6 2.1-2 4.5-2.9 7.4-2.6L12 20.5z" fill="#FFFFFF"/><ellipse cx="12" cy="19.3" rx="1.3" ry="1" fill="#26221F" stroke="none"/>'
      + '<circle cx="9" cy="11.8" r="1" fill="#26221F" stroke="none"/><circle cx="15" cy="11.8" r="1" fill="#26221F" stroke="none"/>',
  "🐻": '<circle cx="6" cy="6.5" r="2.8" fill="#9A5B2E"/><circle cx="18" cy="6.5" r="2.8" fill="#9A5B2E"/><circle cx="6" cy="6.5" r="1.2" fill="#E3B98A" stroke="none"/><circle cx="18" cy="6.5" r="1.2" fill="#E3B98A" stroke="none"/>'
      + '<circle cx="12" cy="13.5" r="7.5" fill="#9A5B2E"/><ellipse cx="12" cy="16.5" rx="3" ry="2.4" fill="#E3B98A"/><ellipse cx="12" cy="15.4" rx="1.2" ry=".85" fill="#26221F" stroke="none"/>'
      + '<circle cx="9.3" cy="11.8" r="1" fill="#26221F" stroke="none"/><circle cx="14.7" cy="11.8" r="1" fill="#26221F" stroke="none"/>',
  "🦉": '<path d="M5 8v9a7 5 0 0 0 14 0V8l-3-4.5-4 2.3-4-2.3z" fill="#8A5A3C"/><ellipse cx="12" cy="17.6" rx="4.2" ry="3.4" fill="#EBCB9C"/>'
      + '<circle cx="9" cy="10.8" r="2.8" fill="#FFFFFF"/><circle cx="15" cy="10.8" r="2.8" fill="#FFFFFF"/><circle cx="9" cy="10.8" r="1.2" fill="#26221F" stroke="none"/><circle cx="15" cy="10.8" r="1.2" fill="#26221F" stroke="none"/>'
      + '<path d="M10.8 13.6h2.4L12 15.6z" fill="#F5A623" stroke-width="1"/>',
  "🐰": '<rect x="7.2" y="1.8" width="3.4" height="9" rx="1.7" fill="#F7F4EF"/><rect x="13.4" y="1.8" width="3.4" height="9" rx="1.7" fill="#F7F4EF"/>'
      + '<rect x="8.3" y="3.3" width="1.2" height="5.5" rx=".6" fill="#F4A3B5" stroke="none"/><rect x="14.5" y="3.3" width="1.2" height="5.5" rx=".6" fill="#F4A3B5" stroke="none"/>'
      + '<circle cx="12" cy="15" r="6.3" fill="#F7F4EF"/><circle cx="9.6" cy="14" r="1" fill="#26221F" stroke="none"/><circle cx="14.4" cy="14" r="1" fill="#26221F" stroke="none"/>'
      + '<path d="M11 16.2h2l-1 1.1z" fill="#F07F9A" stroke-width="1"/>',
  "🐸": '<ellipse cx="12" cy="14.5" rx="9.3" ry="6.3" fill="#6CC04A"/><circle cx="7.5" cy="8" r="3.3" fill="#6CC04A"/><circle cx="16.5" cy="8" r="3.3" fill="#6CC04A"/>'
      + '<circle cx="7.5" cy="8" r="1.9" fill="#FFFFFF" stroke="none"/><circle cx="16.5" cy="8" r="1.9" fill="#FFFFFF" stroke="none"/><circle cx="7.5" cy="8" r="1" fill="#26221F" stroke="none"/><circle cx="16.5" cy="8" r="1" fill="#26221F" stroke="none"/>'
      + '<path d="M7.5 15.5q4.5 3.2 9 0" fill="none"/><ellipse cx="5.6" cy="14.3" rx="1.3" ry=".8" fill="#F28CA0" stroke="none"/><ellipse cx="18.4" cy="14.3" rx="1.3" ry=".8" fill="#F28CA0" stroke="none"/>',
  "🐧": '<ellipse cx="9.3" cy="21" rx="2.2" ry="1.1" fill="#F5A623"/><ellipse cx="14.7" cy="21" rx="2.2" ry="1.1" fill="#F5A623"/>'
      + '<path d="M6 10.5 2.8 16.5l3.2-.4zM18 10.5l3.2 6-3.2-.4z" fill="#3B4763"/>'
      + '<path d="M12 2.5c-4.2 0-6.5 3.5-6.5 8.5v5.5c0 3 2.8 4.5 6.5 4.5s6.5-1.5 6.5-4.5V11c0-5-2.3-8.5-6.5-8.5z" fill="#3B4763"/>'
      + '<path d="M12 8c-1.5-2-4.2-1.7-4.2 1.5v7c0 2.2 2 3.3 4.2 3.3s4.2-1.1 4.2-3.3v-7C16.2 6.3 13.5 6 12 8z" fill="#FFFFFF" stroke="none"/>'
      + '<circle cx="10" cy="9.4" r=".95" fill="#26221F" stroke="none"/><circle cx="14" cy="9.4" r=".95" fill="#26221F" stroke="none"/><path d="M10.7 11h2.6L12 12.7z" fill="#F5A623" stroke-width="1"/>',
  /* nature and sky */
  "🌻": '<path d="M12 13v9" stroke-width="3.2"/><path d="M12 13v9" stroke="#3E9B3E" stroke-width="1.4"/><path d="M12.5 18.5c2-2.6 5-3 7-2-1.5 2.6-4.3 3.2-7 2z" fill="#4CAF50"/>'
      + '<g fill="#FFC928"><ellipse cx="12" cy="4.6" rx="2" ry="3.1"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(45 12 9.5)"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(90 12 9.5)"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(135 12 9.5)"/>'
      + '<ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(180 12 9.5)"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(225 12 9.5)"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(270 12 9.5)"/><ellipse cx="12" cy="4.6" rx="2" ry="3.1" transform="rotate(315 12 9.5)"/></g>'
      + '<circle cx="12" cy="9.5" r="3.5" fill="#7A4A1E"/>',
  "⭐": '<path d="M12 2.5l2.8 6.2 6.7.5-5.2 4.3 1.7 6.7L12 16.5l-6 3.7 1.7-6.7-5.2-4.3 6.7-.5z" fill="#FFB52E"/><path d="M9.6 10.4l1.4-.1.6-1.4" fill="none" stroke="#FFF1B8" stroke-width="1.1"/>',
  "🌙": '<path d="M20.5 14.5A9 9 0 1 1 9.5 3.5a7.3 7.3 0 0 0 11 11z" fill="#FFEFA8"/><circle cx="9" cy="14" r="1.2" fill="#EBCB6A" stroke="none"/><circle cx="12.5" cy="17.5" r=".9" fill="#EBCB6A" stroke="none"/>',
  "⚡": '<path d="M13.5 1.5 3.5 14h7.5l-1.5 8.5L20.5 9H13z" fill="#FFE352"/>',
  "🔥": '<path d="M12 22c4 0 7-2.8 7-7 0-3.5-2.5-6-4-8-.3 2-1.3 3-2.5 3.5C12.5 7 11 4 8 2c.5 3-1.5 5.5-2.8 7.5C4.5 11 5 12.5 5 15c0 4.2 3 7 7 7z" fill="#F4511E"/>'
      + '<path d="M12 22c-1.9 0-3.3-1.3-3.3-3.2 0-1.7 1.6-2.8 2.3-4.6 1.6 1.1 4.3 2.8 4.3 4.6 0 1.9-1.4 3.2-3.3 3.2z" fill="#FFC93C"/>',
  "⛰": '<path d="M1.5 20.5 9.5 6.5l4.5 7.5 2.5-3.5 6 10z" fill="#8391A8"/><path d="M9.5 6.5l2.8 4.7-1.5-.9-1.3 1.2-1.3-1.2-1.4.9z" fill="#FFFFFF" stroke-width="1"/>'
      + '<path d="M1.5 20.5c4-4.5 10-5 14 0z" fill="#4FA85A"/>',
  "🌊": '<path d="M2 21v-7C2 7.5 6.5 3 12 3c4 0 7 2.4 7 5.6 0 2.3-1.7 4-3.9 4-1.7 0-3.1-1.2-3.1-2.8 0-1 .5-1.7 1.2-2C10.2 7 7.5 9.4 7.5 13.2c0 3.2 2.4 5.3 5.5 5.3H22V21z" fill="#2F80ED"/>'
      + '<path d="M12 3c4 0 7 2.4 7 5.6 0 1.1-.4 2.1-1.1 2.8.1-2.6-2-4.6-5.2-4.6C8.6 6.8 6 9.6 6 13.5V21H2v-7C2 7.5 6.5 3 12 3z" fill="#7CC4FA" stroke="none"/>'
      + '<path d="M2 21v-7C2 7.5 6.5 3 12 3c4 0 7 2.4 7 5.6 0 2.3-1.7 4-3.9 4-1.7 0-3.1-1.2-3.1-2.8 0-1 .5-1.7 1.2-2C10.2 7 7.5 9.4 7.5 13.2c0 3.2 2.4 5.3 5.5 5.3H22V21z" fill="none"/>',
  /* things */
  "🚀": '<path d="M9.5 17h5l-1 3-1.5 2.5-1.5-2.5z" fill="#FF9F1C"/><path d="M7.5 12 4.5 16.5V19.5h3zM16.5 12l3 4.5v3h-3z" fill="#E53935"/>'
      + '<path d="M12 1.8c3 2.5 4.5 6 4.5 10.2v5.5h-9V12C7.5 7.8 9 4.3 12 1.8z" fill="#F1F3F7"/><path d="M12 1.8c1.6 1.3 2.7 2.8 3.4 4.7H8.6c.7-1.9 1.8-3.4 3.4-4.7z" fill="#E53935"/>'
      + '<circle cx="12" cy="10" r="2" fill="#4FB3E8"/>',
  "🍕": '<path d="M3.8 6.2 12 22l8.2-15.8z" fill="#FFD166"/><path d="M2.8 5.2Q12 .8 21.2 5.2l-1 2.4Q12 3.6 3.8 7.6z" fill="#D98E3A"/>'
      + '<circle cx="9.6" cy="9.6" r="1.6" fill="#D7263D" stroke-width="1"/><circle cx="14.6" cy="10.4" r="1.6" fill="#D7263D" stroke-width="1"/><circle cx="12" cy="15" r="1.6" fill="#D7263D" stroke-width="1"/>',
  "⚽": '<circle cx="12" cy="12" r="9.5" fill="#FFFFFF"/><path d="M12 8.3l3.4 2.5-1.3 4h-4.2l-1.3-4z" fill="#26221F"/>'
      + '<path d="M12 8.3V2.5M15.4 10.8l5.3-1.8M14.1 14.8l3.3 4.6M9.9 14.8l-3.3 4.6M8.6 10.8 3.3 9" fill="none" stroke-width="1.1"/>'
      + '<path d="M9.6 2.8 12 4.4l2.4-1.6A9.5 9.5 0 0 0 9.6 2.8zM21.3 10.6l-1.6 2.6 1 2.6a9.5 9.5 0 0 0 .6-5.2zM2.7 10.6l1.6 2.6-1 2.6a9.5 9.5 0 0 1-.6-5.2z" fill="#26221F" stroke="none"/>',
  "☕": '<path d="M9 2.8c-1 1 1 2 0 3.2M13 2.8c-1 1 1 2 0 3.2" fill="none" stroke-width="2.6"/><path d="M9 2.8c-1 1 1 2 0 3.2M13 2.8c-1 1 1 2 0 3.2" fill="none" stroke="#FFFFFF" stroke-width="1"/>'
      + '<ellipse cx="11" cy="20.5" rx="8.5" ry="1.7" fill="#C9D1DC"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke-width="3"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke="#FFFFFF" stroke-width="1.2"/>'
      + '<path d="M4 8.5h13.5V14a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z" fill="#FFFFFF"/><path d="M4 8.5h13.5v2H4z" fill="#6F4E37"/>',
  "🎮": '<path d="M6 6.5h12a4.5 4.5 0 0 1 4.5 4.5v4.5a2.8 2.8 0 0 1-5 1.7L16 15.5H8l-1.5 1.7a2.8 2.8 0 0 1-5-1.7V11A4.5 4.5 0 0 1 6 6.5z" fill="#7B6CF0"/>'
      + '<path d="M6.2 9.6h1.6v1.6h1.6v1.6H7.8v1.6H6.2v-1.6H4.6v-1.6h1.6z" fill="#26221F" stroke="none"/>'
      + '<circle cx="16" cy="10.6" r="1.25" fill="#FF5A5F" stroke-width="1"/><circle cx="18.6" cy="13.2" r="1.25" fill="#FFD23F" stroke-width="1"/>',
  "👻": '<path d="M4.5 21.5V11a7.5 7.5 0 0 1 15 0v10.5l-2.5-2-2.5 2-2.5-2-2.5 2-2.5-2z" fill="#F7F7FB"/>'
      + '<ellipse cx="9.5" cy="11" rx="1.3" ry="1.8" fill="#26221F" stroke="none"/><ellipse cx="14.5" cy="11" rx="1.3" ry="1.8" fill="#26221F" stroke="none"/><ellipse cx="12" cy="15.2" rx="1" ry="1.3" fill="#26221F" stroke="none"/>',
  "👑": '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-2 9.5H5z" fill="#F6C343"/><path d="M5 17.5h14V21H5z" fill="#E0A21E"/>'
      + '<circle cx="3" cy="8" r="1.5" fill="#E53935"/><circle cx="12" cy="5" r="1.5" fill="#1E88E5"/><circle cx="21" cy="8" r="1.5" fill="#E53935"/><circle cx="12" cy="19.2" r="1" fill="#1E88E5" stroke="none"/>',
};

/* the icons offered when picking, in the order above */
export const ICONS = Object.keys(PATHS);

/* the outline every shape shares; each shape brings its own fill */
const svg = inner => `<svg viewBox="0 0 24 24" aria-hidden="true"><g stroke="#26221F" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${inner}</g></svg>`;

/* the icon for an emoji, or null when it isn't one of ours */
export function iconFor(e) {
  const d = PATHS[String(e || "").replace(/️/g, "")];   /* with or without "show as emoji" (U+FE0F), the same icon */
  return d ? svg(d) : null;
}

/* the padlock beside a name with a pass phrase */
export const LOCK = '<svg class="lockic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
