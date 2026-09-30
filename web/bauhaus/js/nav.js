/* Which page the main view shows. Every page change bumps `seq`, so a page that finishes loading after
   you moved on doesn't take over. */
import { $, $$ } from "../../shared/dom.js";

export let view = "home";                      /* home, lists, history, explore, local, stats or search */
export let seq = 0;
export let back = () => {};                    /* where Back on an album / playlist / artist page goes */

/* album / playlist / artist pages opened from one another (an album's artist, a song's album...):
   Back walks through them before it leaves for `back` */
let here = null;
const trail = [];
export function visit(page, goingBack = false) { if (here && !goingBack) trail.push(here); here = page; }
export const previous = () => trail.pop();

export function setNav(v) {
  view = v; seq++; here = null; trail.length = 0;
  $$("#nav button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  if (v !== "search") $("#tabs").hidden = true;
}
export const bump = () => ++seq;
export function setBack(fn) { back = fn; }
