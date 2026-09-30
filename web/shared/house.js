/* What the server says about this device and the house: whether the admin is unlocked here, and the
   house's setup (its name and accent, which features are on, what groups are called, the wall's options). */
import { api } from "./api.js";

export let admin = false;                      /* read-only elsewhere: only syncAdmin changes it */
export let house = window.look.house();        /* the last /api/house (look.js kept it); read-only elsewhere */
export let fresh = false;                      /* true once the server answered: until then `house` is what this device remembers */
let houseRev = null;

const listeners = [];
/* fn() runs when the house's setup changed, or the admin was unlocked or locked here */
export function onHouse(fn) { listeners.push(fn); }

/* Follows state.admin; pages style by html[data-admin]. True if it changed. */
export function syncAdmin(flag) {
  flag = !!flag;
  if (flag === admin) return false;
  admin = flag;
  document.documentElement.toggleAttribute("data-admin", flag);
  window.look.apply();                         /* the admin keeps this device's own theme and accent when that is off */
  listeners.forEach(fn => fn());
  return true;
}

/* is this feature switched on? */
export const isOn = k => !house.off.includes(k);
/* ...or at least usable on this device: what is off is still the admin's */
export const feat = k => admin || isOn(k);
/* what groups are called here: one and many as the admin typed them, a and some for the middle of a sentence */
export const G = () => ({ one: house.groups.one, many: house.groups.many, a: house.groups.one.toLowerCase(), some: house.groups.many.toLowerCase() });

/* h: an answer from /api/house (or from the admin's routes that change it) */
export function setHouse(h) {
  window.look.store.set("tb_house", JSON.stringify(h));
  house = window.look.house();
  window.look.apply();
  listeners.forEach(fn => fn());
}

/* Reloads the setup when the server says it changed (state.houseRev) */
export async function syncHouse(rev) {
  if (rev === houseRev) return;
  const was = houseRev;
  houseRev = rev;                              /* now, so the next poll doesn't ask again meanwhile */
  try { const h = await api("api/house"); fresh = true; setHouse(h); } catch { houseRev = was; }
}
