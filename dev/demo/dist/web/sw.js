/* Tunebox's service worker: it makes the page installable as an app. Tunebox needs its server
   anyway, so nothing is cached; when the server can't be reached, a page says so. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tunebox</title>
     <body style="margin:0;display:grid;place-items:center;height:100vh;background:#111;color:#EDEAE3;font:16px system-ui;text-align:center">
     <div><h1 style="font-size:22px">Tunebox can't be reached</h1><p>Is this device on the house network, and is the server on?</p>
     <p><button onclick="location.reload()" style="font:inherit;padding:10px 18px">Try again</button></p></div>`,
    { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
