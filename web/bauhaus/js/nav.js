/* Which page the main view shows. Every page change bumps `seq`, so a page that finishes loading after
   you moved on doesn't take over. */
import { $, $$ } from "../../shared/dom.js";

export let view = "home";                      /* home, lists, history, explore or search */
export let seq = 0;
export let back = () => {};                    /* where Back on an album / playlist / artist page goes */

export function setNav(v) {
  view = v; seq++;
  $$("#nav button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  if (v !== "search") $("#tabs").hidden = true;
}
export const bump = () => ++seq;
export function setBack(fn) { back = fn; }
