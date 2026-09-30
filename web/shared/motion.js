/* Movement that behaves like a thing, not like a film: a spring starts from where the thing is now and
   carries the finger's speed, so a drag and what follows it are one movement, and it can be caught and
   turned around at any moment.

     spring(set, {damping, response})   damping 1 settles without overshoot, .8 bounces a little (for
                                        something that was thrown); response is seconds, lower is snappier
     tracker()                          how fast the pointer has been moving, px/s
     project(v)                         how far a flick at v px/s would carry
     rubberband(over, size)             the give past an edge: the further, the less it follows
     shift(el)                          where an element is on screen right now, mid-transition or not
     letGo(el)                          the spring is done with it */

const reduce = matchMedia("(prefers-reduced-motion: reduce)");
/* reduced motion, or performance mode (html[data-lite], look.js): things still follow the finger, but
   nothing travels on its own */
export const calm = () => reduce.matches || document.documentElement.hasAttribute("data-lite");

export function spring(set, { damping = 1, response = .35 } = {}) {
  let x = 0, v = 0, goal = 0, k = 0, c = 0, raf = 0, last = 0, rest = null;

  function land() {
    cancelAnimationFrame(raf); raf = 0; x = goal; v = 0; set(x);
    const fn = rest; rest = null; fn?.();
  }
  function frame(now) {
    let dt = Math.min(.034, (now - last) / 1000); last = now;      /* a dropped frame mustn't throw it */
    for (; dt > 0; dt -= .004) { const h = Math.min(.004, dt); v += (k * (goal - x) - c * v) * h; x += v * h; }
    if (Math.abs(goal - x) < .5 && Math.abs(v) < 10) return land();
    set(x); raf = requestAnimationFrame(frame);
  }

  return {
    get value() { return x; },
    get moving() { return !!raf; },
    /* put it somewhere at once: following a finger, or catching it mid-flight */
    jump(to) { cancelAnimationFrame(raf); raf = 0; rest = null; x = goal = to; v = 0; set(x); },
    /* head for `to` from wherever it is; velocity in px/s (the finger's, on release); then() runs once it rests */
    to(to, { velocity, damping: z = damping, response: r = response, then } = {}) {
      goal = to; rest = then || null;
      k = (2 * Math.PI / r) ** 2; c = 4 * Math.PI * z / r;
      if (velocity !== undefined) v = velocity;
      if (calm()) return land();
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
    },
  };
}

export function tracker() {
  const pts = [];
  return {
    add(e) {
      const t = performance.now();
      pts.push({ x: e.clientX, y: e.clientY, t });
      while (pts.length > 2 && t - pts[0].t > 100) pts.shift();
    },
    /* over the last tenth of a second; a finger that stopped before it lifted has none */
    velocity() {
      const a = pts[0], b = pts[pts.length - 1];
      if (!a || a === b || performance.now() - b.t > 80) return { x: 0, y: 0 };
      const dt = Math.max(.001, (b.t - a.t) / 1000);
      return { x: (b.x - a.x) / dt, y: (b.y - a.y) / dt };
    },
  };
}

/* the same slowing-down a scroll has: .998 is a normal flick, .99 stops sooner */
export const project = (v, rate = .998) => (v / 1000) * rate / (1 - rate);

export const rubberband = (over, size, give = .55) => (over * size * give) / (size + give * Math.abs(over));

export function shift(el) {
  const m = new DOMMatrixReadOnly(getComputedStyle(el).transform);
  return { x: m.m41, y: m.m42 };
}

/* Hands an element a spring has been moving (class "dragging", inline transform) back to its stylesheet,
   without it animating from where the spring left it */
export function letGo(el) {
  el.style.transition = "none"; el.classList.remove("dragging"); el.style.transform = "";
  void el.offsetWidth;
  el.style.transition = "";
}

/* iOS only shows :active on a page that listens for touches, and a press must show the moment it lands */
document.addEventListener("touchstart", () => {}, { passive: true });
