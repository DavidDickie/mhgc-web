// What the draft does to cargo before a given point (DECISIONS W-31, Dave 2026-11-21).  Orders run
// in draft order in phase 1, before movement (G-20), so a transport can unload and then load in
// the same turn.  The Load and Unload dialogs use this to start from the cargo a ship or fleet
// will really have when their new orders run, not the cargo at the start of the turn.
// Replays the cargo orders of your own ships and fleets (U/UG/L/SL/LOCT/LACT, FU/FUG/FL/FLOCT/
// FLACT) against the start-of-turn cargo, the stock of your systems and where your combat troops
// are.  An order that would fail is clamped to what it could do (Check orders reports it).  Fleet
// orders are spread over the fleet's ships here in list order: the engine picks random ships, so
// for a fleet this is an estimate.  Fleet membership and positions are the start of the turn's
// (movement comes after the orders anyway).
"use strict";
import { S } from "./core.js";
import { rowToDict } from "./orders.js";
import { findOwnFleet } from "./world.js";

const UNITS = 20;                                   // constants.CARGO_UNITS_PER_POINT
const KEY = { A: "AU", I: "IU", P: "POP" };
const SHIP_CODES = new Set(["U", "UG", "L", "SL", "LOCT", "LACT"]);
const FLEET_CODES = new Set(["FU", "FUG", "FL", "FLOCT", "FLACT"]);
export const UNLOAD_CODES = new Set(["U", "UG", "LACT", "FU", "FUG", "FLACT"]);
export const LOAD_CODES = new Set(["L", "SL", "LOCT", "FL", "FLOCT"]);

export const pointsUsed = c => Math.ceil((c.AU + c.IU) / UNITS) + c.POP + c.CT.size;   // model.cargo_points_used
function freeFor(c, cap, item) {                    // model.free_cargo
  const k = cap - c.POP - c.CT.size;
  if (item === "P") return Math.max(0, Math.floor(k - Math.ceil((c.AU + c.IU) / UNITS)));
  return Math.max(0, k * UNITS - c.AU - c.IU);
}

// Does draft order d touch this carrier?  A ship is touched by its own orders and by its fleet's;
// a fleet by its own orders and by those of its member ships here.
export function touches(d, target) {
  if (target.kind === "ship") {
    if (SHIP_CODES.has(d.code) && Number(d.ship) === target.id) return true;
    if (FLEET_CODES.has(d.code)) { const f = findOwnFleet(d.fleet); return !!f && f.ships.includes(target.id); }
    return false;
  }
  if (FLEET_CODES.has(d.code)) return d.fleet === target.id;
  if (SHIP_CODES.has(d.code)) { const f = findOwnFleet(target.id); return !!f && f.ships.includes(Number(d.ship)); }
  return false;
}

// Replay `list` (draft dicts) up to but not including index `upto`, skipping the indices in
// `skip`.  Returns { ship(n) -> {AU, IU, POP, CT:Set}, stock(systemId) -> {A, I, P}, ground(systemId)
// -> Set of troop numbers, changed: Set of ship numbers whose cargo the replay changed }.
export function replay(list, upto, skip = new Set()) {
  const v = S.view;
  const ships = new Map(), stock = new Map(), ground = new Map(), changed = new Set();
  const shipOf = n => {
    if (!ships.has(n)) {
      const s = v.ships.find(x => x.number === n);
      const c = (s && s.cargo) || {};
      ships.set(n, { s, c: { AU: c.AU || 0, IU: c.IU || 0, POP: c.POP || 0, CT: new Set(c.CT || []) } });
    }
    return ships.get(n);
  };
  const sysAt = s => s && v.systems.find(y => y.x === s.x && y.y === s.y);      // own systems only
  const stockOf = sys => {
    if (!stock.has(sys.id)) stock.set(sys.id, { A: sys.au || 0, I: sys.iu || 0, P: sys.pop || 0 });
    return stock.get(sys.id);
  };
  const groundOf = id => {
    if (!ground.has(id)) ground.set(id, new Set(v.troops.filter(t => !t.ship && t.system === id).map(t => t.number)));
    return ground.get(id);
  };
  const load = (n, item, amt) => {                  // returns how much went aboard
    const sh = shipOf(n), sys = sysAt(sh.s);
    if (!sh.s || !sys) return 0;
    const st = stockOf(sys);
    const k = Math.min(amt, freeFor(sh.c, sh.s.cargo_capacity || 0, item), Math.max(0, st[item]));
    if (k <= 0) return 0;
    sh.c[KEY[item]] += k; st[item] -= k; changed.add(n);
    return k;
  };
  const unload = (n, item, amt) => {
    const sh = shipOf(n);
    const k = Math.max(0, Math.min(amt, sh.c[KEY[item]]));
    if (k <= 0) return 0;
    sh.c[KEY[item]] -= k; changed.add(n);
    const sys = sysAt(sh.s);
    if (sys) stockOf(sys)[item] += k;
    return k;
  };
  const loadCt = (n, ct) => {
    const sh = shipOf(n), sys = sysAt(sh.s);
    if (!sh.s || !sys || !groundOf(sys.id).has(ct) || pointsUsed(sh.c) + 1 > (sh.s.cargo_capacity || 0)) return false;
    groundOf(sys.id).delete(ct); sh.c.CT.add(ct); changed.add(n);
    return true;
  };
  const landCt = (n, ct) => {
    const sh = shipOf(n);
    if (!sh.c.CT.has(ct)) return false;
    sh.c.CT.delete(ct); changed.add(n);
    const sys = sysAt(sh.s);
    if (sys) groundOf(sys.id).add(ct);
    return true;
  };
  const members = name => {
    const f = findOwnFleet(name);
    return f ? v.ships.filter(s => f.ships.includes(s.number) && s.x === f.x && s.y === f.y && (s.cargo_capacity || 0) > 0) : [];
  };
  list.forEach((d, i) => {
    if (i >= upto || skip.has(i)) return;
    const amt = Number(d.amount || 0), ct = Number(d.ct);
    switch (d.code) {
      case "L": case "SL": load(Number(d.ship), d.item, amt); break;
      case "U": case "UG": unload(Number(d.ship), d.item, amt); break;
      case "LOCT": loadCt(Number(d.ship), ct); break;
      case "LACT": landCt(Number(d.ship), ct); break;
      case "FL": { let left = amt; for (const s of members(d.fleet)) { if (left <= 0) break; left -= load(s.number, d.item, left); } break; }
      case "FU": case "FUG": { let left = amt; for (const s of members(d.fleet)) { if (left <= 0) break; left -= unload(s.number, d.item, left); } break; }
      case "FLOCT": for (const s of members(d.fleet)) if (loadCt(s.number, ct)) break; break;
      case "FLACT": for (const s of members(d.fleet)) if (landCt(s.number, ct)) break; break;
      default: break;
    }
  });
  return {
    ship: n => shipOf(n).c,
    stock: sys => stockOf(sys),
    ground: id => groundOf(id),
    changed,
  };
}

// index of the last draft order (in `list`, not in `skip`) that unloads this carrier, or -1
export function lastUnload(list, target, skip = new Set()) {
  let at = -1;
  list.forEach((d, i) => { if (!skip.has(i) && UNLOAD_CODES.has(d.code) && touches(d, target)) at = i; });
  return at;
}
