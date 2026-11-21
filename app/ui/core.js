// Shared plumbing for the MHGC UI: API calls, seat tokens, DOM helpers, app state, events.
// All user- and game-supplied text goes into the DOM via textContent, never innerHTML.
"use strict";

// ---------------------------------------------------------------- races logged in on this browser
// localStorage "mhgcSeats" = {gameId: {active: seat, races: {seat: {token, player, race}}}}: the
// session tokens of every race this browser is logged in to (DECISIONS W-21).  A browser can hold
// several races of one game; `active` is the one it last played.  A page plays exactly one race:
// the one in its address (?game=..&seat=N), pinned at load, so two tabs on two races never mix
// their tokens.  The older format {gameId: {seat, token, player}} is read as one race.
const SEATS_KEY = "mhgcSeats";
const pinned = {};
function norm(v) {
  if (!v || typeof v !== "object") return null;
  if (v.races) return v;
  if (v.token) return { active: v.seat, races: { [v.seat]: { token: v.token, player: v.player || "", race: v.race || "" } } };
  return null;
}
export function allSeats() {
  let raw;
  try { raw = JSON.parse(localStorage.getItem(SEATS_KEY)) || {}; } catch { raw = {}; }
  const out = {};
  for (const [gid, v] of Object.entries(raw)) { const n = norm(v); if (n && Object.keys(n.races).length) out[gid] = n; }
  return out;
}
function saveAll(all) { try { localStorage.setItem(SEATS_KEY, JSON.stringify(all)); } catch { /* storage blocked */ } }
// The race this page plays in game gid: {seat, token, player, race}, or null.
export function seatFor(gid) {
  const g = allSeats()[gid];
  if (!g) return null;
  const seat = pinned[gid] !== undefined && g.races[pinned[gid]] ? pinned[gid] : g.races[g.active] ? g.active : Number(Object.keys(g.races)[0]);
  const r = g.races[seat];
  return r ? { seat: Number(seat), ...r } : null;
}
// Every race this browser is logged in to in game gid: [{seat, token, player, race}].
export function racesFor(gid) {
  const g = allSeats()[gid];
  return g ? Object.entries(g.races).map(([s, r]) => ({ seat: Number(s), ...r })).sort((a, b) => a.seat - b.seat) : [];
}
export function keepSeat(gid, seat, token, player, race) {
  const all = allSeats();
  const g = all[gid] || { active: seat, races: {} };
  g.races[seat] = { token, player: player || "", race: race || "" };
  g.active = seat;
  all[gid] = g;
  saveAll(all);
  pinned[gid] = seat;
}
export function setRaceName(gid, seat, race) {
  const all = allSeats();
  if (all[gid] && all[gid].races[seat] && all[gid].races[seat].race !== race) { all[gid].races[seat].race = race; saveAll(all); }
}
export function pinSeat(gid, seat) {
  const all = allSeats();
  if (!all[gid] || !all[gid].races[seat]) return false;
  pinned[gid] = seat;
  all[gid].active = seat;
  saveAll(all);
  return true;
}
// Forget one race (seat given) or every race of the game (seat omitted).
export function forgetSeat(gid, seat) {
  const all = allSeats();
  if (!all[gid]) return;
  if (seat === undefined || seat === null) delete all[gid];
  else {
    delete all[gid].races[seat];
    if (!Object.keys(all[gid].races).length) delete all[gid];
    else if (Number(all[gid].active) === Number(seat)) all[gid].active = Number(Object.keys(all[gid].races)[0]);
  }
  if (pinned[gid] !== undefined && (!all[gid] || !all[gid].races[pinned[gid]])) delete pinned[gid];
  saveAll(all);
}

// ---------------------------------------------------------------- UI preferences
// localStorage "mhgcPrefs" = {key: value}: table sorts ("sort.<table>") and panel filters
// ("filter.<panel>"), per browser, for every game.  Panels are rebuilt from scratch on every
// render (draft changes, new turns, history, tab switches), so their controls must read their
// state from here rather than start at defaults.
const PREFS_KEY = "mhgcPrefs";
function allPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; } catch { return {}; }
}
export function getPref(key, dflt) {
  const v = allPrefs()[key];
  return v === undefined || v === null ? dflt : v;
}
export function setPref(key, value) {
  const all = allPrefs();
  all[key] = value;
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(all)); } catch { /* storage full or blocked: keep going */ }
}

