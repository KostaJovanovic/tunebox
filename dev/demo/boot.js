/* Tunebox demo: the server is the service worker (sw.js). Until it looks after this page nothing else may
   load, or the first requests would go to a static host that has no api/. Then every request says who is
   listening (the page keeps it in the tb_who cookie, which a worker can't read). */
(function () {
  const sw = navigator.serviceWorker;
  const say = text => { window.stop(); document.documentElement.innerHTML = `<body style="margin:0;display:grid;place-items:center;height:100vh;background:#111;color:#EDEAE3;font:16px system-ui;text-align:center;padding:24px">${text}</body>`; };
  if (!sw) return say("This demo needs a browser with service workers, and not a private window.");
  if (!sw.controller) {
    const tries = +sessionStorage.getItem("tb_demo_boot") || 0;
    if (tries > 2) return say("The demo couldn't start here. Try another browser, or a normal (not private) window.");
    sessionStorage.setItem("tb_demo_boot", tries + 1);
    say("Starting Tunebox…");
    sw.register("sw.js").then(() => sw.ready).then(() => location.reload(), () => say("The demo couldn't start here. Try another browser, or a normal (not private) window."));
    return;
  }
  sessionStorage.removeItem("tb_demo_boot");
  const who = () => (document.cookie.match(/(?:^|; )tb_who=([^;]*)/) || [])[1] || "";
  const fetch0 = window.fetch;
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    headers.set("X-Demo-Who", who());
    return fetch0(input, { ...init, headers });
  };
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) { this.setRequestHeader("X-Demo-Who", who()); return send.call(this, body); };
})();
