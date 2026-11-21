// The map's model: what is on each square of the (relative) board, built from the view and the
// draft orders.  Rebuilt whenever the view or the draft changes.
"use strict";
import { S, wrap, isHistory, xy } from "./core.js";

export const key = (x, y) => `${wrap(x)},${wrap(y)}`;

function square(idx, x, y) {
  const k = key(x, y);
  let q = idx.get(k);
  if (!q) {
    q = { x: wrap(x), y: wrap(y), system: null, fleets: [], ships: [], fleetShips: [], foreign: [],
          foreignFleets: [], combats: [] };
    idx.set(k, q);
  }
  return q;
}

// Where the draft sends each own ship / fleet (the last movement order wins, as in the engine).
export function plannedMoves() {
  const v = S.view;
  const out = new Map();     // "ship:N" | "fleet:Name" -> {x, y, how, index}
  if (!v) return out;
  const sysByName = new Map();
  for (const s of [...v.known_systems, ...v.systems]) if (s.name) sysByName.set(s.name.toLowerCase(), s);
  const shipAt = n => v.ships.find(s => s.number === n) || v.scans.ships.find(s => s.number === n);
  S.draft.forEach((o, i) => {
    let k = null, x = null, y = null, how = o.code;
    if (o.code === "MO") { k = `ship:${o.ship}`; x = o.x; y = o.y; }
    else if (o.code === "MF") { k = `fleet:${o.fleet}`; x = o.x; y = o.y; }
    else if (o.code === "MS" || o.code === "MFS" || o.code === "WTP" || o.code === "WTPF") {
      k = o.code === "MS" || o.code === "WTP" ? `ship:${o.ship}` : `fleet:${o.fleet}`;
      const s = sysByName.get(String(o.system || "").toLowerCase());
      if (s) { x = s.x; y = s.y; }
    } else if (o.code === "I" || o.code === "FIS") {
      k = o.code === "I" ? `ship:${o.ship}` : `fleet:${o.fleet}`;
      const t = shipAt(o.target);
      if (t) { x = t.x; y = t.y; }
    } else if (o.code === "G") { k = `ship:${o.ship}`; }
    if (k) out.set(k, { x, y, how, index: i });
  });
  return out;
}

// What this turn's draft does to your fleets, in draft order (orders run before movement):
//   forming: fleets the draft creates (CF / CFXY), {name, x, y, ships, forming: true, via, index}
//   joins:   ship number -> fleet name, for ships the draft adds to a fleet (AF)
//   leaves:  ships the draft takes out of their fleet (LF)
//   disbanded: fleet names the draft disbands (DF)
//   merged:  absorbed fleet name -> the fleet it merges into (MGF, DECISIONS G-27): its ships
//            join that fleet at once and it is gone (its name is free for a later CF)
//   counts:  fleet name -> ships it has once the draft has run (the map's hexagon count)
// A CF fleet has the ships its AF orders add and can be moved this turn; a CFXY fleet collects
// the unfleeted ships on its square only after movement (movement.add_fleet_xy), so its
// members are a forecast and a move order for it starts next turn (canMoveNow: false).
export function draftFleets() {
  const v = S.view;
  const out = { forming: new Map(), joins: new Map(), leaves: new Set(), disbanded: new Set(), merged: new Map(), counts: new Map() };
  if (!v || isHistory()) return out;     // the draft is for the current turn only
  const own = new Set(v.fleets.map(f => f.name));
  const fleetNow = s => out.joins.has(s.number) ? out.joins.get(s.number) : out.leaves.has(s.number) ? null : (s.fleet || null);
  const where = n => { const f = out.forming.get(n) || (own.has(n) && v.fleets.find(q => q.name === n)); return f ? `${f.x},${f.y}` : null; };
  const mine = new Set(v.ships.map(s => s.number));
  S.draft.forEach((o, i) => {
    if ((o.code === "CF" || o.code === "CFXY") && o.name && !own.has(o.name) && !out.forming.has(o.name)) {
      out.forming.set(o.name, { name: o.name, number: null, x: wrap(o.x), y: wrap(o.y), from: { x: wrap(o.x), y: wrap(o.y) },
        dest: { x: wrap(o.x), y: wrap(o.y) }, order: "STAND", target: null, dest_system: null, posture: "M", role: "M",
        speed: "A", admiral: null, ships: [], forming: true, via: o.code, index: i, canMoveNow: o.code === "CF" });
    } else if (o.code === "AF" && o.fleet) {
      for (const n of o.ships || []) if (mine.has(n)) { out.joins.set(n, o.fleet); out.leaves.delete(n); }
    } else if (o.code === "LF" && o.fleet) {
      for (const n of o.ships || []) {
        if (out.joins.get(n) === o.fleet) out.joins.delete(n);
        else out.leaves.add(n);
      }
    } else if (o.code === "MGF" && o.fleet && o.into && o.fleet !== o.into) {
      // the engine's checks: both your fleets (live at this point), at the same square
      const a = where(o.fleet), b = where(o.into);
      if (!a || !b || a !== b) return;
      for (const s of v.ships) if (fleetNow(s) === o.fleet) { out.joins.set(s.number, o.into); out.leaves.delete(s.number); }
      if (out.forming.has(o.fleet)) out.forming.delete(o.fleet);
      own.delete(o.fleet);
      out.merged.set(o.fleet, o.into);
    } else if (o.code === "DF" && o.fleet) {
      out.disbanded.add(o.fleet);
      if (out.forming.has(o.fleet)) out.forming.delete(o.fleet);
      for (const [n, f] of out.joins) if (f === o.fleet) out.joins.delete(n);
    }
  });
  for (const [n, f] of out.joins) if (!own.has(f) && !out.forming.has(f)) out.joins.delete(n);   // AF to an unknown fleet fails
  for (const f of out.forming.values()) {
    f.ships = v.ships.filter(s => out.joins.get(s.number) === f.name).map(s => s.number);
    if (f.via === "CFXY") for (const s of v.ships) {
      if (s.x === f.x && s.y === f.y && !out.joins.has(s.number) && (!s.fleet || out.leaves.has(s.number)) && !f.ships.includes(s.number)) f.ships.push(s.number);
    }
    f.ships.sort((a, b) => a - b);
  }
  for (const s of v.ships) { const f = fleetNow(s); if (f) out.counts.set(f, (out.counts.get(f) || 0) + 1); }
  for (const f of out.forming.values()) if (f.via === "CFXY") out.counts.set(f.name, f.ships.length);
  return out;
}
// How many ships a fleet has once the draft has run (a CFXY fleet: its forecast).
export function draftShipCount(f, df = S.draftFleets) {
  if (!df || !df.counts || isHistory()) return f.ships.length;
  return df.counts.get(f.name) || 0;
}
// The fleet a ship will be in once the draft's orders have run (null = loose).
export function effectiveFleet(sh, df = S.draftFleets) {
  if (!df) return sh.fleet || null;
  if (df.joins.has(sh.number)) return df.joins.get(sh.number);
  if (df.leaves.has(sh.number)) return null;
  return sh.fleet || null;
}
// Your fleets: the view's, then those this turn's draft is forming.
export function ownFleets() {
  const v = S.view;
  if (!v) return [];
  const df = S.draftFleets || draftFleets();
  // a fleet the draft merges into another (MGF) is gone once the orders have run
  return [...v.fleets.filter(f => !(df.merged && df.merged.has(f.name))), ...df.forming.values()];
}
export function findOwnFleet(name) { return ownFleets().find(f => f.name === name) || null; }

