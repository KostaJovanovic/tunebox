/* What the server says about this device and the house: for now, whether the admin is unlocked here. */

export let admin = false;                      /* read-only elsewhere: only syncAdmin changes it */

/* Follows state.admin; pages style by html[data-admin]. True if it changed. */
export function syncAdmin(flag) {
  flag = !!flag;
  if (flag === admin) return false;
  admin = flag;
  document.documentElement.toggleAttribute("data-admin", flag);
  return true;
}
