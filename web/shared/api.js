/* Talking to the Tunebox server. */

let askName = async () => false, asking = null;

/* The page decides how to ask for a name (its "Who's listening?" picker). It resolves true once one is picked. */
export function setNameAsker(fn) { askName = fn; }

/* GET without a body; POST (or `method`) with a JSON body. Adding songs needs a name: on a 401 the
   page asks for one, then the request is tried once more. */
export async function api(path, body, method, retried = false) {
  const opts = body !== undefined
    ? { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method: method || "GET" };
  const r = await fetch(path, opts);
  if (r.status === 401 && !retried) {
    asking ||= askName().finally(() => asking = null);   /* two taps before a name is picked share one question */
    if (await asking) return api(path, body, method, true);
    throw new Error(JSON.stringify({ detail: "Pick your name first" }));
  }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/* The server's readable message from a failed api() call */
export const errText = e => { try { return JSON.parse(e.message).detail; } catch { return e.message; } };