// ---------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : (detail && detail.message) || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

// The host viewing as a race (DECISIONS W-23): the page's reads of "its" race go to the
// read-only /as/<race>/ endpoints instead.  Writes are never rewritten (the server refuses them).
const AS_PATH = /^\/api\/games\/([0-9a-f]{8})\/(view|orders|stats|turns|chat|production\/preview|production\/tweak|report\.txt)(\?.*)?$/;
export async function api(path, { method, body, gid, text, token } = {}) {
  if (!path.startsWith("/api/")) throw new Error("relative /api/ paths only");
  const headers = {};
  const s = gid ? seatFor(gid) : null;
  if (token) headers["X-Seat-Token"] = token;
  else if (s) headers["X-Seat-Token"] = s.token;
  const meth = method || (body !== undefined ? "POST" : "GET");
  if (gid && gid === S.gid && S.viewAs !== null && S.viewAs !== undefined && !token) {
    const m = AS_PATH.exec(path);
    if (m && (meth === "GET" || m[2].startsWith("production/"))) path = `/api/games/${m[1]}/as/${S.viewAs}/${m[2]}${m[3] || ""}`;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method: meth, headers, credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (text) {
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.text();
  }
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    let d = data && data.detail !== undefined ? data.detail : res.statusText;
    if (Array.isArray(d)) d = d.map(x => x.msg || JSON.stringify(x)).join("; ");   // pydantic 422
    throw new ApiError(res.status, d);
  }
  return data;
}

// ---------------------------------------------------------------- DOM helpers
export const $ = id => document.getElementById(id);

// el("div", {class: "x", onclick: fn, "aria-label": "..."}, child, "text", ...)
export function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (k === "class") e.className = v;
      else if (k === "dataset") Object.assign(e.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
      else if (k === "value") e.value = v;
      else if (k === "checked" || k === "selected" || k === "disabled" || k === "hidden") e[k] = !!v;
      else e.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const k of kids.flat(Infinity)) {
    if (k === undefined || k === null || k === false) continue;
    e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return e;
}

export function clear(node, ...kids) { node.replaceChildren(); for (const k of kids.flat()) if (k) node.append(k); return node; }

export function fmt(n, digits = 0) {
  if (n === null || n === undefined || n === "") return "–";
  if (typeof n !== "number") return String(n);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export const pct = v => `${Math.round(v)}%`;
export const xy = (x, y) => `${x},${y}`;

// ---------------------------------------------------------------- toasts
export function toast(msg, kind = "info", ms = 4000) {
  const box = $("toasts");
  const t = el("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, msg);
  box.append(t);
  while (box.children.length > 3) box.firstElementChild.remove();
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 400); }, ms);
}

// ---------------------------------------------------------------- confirm dialog (accessible)
export function confirmBox(title, body, okLabel = "OK", danger = false) {
  return new Promise(resolve => {
    const dlg = $("confirmDlg");
    $("confirmTitle").textContent = title;
    $("confirmBody").textContent = body;
    const ok = $("confirmOk");
    ok.textContent = okLabel;
    ok.classList.toggle("danger", danger);
    const done = v => { dlg.close(); resolve(v); };
    ok.onclick = () => done(true);
    $("confirmCancel").onclick = () => done(false);
    dlg.oncancel = e => { e.preventDefault(); done(false); };
    dlg.showModal();
    $("confirmCancel").focus();
  });
}

// ---------------------------------------------------------------- tiny event bus
const handlers = {};
export function on(name, fn) { (handlers[name] ||= []).push(fn); }
export function emit(name, arg) { for (const fn of handlers[name] || []) { try { fn(arg); } catch (e) { console.error(e); } } }

