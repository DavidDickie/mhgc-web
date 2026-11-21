// The galaxy map: a canvas over the torus (100x100, 75x75 for 8/9-empire games, 50x50 for 4) in the
// empire's relative coordinates (home at the centre: 50,50 or 37,37; y up as in the old gcviewer).  Pan by dragging or with Shift+arrows, zoom with the wheel
// or +/-; arrow keys move a keyboard cursor; click / Enter selects a square; right-click (or M)
// moves the focused fleet or ship there.
//
// Squares are tinted three ways: inside a scan now, scanned on an earlier turn (the empire's
// scan history, view.scan_history), never scanned.  Systems are sized by habitability where the
// empire knows it (own, scanned, remembered); an unknown rating is a small diamond.  MR/AR are
// pips at the lower right; own systems show their population in a badge at the upper left.
// Fleets (yours, the ones this turn's draft forms, and scanned foreign ones) are hexagons beside
// the system; the selected fleet or ship gets a pulsing ring (a DOM overlay) or, off screen, an
// edge arrow, and a rubber band to the pointer while you pick its destination (2026-11-16).
"use strict";

// tints (r, g, b, alpha 0-255) for the coverage image, over the map's near-black background
// (about #08101e).  Composited there: never ~ #04070d (darkest), scanned before ~ #2a323f (a plain
// mid-dark grey, clearly lighter than never), inside a scan now ~ #21457f (blue, brighter than
// before).  The explored region (now or before) also gets a thin light outline (EDGE).
const TINT = { now: [70, 140, 255, 110], past: [150, 156, 168, 62], never: [0, 0, 0, 150] };
// the minimap is small and darker (#050a14): stronger tints so the three states still read
const MINI_ALPHA = { now: 190, past: 125, never: 0 };
const EDGE = "rgba(178, 192, 214, 0.55)";
const MAP_BG = [8, 16, 30];
// a tint as it looks on the map (opaque), for the legend swatches
const onMap = ([r, g, b, a]) => { const f = a / 255; return `rgb(${[r, g, b].map((c, i) => Math.round(MAP_BG[i] * (1 - f) + c * f)).join(",")})`; };
// radius factors by habitability (index = HAB value; 0 = unknown, drawn as a diamond)
const HAB_SIZE = [0.5, 0.5, 0.6, 0.72, 0.86, 1.0];
const PIP = { MR: "#ff9f43", AR: "#6fdc8c" };
// decode the base64 bitmask (bit y*B+x, LSB first; B = the board side) into a grid indexed x*B+y
function decodeMask(b64) {
  const B = BOARD, g = new Uint8Array(B * B);
  if (!b64) return g;
  const bin = atob(b64);
  for (let i = 0; i < bin.length; i++) {
    const c = bin.charCodeAt(i);
    if (!c) continue;
    for (let b = 0; b < 8; b++) if (c & (1 << b)) {
      const n = i * 8 + b;
      if (n < B * B) g[(n % B) * B + Math.floor(n / B)] = 1;
    }
  }
  return g;
}
import { S, BOARD, HOME, REL, relColor, relationOf, systemColor, systemOwnerLabel, wrap, axisDelta, pathTo, fleetSpeed, emit, shipClass, xy, el, clear, fmt, habValue, habText, habAsOf, HAB_LABEL } from "./core.js";
import { buildIndex, plannedMoves, key, ownFleets, findOwnFleet, effectiveFleet, draftShipCount } from "./world.js";

// the selected-unit highlight: a colour no relation uses, with a white core (DOM overlay, so the
// pulse is a CSS animation and the canvas is not redrawn every frame; prefers-reduced-motion
// gets a steady thick ring instead, style.css)
export const HILITE = "#ff4fe3";

const LAYERS = [
  ["grid", "Grid and coordinates", true],
  ["labels", "System names", true],
  ["scan", "Scan coverage (now)", true],
  ["history", "Scan history (scanned before / never)", true],
  ["memory", "Map memory (older sightings)", true],
  ["paths", "Movement orders", true],
  ["foreign", "Scanned foreign ships", true],
  ["combat", "Battles this turn", true],
];