export function buildIndex() {
  const v = S.view;
  const idx = new Map();
  if (!v) return idx;
  const scanned = new Set(v.scans.systems.map(s => s.id));
  const mine = new Set(v.systems.map(s => s.id));
  for (const s of v.known_systems) {
    if (mine.has(s.id) || scanned.has(s.id)) continue;
    square(idx, s.x, s.y).system = { kind: "memory", ...s };
  }
  for (const s of v.scans.systems) square(idx, s.x, s.y).system = { kind: "scan", ...s, owner: s.owner ?? null };
  for (const s of v.systems) square(idx, s.x, s.y).system = { kind: "own", ...s, owner: v.empire.id };
  S.draftFleets = draftFleets();
  for (const f of ownFleets()) square(idx, f.x, f.y).fleets.push(f);
  for (const sh of v.ships) {
    const q = square(idx, sh.x, sh.y);
    (effectiveFleet(sh) ? q.fleetShips : q.ships).push(sh);
  }
  for (const sh of v.scans.ships) square(idx, sh.x, sh.y).foreign.push(sh);
  for (const f of v.scans.fleets) square(idx, f.x, f.y).foreignFleets.push(f);
  for (const c of (v.results && v.results.combats) || []) square(idx, c.x, c.y).combats.push(c);
  return idx;
}

// Where something is, for lists and panels: the known system's name if it is at one, else x,y
// (Dave 2026-11-17: "If the ship is at a system, list the system instead of coordinates").
export function placeName(x, y) {
  const s = knownSystems().find(q => q.x === x && q.y === y && q.name);
  return s ? s.name : xy(x, y);
}

// Every system the player knows, for pickers and search: own first, then by name.
export function knownSystems() {
  const v = S.view;
  if (!v) return [];
  const seen = new Map();
  for (const s of v.systems) seen.set(s.id, { id: s.id, name: s.name, x: s.x, y: s.y, owner: v.empire.id, mine: true });
  for (const s of v.scans.systems) if (!seen.has(s.id)) seen.set(s.id, { id: s.id, name: s.name, x: s.x, y: s.y, owner: s.owner ?? null, owner_name: s.owner_name, owner_kind: s.owner_kind, mine: false });
  for (const s of v.known_systems) if (!seen.has(s.id)) seen.set(s.id, { id: s.id, name: s.name, x: s.x, y: s.y, owner: s.owner ?? null, owner_name: s.owner_name, owner_kind: s.owner_kind, mine: false, last_seen: s.last_seen, via: s.via });
  return [...seen.values()].sort((a, b) => (b.mine - a.mine) || String(a.name || "~").localeCompare(String(b.name || "~")));
}