// ---------------------------------------------------------------- the app state
export const S = {
  gid: null,             // the open game
  summary: null,         // lobby summary of the open game
  view: null,            // the view being shown (current turn or history)
  currentView: null,     // the view of the current turn
  viewTurn: null,        // the turn being shown
  draft: [],             // draft orders [{code, ...args, text}]
  submitted: false,
  checks: null,          // last check results, aligned to draft by index
  advice: [],            // check-orders warnings for the draft [{index, kind, text, fix}] (G-20)
  adviceSig: null,       // the draft text the advice is for
  catalogue: null,       // /api/orders/catalogue
  ref: null,             // /api/reference
  stats: null,           // /api/games/{gid}/stats
  selection: null,       // {x, y, kind?, id?}
  draftFleets: null,     // world.draftFleets(): fleets the draft forms, joins and leaves (rebuilt with the map index)
  versionSeen: null,
  chatLast: 0,
  viewAs: null,          // host login: the race being viewed (read-only), else null
  hostRaces: null,       // host login: /host/races
};

export const isHistory = () => S.view && S.view.game.turn !== S.view.current_turn;
export const canOrder = () => S.view && !isHistory() && S.view.seat.needs_orders && !S.view.game.winner;

// ---------------------------------------------------------------- relations and colours
// Map colours encode relation to you (like the old viewer's label colours), not identity:
// 16 empires are too many hues to tell apart, and relation is what matters on the map.
export const REL = {
  own:     { color: "#4ea1ff", label: "Yours" },
  ally:    { color: "#2fd39a", label: "Allied" },
  neutral: { color: "#f0b429", label: "Neutral (contacted)" },
  war:     { color: "#ff5f5f", label: "At war" },
  stranger:{ color: "#c7a6ff", label: "Not contacted" },
  rebels:  { color: "#e58fd0", label: "Rebels (a system that rebelled)" },
  unowned: { color: "#b9c2d3", label: "Unowned (no population)" },
  none:    { color: "#6f7a90", label: "Owner unknown" },
};
export const STANCE = { N: "Neutral", A: "Allied", W: "At war", E: "At war (peace offered)" };
// "At war" from your own stance only (W, or E = you offered peace); their stance is hidden.
export const atWar = stance => stance === "W" || stance === "E";
// Orders that may not target a race you are at war with (DECISIONS, Dave 2026-11-12: GS).
export const NOT_AT_WAR_CODES = new Set(["GS"]);
export const giftableRaces = code => (S.view ? S.view.races : []).filter(r => r.kind !== "extinct" && !(NOT_AT_WAR_CODES.has(code) && atWar(r.our_stance)));

export function relationOf(owner) {
  const v = S.view;
  if (owner === null || owner === undefined) return "none";
  if (v && owner === v.empire.id) return "own";
  if (owner === 0) return "rebels";
  const r = v && v.races.find(x => x.id === owner);
  if (!r) return "stranger";
  return r.our_stance === "A" ? "ally" : (r.our_stance === "W" || r.our_stance === "E") ? "war" : "neutral";
}
export const relColor = owner => REL[relationOf(owner)].color;
// Systems: empire 0 is "unowned" (empty) or "rebels" (populated); view.py decides and sends
// owner_kind, so the UI never needs the population.  Troops of empire 0 are always Rebels.
export const systemRel = s => s.owner_kind === "unowned" ? "unowned" : s.owner_kind === "rebels" ? "rebels" : relationOf(s.owner);
export const systemColor = s => REL[systemRel(s)].color;
// Habitability (rules: EH > VH > H > PH > MH) and the MR/AR flags, as far as the player knows them:
// own systems and short scans now, long scans and map memory from the last short scan (view.py
// sends details_turn).  0 = rating unknown.
export const HAB_VALUE = { MH: 1, PH: 2, H: 3, VH: 4, EH: 5 };
export const HAB_LABEL = { EH: "Extremely habitable", VH: "Very habitable", H: "Habitable", PH: "Poorly habitable", MH: "Marginally habitable" };
export const habValue = s => (s && (s.hab_value || HAB_VALUE[s.hab])) || 0;
export function habText(s) {
  if (!habValue(s)) return null;
  const res = [s.mr ? "MR" : null, s.ar ? "AR" : null].filter(Boolean);
  return [s.hab, ...res].join(" · ");
}
// "as of turn N" when the rating comes from an earlier short scan
export function habAsOf(s) {
  if (!habValue(s) || s.kind === "own" || !s.details_turn) return "";
  return S.view && s.details_turn >= S.view.game.turn && s.kind !== "memory" ? "" : `as of turn ${s.details_turn}`;
}
export function systemOwnerLabel(s) {
  if (S.view && s.owner === S.view.empire.id) return S.view.empire.name;
  if (s.owner_kind) return s.owner_kind === "unowned" ? "Unowned" : "Rebels";
  if (s.owner === null || s.owner === undefined) return s.owner_name && s.owner_name !== "Unknown" ? s.owner_name : "Owner unknown";
  return raceName(s.owner);
}