export class GalaxyMap {
  constructor(canvas, minimap, tip) {
    this.c = canvas; this.ctx = canvas.getContext("2d");
    this.mm = minimap; this.mctx = minimap.getContext("2d");
    this.tip = tip;
    this.cx = HOME; this.cy = HOME; this.scale = 14;
    this.cursor = { x: HOME, y: HOME };
    this.hover = null;
    this.layers = Object.fromEntries(LAYERS.map(([k, , d]) => [k, d]));
    try { Object.assign(this.layers, JSON.parse(localStorage.getItem("mhgcLayers")) || {}); } catch { /* defaults */ }
    this.idx = new Map();
    this.planned = new Map();
    this.cover = null;
    this.pick = null;           // {resolve, label, from?}
    this.hits = [];             // fleet glyphs drawn last frame: {X, Y, r, x, y, focus}
    this.glyphOff = new Map();
    this.mouse = null;          // pointer position over the canvas (CSS px), for the rubber band
    this.dirty = true;
    // the selected unit's ring and, when it is off screen, an edge arrow pointing to it
    const pane = canvas.parentElement;
    this.ring = el("div", { class: "unit-ring", id: "unitRing", "aria-hidden": "true", hidden: true }, el("div", { class: "unit-ring-pulse" }));
    this.edge = el("button", { type: "button", class: "edge-arrow", id: "edgeArrow", hidden: true, title: "The selected unit is off the map: click to centre on it",
      onclick: () => { const u = this.highlightUnit(); if (u) { this.ensureVisible(u.x, u.y); this.c.focus(); } } },
      el("span", { class: "edge-arrow-tip", "aria-hidden": "true" }, "➤"), el("span", { class: "edge-arrow-label" }));
    pane.append(this.ring, this.edge);
    this.bind();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    const loop = () => { if (this.dirty) { this.dirty = false; this.draw(); this.drawMini(); } requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ data
  refresh() {
    this.idx = buildIndex();
    this.planned = plannedMoves();
    this.cover = this.coverage();
    this.dirty = true;
  }
  coverage() {
    const v = S.view;
    if (!v) return null;
    const B = BOARD, g = new Uint8Array(B * B);
    const mark = (x, y, r) => {
      for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++) g[wrap(x + dx) * B + wrap(y + dy)] = 1;
    };
    for (const s of v.systems) if (s.scan_range) mark(s.x, s.y, s.scan_range);   // populated (engine)
    for (const s of v.ships) mark(s.x, s.y, s.scan || 0);
    const hist = decodeMask(v.scan_history && v.scan_history.data);
    const now = this.layers.scan, past = this.layers.history;
    const image = mini => {
      const off = document.createElement("canvas");
      off.width = B; off.height = B;
      const o = off.getContext("2d");
      const img = o.createImageData(B, B);
      for (let x = 0; x < B; x++) for (let y = 0; y < B; y++) {
        const i = x * B + y;
        const k = g[i] && now ? "now" : !past ? null : (g[i] || hist[i]) ? "past" : "never";
        if (!k) continue;
        const t = TINT[k], p = ((B - 1 - y) * B + x) * 4;          // y up
        img.data[p] = t[0]; img.data[p + 1] = t[1]; img.data[p + 2] = t[2]; img.data[p + 3] = mini ? MINI_ALPHA[k] : t[3];
      }
      o.putImageData(img, 0, 0);
      return off;
    };
    return { grid: g, hist, canvas: image(false), mini: image(true), edges: past ? this.edges(g, hist) : [] };
  }
  // The outline of the explored region (squares inside a scan now or scanned before; drawn with
  // the scan history layer):
  // unit edges between an explored and an unexplored square, merged into runs.  Each run is
  // [x1, y1, x2, y2] in world coordinates (square centres on integers, so edges on .5).
  edges(g, hist) {
    const B = BOARD, out = [];
    const known = (x, y) => { const i = wrap(x) * B + wrap(y); return !!(g[i] || hist[i]); };
    for (let x = 0; x < B; x++) {                       // vertical edges at x + .5
      let y0 = null;
      for (let y = 0; y <= B; y++) {
        const on = y < B && known(x, y) !== known(x + 1, y);
        if (on && y0 === null) y0 = y;
        if (!on && y0 !== null) { out.push([x + .5, y0 - .5, x + .5, y - .5]); y0 = null; }
      }
    }
    for (let y = 0; y < B; y++) {                       // horizontal edges at y + .5
      let x0 = null;
      for (let x = 0; x <= B; x++) {
        const on = x < B && known(x, y) !== known(x, y + 1);
        if (on && x0 === null) x0 = x;
        if (!on && x0 !== null) { out.push([x0 - .5, y + .5, x - .5, y + .5]); x0 = null; }
      }
    }
    return out;
  }
  // "now" | "past" | "never" for a square (relative coordinates)
  coverageOf(x, y) {
    if (!this.cover) return null;
    const i = wrap(x) * BOARD + wrap(y);
    return this.cover.grid[i] ? "now" : this.cover.hist[i] ? "past" : "never";
  }
  setLayer(k, on) {
    this.layers[k] = on;
    localStorage.setItem("mhgcLayers", JSON.stringify(this.layers));
    if (k === "scan" || k === "history") this.cover = this.coverage();
    this.dirty = true;
  }
  layerControls(box, legend) {
    clear(box, LAYERS.map(([k, label]) => {
      const cb = el("input", { type: "checkbox", checked: this.layers[k], onchange: e => this.setLayer(k, e.target.checked) });
      return el("label", {}, cb, label);
    }));
    const sq = (t, label, edge) => el("div", {}, el("span", { class: "sw sq", style: { background: onMap(t), ...(edge ? { boxShadow: `inset 0 0 0 1px ${EDGE}` } : {}) } }), label);
    const dot = f => el("span", { class: "hab-dot", style: { width: `${(f * 14).toFixed(1)}px`, height: `${(f * 14).toFixed(1)}px` } });
    clear(legend, Object.values(REL).map(r => el("div", {}, el("span", { class: "sw", style: { background: r.color } }), r.label)),
      el("div", { class: "legend-h" }, "Scans"),
      sq(TINT.now, "Inside your scans now"),
      sq(TINT.past, "Scanned before, not now", true),
      sq(TINT.never, "Never scanned"),
      el("div", { class: "dim" }, "Light outline = edge of the space you have explored"),
      el("div", { class: "legend-h" }, "Habitability (size)"),
      el("div", { class: "hab-row" }, ["EH", "VH", "H", "PH", "MH"].map((h, i) => el("span", { class: "hab-key", title: HAB_LABEL[h] }, dot(HAB_SIZE[5 - i]), h)),
        el("span", { class: "hab-key", title: "Rating not known: never short-scanned" }, el("span", { class: "hab-dot unknown" }), "?")),
      el("div", {}, el("span", { class: "pip", style: { background: PIP.MR, borderRadius: "1px" } }), "MR metal rich ",
        el("span", { class: "pip", style: { background: PIP.AR } }), "AR agri rich"),
      el("div", {}, el("span", { class: "pop-key" }, "12"), "population (your systems)"),
      el("div", { class: "dim" }, "Hollow ring = long-range scan; dashed = remembered (rating as last seen)"),
      el("div", { class: "legend-h" }, "Ships and fleets"),
      el("div", {}, glyphKey(g => chevron(g, 9, 8, 5, REL.own.color)), "your ships (not in a fleet), with a count"),
      el("div", {}, glyphKey(g => fleetGlyph(g, 9, 7, 5.5, REL.own.color, false)), "your fleet: name and number of ships"),
      el("div", {}, glyphKey(g => fleetGlyph(g, 9, 7, 5.5, REL.own.color, true)), "forming: created by this turn's draft"),
      el("div", {}, glyphKey(g => { chevron(g, 6, 7, 4.5, REL.neutral.color, false, true); fleetGlyph(g, 14, 7, 4.5, REL.war.color, false); }), "other races' ships and fleets (their colour)"),
      el("div", {}, glyphKey(g => { g.strokeStyle = HILITE; g.lineWidth = 2.5; g.beginPath(); g.arc(9, 7, 5.5, 0, Math.PI * 2); g.stroke(); }), "the selected fleet or ship"),
      el("div", { class: "dim" }, "Yellow dashes = this turn's draft moves"));
  }

  // ------------------------------------------------------------ view transform
  resize() {
    const r = this.c.parentElement.getBoundingClientRect();
    this.W = Math.max(100, r.width); this.H = Math.max(100, r.height);
    const dpr = window.devicePixelRatio || 1;
    this.c.width = Math.round(this.W * dpr); this.c.height = Math.round(this.H * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.minScale = Math.max(3, Math.min(this.W, this.H) / (BOARD + 12));
    this.scale = Math.max(this.scale, this.minScale);
    this.dirty = true;
  }
  sx(x) { return this.W / 2 + (x - this.cx) * this.scale; }
  sy(y) { return this.H / 2 - (y - this.cy) * this.scale; }
  toWorld(px, py) {
    return { x: wrap(Math.round((px - this.W / 2) / this.scale + this.cx)),
             y: wrap(Math.round(this.cy - (py - this.H / 2) / this.scale)) };
  }
  // the screen copies of a board square (the torus repeats every BOARD squares)
  images(x, y, pad = 2) {
    const out = [];
    const bx = this.cx + axisDelta(wrap(this.cx), x), by = this.cy + axisDelta(wrap(this.cy), y);
    const B = BOARD;
    for (const ox of [-B, 0, B]) for (const oy of [-B, 0, B]) {
      const X = this.sx(bx + ox), Y = this.sy(by + oy);
      const m = this.scale * pad;
      if (X > -m && X < this.W + m && Y > -m && Y < this.H + m) out.push([X, Y, bx + ox, by + oy]);
    }
    return out;
  }
  centerOn(x, y, scale) {
    this.cx = x; this.cy = y;
    if (scale) this.scale = Math.max(this.minScale, Math.min(64, scale));
    this.dirty = true;
  }
  zoom(f, px = this.W / 2, py = this.H / 2) {
    const before = { x: (px - this.W / 2) / this.scale + this.cx, y: this.cy - (py - this.H / 2) / this.scale };
    this.scale = Math.max(this.minScale, Math.min(64, this.scale * f));
    this.cx = before.x - (px - this.W / 2) / this.scale;
    this.cy = before.y + (py - this.H / 2) / this.scale;
    this.dirty = true;
  }
  setCursor(x, y, follow = true) {
    this.cursor = { x: wrap(x), y: wrap(y) };
    if (follow) {
      const X = this.sx(this.cx + axisDelta(wrap(this.cx), this.cursor.x)), Y = this.sy(this.cy + axisDelta(wrap(this.cy), this.cursor.y));
      const m = this.scale * 3;
      if (X < m || X > this.W - m || Y < m || Y > this.H - m) this.centerOn(this.cx + axisDelta(wrap(this.cx), this.cursor.x), this.cy + axisDelta(wrap(this.cy), this.cursor.y));
    }
    this.dirty = true;
    emit("cursor", this.cursor);
  }

  // ------------------------------------------------------------ picking a square for an order
  pickSquare(label) {
    if (this.pick) this.pick.resolve(null);
    return new Promise(resolve => {
      this.pick = { resolve, label };
      this.c.classList.add("picking");
      emit("pickmode", label);
      this.c.focus();
      this.dirty = true;
    });
  }
  endPick(result) {
    if (!this.pick) return;
    const p = this.pick;
    this.pick = null;
    this.c.classList.remove("picking");
    emit("pickmode", null);
    p.resolve(result);
    this.dirty = true;
  }

  // ------------------------------------------------------------ input
  bind() {
    const c = this.c;
    let down = null;
    c.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      down = { x: e.clientX, y: e.clientY, cx: this.cx, cy: this.cy, moved: false };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener("pointermove", e => {
      const r = c.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      if (down) {
        const dx = e.clientX - down.x, dy = e.clientY - down.y;
        if (!down.moved && Math.hypot(dx, dy) > 4) { down.moved = true; c.classList.add("dragging"); }
        if (down.moved) { this.cx = down.cx - dx / this.scale; this.cy = down.cy + dy / this.scale; this.dirty = true; }
      }
      this.mouse = { x: px, y: py };
      if (this.pick && this.pick.from) this.dirty = true;     // the rubber band follows the pointer
      const w = this.toWorld(px, py);
      if (!this.hover || this.hover.x !== w.x || this.hover.y !== w.y) { this.hover = w; this.dirty = true; }
      this.showTip(px, py, w);
    });
    c.addEventListener("pointerup", e => {
      if (!down) return;
      const moved = down.moved;
      down = null;
      c.classList.remove("dragging");
      if (moved) return;
      const r = c.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const w = this.toWorld(px, py);
      if (this.pick) { this.setCursor(w.x, w.y, false); return this.endPick(w); }
      // a click on a fleet glyph selects that fleet (glyphs sit off the square's centre)
      const hit = this.hitFleet(px, py);
      if (hit) { this.setCursor(hit.x, hit.y, false); return emit("select", { x: hit.x, y: hit.y, focus: hit.focus }); }
      this.setCursor(w.x, w.y, false);
      emit("select", w);
    });
    c.addEventListener("pointerleave", () => { this.hover = null; this.mouse = null; this.tip.hidden = true; this.dirty = true; });
    c.addEventListener("contextmenu", e => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      const w = this.toWorld(e.clientX - r.left, e.clientY - r.top);
      if (this.pick) return this.endPick(w);
      emit("mapMove", w);
    });
    c.addEventListener("wheel", e => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      this.zoom(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    c.addEventListener("keydown", e => {
      const k = e.key;
      const mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[k];
      if (mv) {
        e.preventDefault();
        const n = e.ctrlKey ? 10 : 1;
        if (e.shiftKey) { this.cx += mv[0] * 5; this.cy += mv[1] * 5; this.dirty = true; }
        else this.setCursor(this.cursor.x + mv[0] * n, this.cursor.y + mv[1] * n);
      } else if (k === "+" || k === "=") { this.zoom(1.25); }
      else if (k === "-" || k === "_") { this.zoom(0.8); }
      else if (k === "h" || k === "H") { this.centerOn(HOME, HOME); this.setCursor(HOME, HOME, false); }
      else if (k === "Enter" || k === " ") {
        e.preventDefault();
        if (this.pick) this.endPick({ ...this.cursor }); else emit("select", { ...this.cursor });
      } else if (k === "m" || k === "M") { if (this.pick) this.endPick({ ...this.cursor }); else emit("mapMove", { ...this.cursor }); }
      else if (k === "Escape") { if (this.pick) this.endPick(null); else emit("deselect"); }
    });
    this.mm.addEventListener("click", e => {
      const r = this.mm.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width * BOARD, y = BOARD - (e.clientY - r.top) / r.height * BOARD;
      this.centerOn(x, y);
    });
  }

  squareSummary(q) {
    const lines = [];
    if (q.system) {
      const s = q.system;
      const who = s.kind === "own" ? "yours" : systemOwnerLabel(s);
      const when = s.kind === "memory" ? ` · seen turn ${s.last_seen}${s.via === "cdrom" ? " (CD-ROM)" : ""}` : s.kind === "scan" ? ` · ${s.level} scan` : "";
      lines.push([s.name || "Unnamed system", `${who}${when}${s.kind === "own" ? ` · pop ${fmt(s.pop, 1)}` : ""}`]);
      const h = habText(s), asOf = habAsOf(s);
      lines.push(["Habitability", h ? `${h}${asOf ? ` (${asOf})` : ""}` : "unknown (needs a short range scan)"]);
    }
    if (q.fleets.length) lines.push([`${q.fleets.length} fleet${q.fleets.length > 1 ? "s" : ""}`, q.fleets.map(f => `${f.name} (${draftShipCount(f)})${f.forming ? " forming" : ""}`).join(", ")]);
    if (q.ships.length) lines.push([`${q.ships.length} ship${q.ships.length > 1 ? "s" : ""}`, summarizeTypes(q.ships)]);
    if (q.foreignFleets.length) lines.push([`${q.foreignFleets.length} foreign fleet${q.foreignFleets.length > 1 ? "s" : ""}`, q.foreignFleets.map(f => `${f.name} of the ${f.owner_name} (${f.ships.length})`).join(", ")]);
    if (q.foreign.length) lines.push([`${q.foreign.length} foreign ship${q.foreign.length > 1 ? "s" : ""}`, [...new Set(q.foreign.map(s => s.owner_name))].join(", ") + ": " + summarizeTypes(q.foreign)]);
    if (q.combats.length) lines.push(["Battle", "click for the combat report"]);
    return lines;
  }
  showTip(px, py, w) {
    const q = this.idx.get(key(w.x, w.y));
    const lines = q ? this.squareSummary(q) : [];
    if (!lines.length) { this.tip.hidden = true; return; }
    clear(this.tip, el("div", { class: "t2" }, xy(w.x, w.y)),
      lines.map(([a, b]) => el("div", {}, el("b", {}, a), " ", el("span", { class: "t2" }, b))));
    this.tip.hidden = false;
    const tw = this.tip.offsetWidth, th = this.tip.offsetHeight;
    this.tip.style.left = `${Math.min(px + 16, this.W - tw - 8)}px`;
    this.tip.style.top = `${Math.min(py + 16, this.H - th - 8)}px`;
  }

  // ------------------------------------------------------------ drawing
  draw() {
    const g = this.ctx, W = this.W, H = this.H, sc = this.scale;
    g.clearRect(0, 0, W, H);
    const bg = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * .7);
    bg.addColorStop(0, "#0a1222"); bg.addColorStop(1, "#03060c");
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    this.hits = [];
    this.glyphOff = new Map();   // "fleet:Name" | "loose:x,y" -> {dx, dy, r}: where a unit's glyph sits on its square
    if (!S.view) { this.placeHighlight(null); return; }
    g.save();
    if ((this.layers.scan || this.layers.history) && this.cover) {
      g.imageSmoothingEnabled = false;
      const B = BOARD, bx = Math.floor(this.cx / B) * B, by = Math.floor(this.cy / B) * B;
      const copies = [];
      for (const ox of [-B, 0, B]) for (const oy of [-B, 0, B]) {
        const x0 = this.sx(-0.5 + ox + bx), y0 = this.sy(B - 0.5 + oy + by);
        if (x0 > W || y0 > H || x0 + B * sc < 0 || y0 + B * sc < 0) continue;   // off screen
        copies.push([ox + bx, oy + by]);
        g.drawImage(this.cover.canvas, x0, y0, B * sc, B * sc);
      }
      const ed = this.cover.edges;
      if (ed.length) {                    // the outline of the explored region
        g.strokeStyle = EDGE; g.lineWidth = sc >= 6 ? 1.25 : 1;
        g.beginPath();
        for (const [ox, oy] of copies) for (const [x1, y1, x2, y2] of ed) {
          g.moveTo(this.sx(x1 + ox), this.sy(y1 + oy)); g.lineTo(this.sx(x2 + ox), this.sy(y2 + oy));
        }
        g.stroke();
      }
    }
    if (this.layers.grid) this.drawGrid();
    // home marker
    for (const [X, Y] of this.images(HOME, HOME)) {
      g.strokeStyle = "#4ea1ff33"; g.lineWidth = 1;
      g.beginPath(); g.arc(X, Y, sc * 4, 0, Math.PI * 2); g.stroke();
    }
    const squares = [...this.idx.values()];
    if (this.layers.paths) this.drawPaths();
    for (const q of squares) if (q.system && (q.system.kind !== "memory" || this.layers.memory)) this.drawSystem(q.system);
    for (const q of squares) this.drawShips(q);
    if (this.layers.combat) for (const q of squares) if (q.combats.length) this.drawBattle(q);
    if (this.layers.labels) for (const q of squares) if (q.system && (q.system.kind !== "memory" || this.layers.memory)) this.drawLabel(q.system);
    // selection, hover, cursor
    const box = (x, y, color, dash) => {
      for (const [X, Y] of this.images(x, y)) {
        g.strokeStyle = color; g.lineWidth = 2; g.setLineDash(dash || []);
        const r = Math.max(sc * 0.55, 7);
        g.strokeRect(X - r, Y - r, r * 2, r * 2);
        g.setLineDash([]);
      }
    };
    if (this.hover) box(this.hover.x, this.hover.y, "#ffffff40");
    if (S.selection) box(S.selection.x, S.selection.y, "#ffd166");
    if (document.activeElement === this.c || this.pick) box(this.cursor.x, this.cursor.y, this.pick ? "#7cc0ff" : "#ffd16699", [4, 3]);
    const from = this.pick && this.pick.from;
    if (from) {
      // choosing a destination: a rubber band from the unit to the pointer (or the keyboard
      // cursor), under the engine's path preview
      const [X0, Y0] = this.anchor(from);
      const tgt = this.mouse || (() => { const [, , cx2, cy2] = this.nearest(this.cursor.x, this.cursor.y); return { x: this.sx(cx2), y: this.sy(cy2) }; })();
      g.save();
      g.setLineDash([7, 5]); g.lineCap = "round";
      g.strokeStyle = "#03060cc0"; g.lineWidth = 6;
      g.beginPath(); g.moveTo(X0, Y0); g.lineTo(tgt.x, tgt.y); g.stroke();
      g.strokeStyle = HILITE; g.lineWidth = 3;
      g.beginPath(); g.moveTo(X0, Y0); g.lineTo(tgt.x, tgt.y); g.stroke();
      g.setLineDash([]);
      g.fillStyle = HILITE; g.beginPath(); g.arc(tgt.x, tgt.y, 3.5, 0, Math.PI * 2); g.fill();
      g.restore();
      const end = this.hover || this.cursor;
      this.drawPath(from.x, from.y, end.x, end.y, from.speed || 1, "#7cc0ff", true);
    }
    g.restore();
    this.placeHighlight(this.highlightUnit());
  }

  // the screen copy of a square nearest the view centre: [X, Y, bx, by]
  nearest(x, y) {
    const bx = this.cx + axisDelta(wrap(this.cx), x), by = this.cy + axisDelta(wrap(this.cy), y);
    return [this.sx(bx), this.sy(by), bx, by];
  }
  // where the highlighted unit is: the unit being moved, else the focused fleet or ship
  highlightUnit() {
    const v = S.view;
    if (!v) return null;
    if (this.pick && this.pick.from) return this.pick.from;
    const f = S.selection && S.selection.focus;
    if (!f) return null;
    if (f.kind === "fleet") { const o = findOwnFleet(f.id); return o ? { x: o.x, y: o.y, label: `Fleet ${o.name}`, fleet: o.name } : null; }
    if (f.kind === "ship") { const o = v.ships.find(s => s.number === f.id); return o ? { x: o.x, y: o.y, label: `Ship ${o.number}`, ship: o.number } : null; }
    return null;
  }
  // the screen point and ring radius for a unit: its own fleet glyph or the loose-ship chevron
  // when drawn this frame, else the square's centre
  anchor(u) {
    const [X, Y] = this.nearest(u.x, u.y);
    let fleet = u.fleet;
    if (!fleet && u.ship !== undefined) {
      const sh = S.view.ships.find(s => s.number === u.ship);
      fleet = sh ? effectiveFleet(sh) : null;
      if (!fleet) { const o = this.glyphOff.get(`loose:${key(u.x, u.y)}`); if (o) return [X + o.dx, Y + o.dy, o.r]; }
    }
    const o = fleet ? this.glyphOff.get(`fleet:${fleet}`) : null;
    if (o) return [X + o.dx, Y + o.dy, o.r];
    return [X, Y, Math.round(Math.max(16, Math.min(30, this.scale * 0.8)))];
  }
  // the part of the map not covered by the selection panel (CSS px)
  freeRect() {
    const insp = this.c.parentElement.querySelector("#inspector");
    const l = insp && !insp.hidden ? insp.offsetLeft + insp.offsetWidth : 0;
    return { l, t: 0, r: this.W, b: this.H };
  }
  // is a square in the free part of the map (with a margin)?  If not, bring it to the middle of
  // that part (Move uses this, so you see the unit before you pick its destination)
  onScreen(x, y, m = 30) {
    const [X, Y] = this.nearest(x, y), f = this.freeRect();
    return X >= f.l + m && X <= f.r - m && Y >= f.t + m && Y <= f.b - m;
  }
  ensureVisible(x, y) {
    if (this.onScreen(x, y, 40)) return false;
    const [, , bx, by] = this.nearest(x, y), f = this.freeRect();
    // centre of the free area, in world units relative to the canvas centre
    this.centerOn(bx - ((f.l + f.r) / 2 - this.W / 2) / this.scale, by + ((f.t + f.b) / 2 - this.H / 2) / this.scale);
    return true;
  }
  placeHighlight(u) {
    const ring = this.ring, edge = this.edge;
    if (!u) { ring.hidden = true; edge.hidden = true; return; }
    const [X, Y, R] = this.anchor(u);
    const m = 6, f = this.freeRect();
    ring.classList.toggle("picking", !!(this.pick && this.pick.from));
    if (X >= f.l + m && X <= f.r - m && Y >= f.t + m && Y <= f.b - m) {
      ring.hidden = false; edge.hidden = true;
      ring.style.left = `${X - R}px`; ring.style.top = `${Y - R}px`;
      ring.style.width = ring.style.height = `${2 * R}px`;
      ring.dataset.x = u.x; ring.dataset.y = u.y;
      return;
    }
    // off screen: an arrow on the map's edge, pointing at it (click to centre)
    ring.hidden = true; edge.hidden = false;
    // from the middle of the free area towards the unit, stopping at its edge
    const mx = (f.l + f.r) / 2, my = (f.t + f.b) / 2;
    const dx = X - mx, dy = Y - my, inset = 30;
    const t = Math.min(Math.abs(dx) > 0 ? ((f.r - f.l) / 2 - inset) / Math.abs(dx) : Infinity, Math.abs(dy) > 0 ? ((f.b - f.t) / 2 - inset) / Math.abs(dy) : Infinity);
    const ex = mx + dx * t, ey = my + dy * t;
    edge.style.left = `${ex}px`; edge.style.top = `${ey}px`;
    edge.querySelector(".edge-arrow-tip").style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
    const d = Math.round(Math.max(Math.abs(dx), Math.abs(dy)) / this.scale);
    edge.querySelector(".edge-arrow-label").textContent = `${u.label || "Selected"} · ${d} sq`;
    edge.dataset.x = u.x; edge.dataset.y = u.y;
    // keep the label inside the pane: anchor it on the side away from the edge
    edge.classList.toggle("left", ex > mx);
    edge.classList.toggle("up", ey > my);
  }
  hitFleet(px, py) {
    for (let i = this.hits.length - 1; i >= 0; i--) {
      const h = this.hits[i];
      if (Math.hypot(px - h.X, py - h.Y) <= h.r) return h;
    }
    return null;
  }

  drawGrid() {
    const g = this.ctx, sc = this.scale, W = this.W, H = this.H;
    const x0 = Math.floor(this.cx - W / 2 / sc) - 1, x1 = Math.ceil(this.cx + W / 2 / sc) + 1;
    const y0 = Math.floor(this.cy - H / 2 / sc) - 1, y1 = Math.ceil(this.cy + H / 2 / sc) + 1;
    g.lineWidth = 1;
    const line = (X1, Y1, X2, Y2) => { g.beginPath(); g.moveTo(X1, Y1); g.lineTo(X2, Y2); g.stroke(); };
    if (sc >= 9) {
      g.strokeStyle = "#ffffff0d";
      for (let x = x0; x <= x1; x++) if (wrap(x) % 10) line(this.sx(x - .5) | 0, 0, this.sx(x - .5) | 0, H);
      for (let y = y0; y <= y1; y++) if (wrap(y) % 10) line(0, this.sy(y - .5) | 0, W, this.sy(y - .5) | 0);
    }
    const stepL = sc >= 7 ? 10 : 20;
    g.font = "11px system-ui, sans-serif"; g.fillStyle = "#8f9bb6";
    for (let x = x0; x <= x1; x++) {
      if (wrap(x) % 10) continue;
      g.strokeStyle = wrap(x) === 0 ? "#7cc0ff40" : "#ffffff1c";
      line(this.sx(x - .5) | 0, 0, this.sx(x - .5) | 0, H);
      if (wrap(x) % stepL === 0) g.fillText(String(wrap(x)), this.sx(x) - 6, 14);
    }
    for (let y = y0; y <= y1; y++) {
      if (wrap(y) % 10) continue;
      g.strokeStyle = wrap(y) === 0 ? "#7cc0ff40" : "#ffffff1c";
      line(0, this.sy(y - .5) | 0, W, this.sy(y - .5) | 0);
      if (wrap(y) % stepL === 0) g.fillText(String(wrap(y)), 4, this.sy(y) + 4);
    }
  }

  sysRadius(s) {
    const base = Math.max(4.2, Math.min(14, 2.6 + this.scale * 0.3));
    return base * HAB_SIZE[habValue(s)];
  }
  drawSystem(s) {
    const g = this.ctx, sc = this.scale;
    const color = s.kind === "own" ? REL.own.color : systemColor(s);
    const r = this.sysRadius(s);
    const known = habValue(s) > 0;
    // the outline: a circle when the rating is known, a small diamond when it isn't
    const shape = (X, Y, rr) => {
      g.beginPath();
      if (known) g.arc(X, Y, rr, 0, Math.PI * 2);
      else { g.moveTo(X, Y - rr * 1.25); g.lineTo(X + rr * 1.25, Y); g.lineTo(X, Y + rr * 1.25); g.lineTo(X - rr * 1.25, Y); g.closePath(); }
    };
    for (const [X, Y] of this.images(s.x, s.y)) {
      g.save();
      if (s.kind === "memory") {
        g.globalAlpha = 0.75;
        g.setLineDash(sc >= 9 ? [2, 2] : []);
        g.strokeStyle = color; g.lineWidth = 1.4;
        shape(X, Y, r); g.stroke();
        g.fillStyle = color + "38"; g.fill();
        g.setLineDash([]);
      } else if (s.kind === "scan" && s.level === "long") {
        g.strokeStyle = color; g.lineWidth = sc >= 6 ? 2 : 1.5;
        shape(X, Y, r); g.stroke();
        g.fillStyle = color + "40"; g.fill();
      } else {
        const grd = g.createRadialGradient(X - r * .35, Y - r * .35, r * .1, X, Y, r);
        grd.addColorStop(0, "#ffffff"); grd.addColorStop(0.25, color); grd.addColorStop(1, shade(color));
        g.fillStyle = grd;
        g.beginPath(); g.arc(X, Y, r, 0, Math.PI * 2); g.fill();
        if (s.kind === "own" && s.x === HOME && s.y === HOME) {     // home
          g.strokeStyle = "#ffd166"; g.lineWidth = 1.5;
          g.beginPath(); g.arc(X, Y, r + 3.5, 0, Math.PI * 2); g.stroke();
        }
        if (s.starport && sc >= 6) {                            // starport: notches
          g.strokeStyle = "#e6ebf5"; g.lineWidth = 1.5;
          for (let i = 0; i < Math.min(5, s.starport); i++) {
            const a = -Math.PI / 2 + (i - (Math.min(5, s.starport) - 1) / 2) * 0.45;
            g.beginPath(); g.moveTo(X + Math.cos(a) * (r + 1), Y + Math.sin(a) * (r + 1));
            g.lineTo(X + Math.cos(a) * (r + 4), Y + Math.sin(a) * (r + 4)); g.stroke();
          }
        }
        const st = s.status;
        if (st && st !== "Norm" && st !== 0) {                // under attack / interdicted
          g.strokeStyle = "#ff5f5f"; g.lineWidth = 2; g.setLineDash([3, 2]);
          g.beginPath(); g.arc(X, Y, r + 5, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
        }
      }
      // MR / AR pips at the lower right (dimmed with the memory)
      if (known && (s.mr || s.ar)) {
        const p = Math.max(1.7, Math.min(3.4, sc * 0.12));
        let px = X + r * 0.78 + p * 0.6;
        const py = Y + r * 0.78 + p * 0.3;
        g.setLineDash([]); g.lineWidth = 1; g.strokeStyle = "#03060c";
        if (s.mr) { g.fillStyle = PIP.MR; g.beginPath(); g.rect(px - p, py - p, p * 2, p * 2); g.fill(); g.stroke(); px += p * 2.4; }
        if (s.ar) { g.fillStyle = PIP.AR; g.beginPath(); g.arc(px, py, p * 1.05, 0, Math.PI * 2); g.fill(); g.stroke(); }
      }
      // own systems: population badge at the upper left
      if (s.kind === "own" && sc >= 7) popBadge(g, X - r - 2, Y - r - 1, fmt(s.pop, s.pop < 10 ? 1 : 0));
      g.restore();
    }
  }
  drawLabel(s) {
    const g = this.ctx, sc = this.scale;
    const show = s.kind === "own" ? sc >= 5 : sc >= 9;
    if (!show || !s.name) return;
    const fs = Math.round(Math.max(10, Math.min(13, sc * 0.42)));
    g.font = `${s.kind === "own" ? "600 " : ""}${fs}px system-ui, sans-serif`;
    g.textAlign = "center";
    const r = this.sysRadius(s);
    for (const [X, Y] of this.images(s.x, s.y)) {
      const text = s.name;
      g.lineWidth = 3; g.strokeStyle = "#03060cd0";
      g.strokeText(text, X, Y + r + fs + 1);
      g.fillStyle = s.kind === "memory" ? "#8f9bb6" : s.kind === "own" ? "#e6ebf5" : "#c8d0e0";
      g.fillText(text, X, Y + r + fs + 1);
    }
    g.textAlign = "start";
  }
  // Loose ships are a chevron with a count (up and right of the square); each of your fleets is
  // a hexagon right of the system (several are stacked) with its ship count and, zoomed in, its
  // name to its right; a fleet this turn's draft is forming is dashed.  Other races: chevrons
  // down and left, fleets left of the system (name to the left), in their relation colour.
  // Zoomed out, a square shows one glyph of each kind ("+n" for more).
  drawShips(q) {
    const g = this.ctx, sc = this.scale;
    const sz = Math.max(3.5, Math.min(9, sc * 0.26));
    const off = Math.max(6, sc * 0.36);
    const fr = Math.max(4.5, Math.min(10, sc * 0.3));
    const many = sc >= 9 ? 3 : 1;                        // fleet glyphs per square before "+n"
    const showForeign = this.layers.foreign;
    const fleetMembers = new Set(q.foreignFleets.flatMap(f => f.ships));
    const looseForeign = q.foreign.filter(s => !fleetMembers.has(s.number));
    const side = (q.system ? this.sysRadius(q.system) : 3) + fr + 4;     // fleet glyphs clear the system
    for (const [X, Y] of this.images(q.x, q.y)) {
      if (q.ships.length) {
        chevron(g, X + off, Y - off, sz, REL.own.color, false);
        this.glyphOff.set(`loose:${key(q.x, q.y)}`, { dx: off, dy: -off, r: Math.round(Math.max(13, sz + 8)) });
        if (sc >= 8 && q.ships.length > 1) badge(g, X + off + sz + 2, Y - off - sz, String(q.ships.length));
      }
      const nOwn = Math.min(q.fleets.length, many), step = fr * 2.1;
      q.fleets.slice(0, many).forEach((f, i) => {
        const FX = X + side, FY = Y + (i - (nOwn - 1) / 2) * step;
        fleetGlyph(g, FX, FY, fr, REL.own.color, !!f.forming, sc >= 8 ? String(draftShipCount(f)) : null);   // the draft's members (AF, LF, MGF)
        this.hits.push({ X: FX, Y: FY, r: fr + 4, x: q.x, y: q.y, focus: { kind: "fleet", id: f.name } });
        this.glyphOff.set(`fleet:${f.name}`, { dx: FX - X, dy: FY - Y, r: Math.round(Math.max(13, fr + 7)) });
        if (sc >= 11 && this.layers.labels) fleetLabel(g, FX + fr + 3, FY, f.forming ? `${f.name} (forming)` : f.name, f.forming, "left");
      });
      if (q.fleets.length > many) badge(g, X + side - fr, Y + (nOwn / 2) * step + 4, `+${q.fleets.length - many}`);
      if (showForeign && (looseForeign.length || q.foreignFleets.length)) {
        const owners = [...new Set(looseForeign.map(s => s.owner))];
        owners.forEach((o, i) => chevron(g, X - off - i * (sz + 1.5), Y + off, sz, relColor(o), false, true));
        if (sc >= 8 && looseForeign.length > 1) badge(g, X - off - sz - 14, Y + off + 2, String(looseForeign.length));
        const nF = Math.min(q.foreignFleets.length, many), step = fr * 2.1;
        q.foreignFleets.slice(0, many).forEach((f, i) => {
          const FX = X - side, FY = Y + (i - (nF - 1) / 2) * step;
          fleetGlyph(g, FX, FY, fr, relColor(f.owner), false, sc >= 8 ? String(f.ships.length) : null);
          if (sc >= 11 && this.layers.labels) fleetLabel(g, FX - fr - 3, FY, f.name, false, "right");
        });
        if (q.foreignFleets.length > many) badge(g, X - side - fr, Y + (nF / 2) * step + 4, `+${q.foreignFleets.length - many}`);
      }
    }
  }
  drawBattle(q) {
    const g = this.ctx;
    const r = Math.max(9, this.scale * 0.7);
    for (const [X, Y] of this.images(q.x, q.y)) {
      g.save();
      g.strokeStyle = "#ff7a45"; g.lineWidth = 2;
      g.beginPath();
      for (let i = 0; i < 16; i++) {
        const a = i * Math.PI / 8, rr = i % 2 ? r * 0.55 : r;
        g.lineTo(X + Math.cos(a) * rr, Y + Math.sin(a) * rr);
      }
      g.closePath(); g.stroke();
      g.fillStyle = "#ff7a4522"; g.fill();
      g.restore();
    }
  }
  drawPaths() {
    const v = S.view;
    const f0 = S.selection && S.selection.focus;
    const isFocus = (kind, id) => f0 && f0.kind === kind && f0.id === id;
    // standing orders recede; this turn's draft moves and the focused unit's course stand out
    for (const f of ownFleets()) {
      const p = this.planned.get(`fleet:${f.name}`);
      const sp = fleetSpeed(f) || 1;
      if (p && p.x !== null) this.drawPath(f.x, f.y, p.x, p.y, sp, "#ffd166", "planned");
      else if (f.dest && (f.dest.x !== f.x || f.dest.y !== f.y)) this.drawPath(f.x, f.y, f.dest.x, f.dest.y, sp, REL.own.color, isFocus("fleet", f.name) ? "focus" : "standing");
    }
    for (const s of v.ships) {
      if (s.fleet) continue;
      const p = this.planned.get(`ship:${s.number}`);
      if (p && p.x !== null) this.drawPath(s.x, s.y, p.x, p.y, s.move || 1, "#ffd166", "planned");
      else if (s.dest && (s.dest.x !== s.x || s.dest.y !== s.y)) this.drawPath(s.x, s.y, s.dest.x, s.dest.y, s.move || 1, REL.own.color, isFocus("ship", s.number) ? "focus" : "standing");
    }
    // foreign ships: where they came from (scans show the square a ship moved from)
    if (this.layers.foreign) for (const s of v.scans.ships) {
      if (s.moved && s.ox !== undefined && (s.ox !== s.x || s.oy !== s.y)) this.drawTrail(s.ox, s.oy, s.x, s.y, relColor(s.owner));
    }
  }
  drawPath(x, y, dx, dy, speed, color, mode) {
    const planned = mode === "planned" || mode === true, strong = planned || mode === "focus";
    const g = this.ctx;
    const pts = pathTo(x, y, dx, dy, Math.max(1, speed));
    if (pts.length < 2) return;
    // unwrap so the line follows the short way round
    const un = [[x, y]];
    for (let i = 1; i < pts.length; i++) {
      const [px, py] = un[i - 1];
      un.push([px + axisDelta(wrap(px), pts[i][0]), py + axisDelta(wrap(py), pts[i][1])]);
    }
    for (const [, , bx, by] of this.images(x, y, 40)) {
      const ox = bx - x, oy = by - y;
      g.save();
      g.strokeStyle = color; g.lineWidth = strong ? 2 : 1.3; g.globalAlpha = strong ? 0.95 : 0.55;
      g.setLineDash(planned ? [6, 4] : []);
      g.beginPath();
      un.forEach(([px, py], i) => { const X = this.sx(px + ox), Y = this.sy(py + oy); i ? g.lineTo(X, Y) : g.moveTo(X, Y); });
      g.stroke(); g.setLineDash([]);
      g.fillStyle = color;
      if (strong || this.scale >= 10) un.slice(1).forEach(([px, py], i) => {
        const X = this.sx(px + ox), Y = this.sy(py + oy);
        g.beginPath(); g.arc(X, Y, i === un.length - 2 ? 3.2 : 2, 0, Math.PI * 2); g.fill();
      });
      if (this.scale >= 7 && (strong || this.scale >= 14)) {
        const [lx, ly] = un[un.length - 1];
        g.font = "600 11px system-ui, sans-serif";
        const t = `${un.length - 1}t`;
        const X = this.sx(lx + ox) + 6, Y = this.sy(ly + oy) - 6;
        g.lineWidth = 3; g.strokeStyle = "#03060c"; g.strokeText(t, X, Y); g.fillText(t, X, Y);
      }
      g.restore();
    }
  }
  drawTrail(x, y, dx, dy, color) {
    const g = this.ctx;
    const tx = x + axisDelta(x, dx), ty = y + axisDelta(y, dy);
    for (const [, , bx, by] of this.images(x, y, 20)) {
      const ox = bx - x, oy = by - y;
      g.save(); g.strokeStyle = color; g.globalAlpha = .45; g.lineWidth = 1.2; g.setLineDash([2, 3]);
      g.beginPath(); g.moveTo(this.sx(x + ox), this.sy(y + oy)); g.lineTo(this.sx(tx + ox), this.sy(ty + oy)); g.stroke();
      g.restore();
    }
  }

  drawMini() {
    const g = this.mctx, N = this.mm.width;
    const k = N / BOARD;
    g.clearRect(0, 0, N, N);
    g.fillStyle = "#050a14"; g.fillRect(0, 0, N, N);
    if (!S.view) return;
    if (this.cover) { g.globalAlpha = 1; g.imageSmoothingEnabled = false; g.drawImage(this.cover.mini, 0, 0, N, N); }
    for (const q of this.idx.values()) {
      if (!q.system) continue;
      const s = q.system;
      g.fillStyle = s.kind === "own" ? REL.own.color : systemColor(s);
      g.globalAlpha = s.kind === "memory" ? .5 : 1;
      const h = habValue(s);
      const r = h ? 1.2 + h * 0.28 : 1.1;                      // sized by habitability, as on the map
      g.fillRect(s.x * k - r / 2 + k / 2, (BOARD - 1 - s.y) * k - r / 2 + k / 2, r, r);
    }
    g.globalAlpha = 1;
    // viewport (may wrap)
    const w = this.W / this.scale * k, h = this.H / this.scale * k;
    const x0 = (wrap(this.cx) + .5) * k - w / 2, y0 = (BOARD - .5 - wrap(this.cy)) * k - h / 2;
    g.strokeStyle = "#ffd166"; g.lineWidth = 1;
    for (const ox of [-N, 0, N]) for (const oy of [-N, 0, N]) g.strokeRect(x0 + ox, y0 + oy, w, h);
  }
}

function shade(hex) {
  const n = parseInt(hex.slice(1), 16);
  const f = c => Math.round(c * 0.45).toString(16).padStart(2, "0");
  return `#${f(n >> 16)}${f((n >> 8) & 255)}${f(n & 255)}`;
}
function chevron(g, X, Y, s, color, fleet, down) {
  g.save();
  g.translate(X, Y);
  if (down) g.rotate(Math.PI);
  g.beginPath();
  g.moveTo(0, -s); g.lineTo(s * .85, s * .8); g.lineTo(0, s * .35); g.lineTo(-s * .85, s * .8); g.closePath();
  g.fillStyle = color; g.fill();
  g.lineWidth = 1; g.strokeStyle = "#03060c"; g.stroke();
  if (fleet) { g.strokeStyle = color; g.lineWidth = 1.2; g.beginPath(); g.arc(0, 0, s * 1.45, 0, Math.PI * 2); g.stroke(); }
  g.restore();
}
// a fleet: a hexagon in the owner's colour with the ship count; dashed and see-through while
// it is forming (created by this turn's draft)
function fleetGlyph(g, X, Y, r, color, forming, count) {
  g.save();
  g.beginPath();
  for (let i = 0; i < 6; i++) { const a = Math.PI / 6 + i * Math.PI / 3; g.lineTo(X + Math.cos(a) * r, Y + Math.sin(a) * r); }
  g.closePath();
  g.fillStyle = forming ? color + "5c" : color; g.fill();
  g.lineWidth = forming ? 1.6 : 1.2;
  g.setLineDash(forming ? [2.5, 2] : []);
  g.strokeStyle = forming ? color : "#03060c"; g.stroke();
  g.setLineDash([]);
  if (count) {
    g.font = `700 ${Math.round(Math.max(8, r * 1.15))}px system-ui, sans-serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillStyle = forming ? "#e6ebf5" : "#03060c";
    g.fillText(count, X, Y + 0.5);
  }
  g.restore();
}
function fleetLabel(g, X, Y, t, forming, align = "center") {
  g.save();
  g.font = `${forming ? "italic " : ""}600 10.5px system-ui, sans-serif`;
  g.textAlign = align; g.textBaseline = "middle";
  g.lineWidth = 3; g.strokeStyle = "#03060cd8"; g.strokeText(t, X, Y);
  g.fillStyle = "#cfe3ff"; g.fillText(t, X, Y);
  g.restore();
}
// a small canvas for a legend entry
function glyphKey(paint) {
  const c = el("canvas", { width: 36, height: 28, class: "glyph-key", "aria-hidden": "true" });
  const g = c.getContext("2d");
  g.scale(2, 2);
  paint(g);
  return c;
}
// population of an own system: a green-edged pill whose right edge sits at X
function popBadge(g, X, Y, t) {
  g.save();
  g.font = "600 10px system-ui, sans-serif";
  const w = g.measureText(t).width + 6;
  g.globalAlpha = 1;
  g.fillStyle = "#0b1424e8"; g.strokeStyle = "#3f8f5f"; g.lineWidth = 1;
  g.beginPath(); g.roundRect(X - w, Y - 6, w, 12, 6); g.fill(); g.stroke();
  g.fillStyle = "#9be7b0"; g.fillText(t, X - w + 3, Y + 3.5);
  g.restore();
}
function badge(g, X, Y, t) {
  g.save();
  g.font = "600 10px system-ui, sans-serif";
  const w = g.measureText(t).width + 6;
  g.fillStyle = "#0b1424e0"; g.strokeStyle = "#33456d";
  g.beginPath(); g.roundRect(X, Y - 6, w, 12, 6); g.fill(); g.stroke();
  g.fillStyle = "#e6ebf5"; g.fillText(t, X + 3, Y + 3.5);
  g.restore();
}
export function summarizeTypes(ships) {
  const c = {};
  for (const s of ships) c[s.type] = (c[s.type] || 0) + 1;
  return Object.entries(c).map(([t, n]) => `${n} ${shipClass(t)}`).join(", ");
}
export { relationOf };