// ---------------------------------------------------------------- geometry (torus, relative)
// The board side and the home square come from the game (view.game.board: 100, 75 or 50; home at
// the centre, 50,50, 37,37 or 25,25).  ES module bindings are live, so importers see setBoard's values.
export let BOARD = 100;
export let HOME = 50;
export function setBoard(n) { BOARD = Number(n) || 100; HOME = Math.floor(BOARD / 2); }
export const wrap = v => ((v % BOARD) + BOARD) % BOARD;
export function axisDelta(a, b) { let d = wrap(b - a); return d > BOARD / 2 ? d - BOARD : d; }
export const dist = (x1, y1, x2, y2) => Math.max(Math.abs(axisDelta(x1, x2)), Math.abs(axisDelta(y1, y2)));
// One turn of movement: each axis steps up to `speed` by the shortest path (geometry.step).
export function step(x, y, dx, dy, speed) {
  const ax = (a, b) => { const d = axisDelta(a, b); return Math.abs(d) <= speed ? wrap(b) : wrap(a + Math.sign(d) * speed); };
  return [ax(x, dx), ax(y, dy)];
}
export function pathTo(x, y, dx, dy, speed) {
  const pts = [[x, y]];
  let cx = x, cy = y;
  for (let i = 0; i < 60 && (cx !== dx || cy !== dy); i++) { [cx, cy] = step(cx, cy, dx, dy, speed); pts.push([cx, cy]); }
  return pts;
}

// ---------------------------------------------------------------- lookups over the view
export function sysName(id) {
  const v = S.view;
  const s = v.systems.find(q => q.id === id) || v.known_systems.find(q => q.id === id)
    || v.scans.systems.find(q => q.id === id);
  return s ? (s.name || `system at ${s.x},${s.y}`) : `#${id}`;
}
export function systemById(id) {
  const v = S.view;
  return v.systems.find(q => q.id === id) || null;
}
export function shipClass(code) {
  const t = S.ref && S.ref.ships.find(s => s.code === code);
  return t ? t.name : code;
}
export function troopName(code) {
  const t = S.ref && S.ref.troops.find(s => s.code === code);
  return t ? t.name : code;
}
export function techName(id) {
  const t = S.ref && S.ref.techs.find(s => s.id === id);
  return t ? t.name : `Tech ${id}`;
}
export function raceName(id) {
  if (!S.view) return `#${id}`;
  if (id === S.view.empire.id) return S.view.empire.name;
  if (id === 0) return "Rebels";
  const r = S.view.races.find(x => x.id === id);
  return r ? r.name : `Empire ${id}`;
}
export function seatName(seat) {
  const s = S.summary && S.summary.seats.find(x => x.seat === seat);
  if (!s) return `seat ${seat}`;
  return s.open ? `seat ${seat} (open)` : `${s.player} (${s.race})`;
}
// Fleet speed: "A" = the slowest member (movement.py).
export function fleetSpeed(f) {
  if (f.speed !== "A" && f.speed !== null && f.speed !== undefined) return Number(f.speed);
  const ms = f.ships.map(n => S.view.ships.find(s => s.number === n)).filter(Boolean).map(s => s.move);
  return ms.length ? Math.min(...ms) : 0;
}
