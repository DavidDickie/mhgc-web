// Combined transport loading (Dave 2026-11-14): one dialog to load population, IU, AU and combat
// troops onto a ship (L + LOCT) or a fleet (FL + FLOCT) at once.  Capacity follows the engine
// (model.cargo_points_used / free_cargo): population 1 cargo point each, AU and IU together 20 to
// a point (rounded up), a combat troop 1 point.  Draft orders that already load this ship or
// fleet prefill the dialog, and confirming replaces them.  The single-item forms stay available
// under "Other orders" and for editing one draft order.
// Draft-aware (W-31, Dave 2026-11-21): orders run in draft order before movement, so both dialogs
// start from the cargo (and system stock and troops) the carrier will have when their new orders
// run (cargoplan.replay), and new loads go after the carrier's last drafted unload.
"use strict";
import { S, el, clear, fmt, toast, canOrder, troopName, xy } from "./core.js";
import { saveDraft, rowToDict } from "./orders.js";
import { knownSystems, findOwnFleet } from "./world.js";
import { replay, lastUnload } from "./cargoplan.js";

const UNITS = 20;                 // AU/IU per cargo point (constants.CARGO_UNITS_PER_POINT)
let dlg = null;

function ensure() {
  if (dlg) return dlg;
  dlg = el("dialog", { id: "loadDlg", class: "load-dlg", "aria-labelledby": "loadH" });
  document.body.append(dlg);
  return dlg;
}

const goodsPoints = units => Math.ceil(units / UNITS);
function shipFree(s, cargoOf) {    // what the ship holds (at the start of the turn, or as cargoOf says)
  const c = (cargoOf ? cargoOf(s) : s.cargo) || { AU: 0, IU: 0, POP: 0, CT: [] };
  const ct = c.CT instanceof Set ? c.CT.size : (c.CT || []).length;
  return { cap: s.cargo_capacity || 0, pop: c.POP || 0, goods: (c.AU || 0) + (c.IU || 0), ct };
}

// the carriers: one ship, or a fleet's members at the fleet's square
function carriers(target) {
  if (target.kind === "ship") return [S.view.ships.find(s => s.number === target.id)].filter(Boolean);
  const f = findOwnFleet(target.id);
  if (!f) return [];
  return S.view.ships.filter(s => f.ships.includes(s.number) && s.x === f.x && s.y === f.y && (s.cargo_capacity || 0) > 0);
}

// draft orders that load this carrier: [index, dict]
function loadsOf(target) {
  const out = [];
  S.draft.forEach((row, i) => {
    const d = rowToDict(row);
    if (target.kind === "ship" && (d.code === "L" || d.code === "LOCT") && Number(d.ship) === target.id) out.push([i, d]);
    if (target.kind === "fleet" && (d.code === "FL" || d.code === "FLOCT") && d.fleet === target.id) out.push([i, d]);
  });
  return out;
}

// capacity used after loading: per ship exact; for a fleet the sum over its ships (an estimate:
// the engine spreads each load over random ships with room, so rounding can differ by a point)
export function capacity(ships, add, cargoOf) {
  const now = ships.map(s => shipFree(s, cargoOf));
  const cap = now.reduce((a, x) => a + x.cap, 0);
  const pop = now.reduce((a, x) => a + x.pop, 0) + add.P;
  const ct = now.reduce((a, x) => a + x.ct, 0) + add.T;
  const goodsNow = now.reduce((a, x) => a + goodsPoints(x.goods), 0);
  const goods = ships.length === 1 ? goodsPoints(now[0].goods + add.A + add.I)
    : goodsNow + goodsPoints(add.A + add.I);
  const used = pop + ct + goods;
  return { cap, used, left: cap - used, nowUsed: now.reduce((a, x) => a + x.pop + x.ct + goodsPoints(x.goods), 0) };
}

export function openLoad(target) {
  if (!canOrder()) return;
  ensure();
  const ships = carriers(target);
  const where = target.kind === "ship" ? ships[0] : findOwnFleet(target.id);
  if (!where || !ships.length) { toast(target.kind === "fleet" ? `Fleet ${target.id} has no ships with cargo room here.` : "No such ship.", "error"); return; }
  const sys = S.view.systems.find(s => s.x === where.x && s.y === where.y);
  const label = target.kind === "ship" ? `ship ${target.id} (${ships[0].class})` : `fleet ${target.id} (${ships.length} cargo ship${ships.length === 1 ? "" : "s"} here)`;
  if (!sys) { toast(`${label[0].toUpperCase()}${label.slice(1)} isn't at one of your systems: loading needs your own system.`, "error", 6000); return; }
  const prior = loadsOf(target);
  // where the new loads go: after the carrier's last drafted unload (so the engine runs unload
  // then load), otherwise in place of the old loads, otherwise at the end
  const list = S.draft.map(rowToDict);
  const drop = new Set(prior.map(([i]) => i));
  const lu = lastUnload(list, target, drop);
  const at = prior.length ? Math.max(prior[0][0], lu + 1) : list.length;
  const sim = replay(list, at, drop);           // the draft up to there, without the old loads
  const cargoOf = s => sim.ship(s.number);
  const draftChanged = ships.some(s => sim.changed.has(s.number));
  const none = { P: 0, I: 0, A: 0, T: 0 };
  const start = capacity(ships, none), after = capacity(ships, none, cargoOf);
  const pre = { P: 0, I: 0, A: 0, troops: new Set() };
  for (const [, d] of prior) {
    if (d.code === "L" || d.code === "FL") pre[d.item] = (pre[d.item] || 0) + Number(d.amount || 0);
    else pre.troops.add(Number(d.ct));
  }
  // eligible troops: as the LOCT picker - your own, on the ground at this system, no militia
  // and the system's stock: what the draft unloads here before then can be loaded
  const onGround = sim.ground(sys.id);
  const troops = S.view.troops.filter(t => onGround.has(t.number) && t.type !== "M");
  const st = sim.stock(sys);
  const stock = { P: Math.floor(st.P + 1e-9), I: st.I, A: st.A };
  const start0 = { P: Math.floor(sys.pop), I: sys.iu, A: sys.au };
  const stockNote = k => stock[k] !== start0[k] ? ` after your draft (${fmt(start0[k])} at the start of the turn)` : "";
  const num = (item, name) => el("label", { class: "load-num" }, `${name}`,
    el("input", { type: "number", name: item, min: 0, step: 1, inputmode: "numeric", value: pre[item] || 0 }),
    el("span", { class: "dim" }, `${fmt(stock[item])} at ${sys.name}${stockNote(item)}`));
  const meter = el("div", { class: "load-meter", role: "status", "aria-live": "polite" });
  const err = el("p", { class: "err", role: "alert" });
  const ok = el("button", { type: "submit", class: "primary" }, prior.length ? "Replace orders" : "Add orders");
  const form = el("form", { method: "dialog", class: "form" },
    el("h2", { id: "loadH" }, `Load ${label}`),
    el("p", { class: "hint" }, `At ${sys.name} ${xy(sys.x, sys.y)}. One order is made per item you fill in${target.kind === "fleet" ? " (FL / FLOCT)" : " (L / LOCT)"}; a combat troop takes one cargo point, population one point each, AU and IU together 20 to a point.`
      + (prior.length ? ` Your draft already loads this ${target.kind}: ${prior.length === 1 ? "that order is" : `those ${prior.length} orders are`} shown here and will be replaced.` : "")
      + (lu >= 0 ? ` The load orders go after this ${target.kind}'s unloads in your draft, so the unloads run first.` : "")),
    draftChanged ? el("p", { class: "hint", id: "loadAfter" }, `${lu >= 0 ? "After the unloads in your draft" : "After the earlier cargo orders in your draft"}: ${Math.max(0, after.left)} of ${after.cap} cargo point${after.cap === 1 ? "" : "s"} free (${Math.max(0, start.left)} at the start of the turn)${target.kind === "fleet" ? "; an estimate for a fleet, as the engine picks its ships at random" : ""}.`) : null,
    el("div", { class: "load-nums" }, num("P", "Population"), num("I", "IU"), num("A", "AU")),
    el("fieldset", { class: "load-troops" }, el("legend", {}, `Combat troops at ${sys.name}`),
      troops.length ? el("div", { class: "checks" }, troops.map(t => el("label", {}, el("input", { type: "checkbox", name: "ct", value: t.number, checked: pre.troops.has(t.number) }), `${t.number} ${troopName(t.type)} (${t.posture})`)))
        : el("p", { class: "dim" }, "None here (militia can't be transported).")),
    meter, err,
    el("div", { class: "row-end gap" }, el("button", { type: "button", class: "ghost", onclick: () => dlg.close() }, "Cancel"), ok));
  const read = () => {
    const v = k => Math.max(0, Math.floor(Number(form.elements.namedItem(k).value) || 0));
    const cts = [...form.querySelectorAll("input[name=ct]:checked")].map(x => Number(x.value));
    return { P: v("P"), I: v("I"), A: v("A"), T: cts.length, cts };
  };
  const update = () => {
    const a = read();
    const c = capacity(ships, a, cargoOf);
    const problems = [];
    if (c.left < 0) problems.push(`Over capacity by ${-c.left} cargo point${c.left === -1 ? "" : "s"}.`);
    for (const [k, n] of [["P", "population"], ["I", "IU"], ["A", "AU"]]) if (a[k] > stock[k]) problems.push(`${sys.name} has only ${fmt(stock[k])} ${n}${stock[k] !== start0[k] ? " to load after your draft's earlier orders" : ""}.`);
    const neg = ["P", "I", "A"].some(k => Number(form.elements.namedItem(k).value) < 0);
    if (neg) problems.push("Amounts can't be negative.");
    const pct = c.cap ? Math.min(100, (c.used / c.cap) * 100) : 100;
    clear(meter, el("div", { class: "row-between" }, el("span", {}, `Cargo: ${c.used} of ${c.cap} points used`), el("span", { class: c.left < 0 ? "bad" : "dim" }, c.left < 0 ? `${-c.left} over` : `${c.left} left`)),
      el("div", { class: `bar${c.left < 0 ? " over" : ""}` }, el("span", { style: { width: `${pct}%` } })),
      el("div", { class: "dim" }, `${c.nowUsed} ${draftChanged ? "aboard after your draft's earlier orders" : "already aboard"} · this load: ${a.P} pop, ${a.I + a.A} AU/IU (${goodsPoints(a.I + a.A)} pt), ${a.T} troop${a.T === 1 ? "" : "s"}${ships.length > 1 ? " · across the fleet's ships, so ±1 point per ship from rounding" : ""}`));
    err.textContent = problems.join(" ");
    const nothing = !a.P && !a.I && !a.A && !a.T && !prior.length;
    ok.disabled = problems.length > 0 || nothing;
    return problems.length === 0;
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    if (!update()) return;
    const a = read();
    const made = [];
    const base = target.kind === "ship" ? { ship: target.id } : { fleet: target.id };
    const L = target.kind === "ship" ? "L" : "FL", CT = target.kind === "ship" ? "LOCT" : "FLOCT";
    for (const k of ["P", "I", "A"]) if (a[k] > 0) made.push({ code: L, ...base, item: k, amount: a[k] });
    for (const t of a.cts) made.push({ code: CT, ...base, ct: t });
    // put them at `at` (after the last unload, or where the old loads were); drop the old loads
    const out = [];
    list.forEach((d, i) => { if (i === at) out.push(...made); if (!drop.has(i)) out.push(d); });
    if (at >= list.length) out.push(...made);
    try {
      await saveDraft(out);
      dlg.close();
      toast(made.length ? `${prior.length ? "Replaced with" : "Added"} ${made.length} load order${made.length === 1 ? "" : "s"}.` : "Load orders removed.", "good");
    } catch (e) { err.textContent = e.message; }
  });
  clear(dlg, form);
  update();
  if (!dlg.open) dlg.showModal();
  form.elements.P.focus();
}

// ---------------------------------------------------------------- combined unload
// Unload population, IU, AU and land combat troops in one form (U / UG / LACT for a ship,
// FU / FUG / FLACT for a fleet).  Where it unloads decides the codes and the sequence:
//  - your own system: U, then LACT;
//  - an unowned empty system: the population unload first (it claims the system, as the
//    selection panel's "Claim" does: orders.claimOrders), then IU/AU (U) and troop landings;
//    IU/AU without population can't be unloaded there and are refused;
//  - another race's (or the rebels') system: P/IU/AU as gifts (UG), said in the form; troops
//    landing there attack it.
export function unloadPlan(target, where, a) {
  const ship = target.kind === "ship";
  const base = ship ? { ship: target.id } : { fleet: target.id };
  const gift = where === "foreign";
  const code = ship ? (gift ? "UG" : "U") : (gift ? "FUG" : "FU");
  const land = ship ? "LACT" : "FLACT";
  const out = [];
  for (const k of ["P", "I", "A"]) if (a[k] > 0) out.push({ code, ...base, item: k, amount: a[k] });
  for (const t of a.cts) out.push({ code: land, ...base, ct: t });
  return out;                       // P first: at an unowned system that is what claims it
}

export function openUnload(target) {
  if (!canOrder()) return;
  ensure();
  const all = target.kind === "ship" ? [S.view.ships.find(s => s.number === target.id)].filter(Boolean)
    : (() => { const f = findOwnFleet(target.id); return f ? S.view.ships.filter(s => f.ships.includes(s.number) && s.x === f.x && s.y === f.y) : []; })();
  const ships = all.filter(s => (s.cargo_capacity || 0) > 0);
  const label = target.kind === "ship" ? `ship ${target.id}${ships[0] ? ` (${ships[0].class})` : ""}` : `fleet ${target.id}`;
  if (!ships.length) { toast(`${label} has no cargo ships here.`, "error"); return; }
  const at = ships[0];
  const known = knownSystems().find(s => s.x === at.x && s.y === at.y);
  if (!known) { toast(`${label[0].toUpperCase()}${label.slice(1)} isn't at a system.`, "error"); return; }
  const own = S.view.systems.find(s => s.id === known.id);
  const where = own ? "own" : known.owner_kind === "unowned" ? "unowned" : "foreign";
  // prior unloads of this carrier in the draft
  const prior = [];
  S.draft.forEach((row, i) => {
    const d = rowToDict(row);
    const mine = target.kind === "ship" ? Number(d.ship) === target.id && ["U", "UG", "LACT"].includes(d.code)
      : d.fleet === target.id && ["FU", "FUG", "FLACT"].includes(d.code);
    if (mine) prior.push([i, d]);
  });
  // what is aboard where the new unloads go (in place of the old ones, or at the end): the draft
  // up to there, without the old unloads, so cargo an earlier drafted load puts aboard counts (W-31)
  const list = S.draft.map(rowToDict);
  const drop = new Set(prior.map(([i]) => i));
  const pos = prior.length ? prior[0][0] : list.length;
  const sim = replay(list, pos, drop);
  const aboard = { P: 0, I: 0, A: 0 }, aboard0 = { P: 0, I: 0, A: 0 }, onShip = new Map();
  for (const s of ships) {
    const c = sim.ship(s.number), c0 = s.cargo || {};
    aboard.P += Math.floor(c.POP + 1e-9); aboard.I += c.IU; aboard.A += c.AU;
    aboard0.P += Math.floor(c0.POP || 0); aboard0.I += c0.IU || 0; aboard0.A += c0.AU || 0;
    for (const t of c.CT) onShip.set(t, s.number);
  }
  const troops = S.view.troops.filter(t => onShip.has(t.number));
  const draftChanged = ships.some(s => sim.changed.has(s.number));
  const pre = { P: 0, I: 0, A: 0, troops: new Set() };
  for (const [, d] of prior) {
    if (d.code.endsWith("ACT")) pre.troops.add(Number(d.ct)); else pre[d.item] = (pre[d.item] || 0) + Number(d.amount || 0);
  }
  const sysName = known.name || "this system";
  const whereText = where === "own" ? `At your system ${sysName}.`
    : where === "unowned" ? `At ${sysName}, an unowned empty system: unloading population claims it, so the population unload goes first and the IU, AU and troops follow.`
    : `At ${sysName}, which belongs to ${known.owner_kind === "rebels" ? "the rebels" : `the ${known.owner_name || "another race"}`}: population, IU and AU are given to it as a gift (${target.kind === "ship" ? "UG" : "FUG"}), and landing combat troops there attacks it.`;
  const num = (item, name) => el("label", { class: "load-num" }, name,
    el("input", { type: "number", name: item, min: 0, max: aboard[item], step: 1, inputmode: "numeric", value: pre[item] || 0 }),
    el("span", { class: "dim" }, `${fmt(aboard[item])} aboard${aboard[item] !== aboard0[item] ? ` after your draft (${fmt(aboard0[item])} at the start of the turn)` : ""}`));
  const err = el("p", { class: "err", role: "alert" });
  const sum = el("div", { class: "load-meter", role: "status", "aria-live": "polite" });
  const ok = el("button", { type: "submit", class: "primary" }, prior.length ? "Replace orders" : "Add orders");
  const form = el("form", { method: "dialog", class: "form" },
    el("h2", { id: "loadH" }, `Unload ${label}`),
    el("p", { class: `hint${where === "foreign" ? " warnc" : ""}`, id: "unloadWhere" }, whereText),
    draftChanged ? el("p", { class: "hint", id: "unloadAfter" }, `Counting the earlier cargo orders in your draft: what they put aboard can be unloaded too${target.kind === "fleet" ? " (for a fleet, an estimate)" : ""}.`) : null,
    prior.length ? el("p", { class: "hint" }, `Your draft already unloads this ${target.kind}: ${prior.length === 1 ? "that order is" : `those ${prior.length} orders are`} shown here and will be replaced.`) : null,
    el("div", { class: "load-nums" }, num("P", "Population"), num("I", "IU"), num("A", "AU")),
    el("fieldset", { class: "load-troops" }, el("legend", {}, "Combat troops aboard"),
      troops.length ? el("div", { class: "checks" }, troops.map(t => el("label", {}, el("input", { type: "checkbox", name: "ct", value: t.number, checked: pre.troops.has(t.number) }), `${t.number} ${troopName(t.type)} (aboard ${onShip.get(t.number)}${t.ship ? "" : ", loaded by your draft"})`)))
        : el("p", { class: "dim" }, "None aboard.")),
    sum, err,
    el("div", { class: "row-end gap" }, el("button", { type: "button", class: "ghost", onclick: () => dlg.close() }, "Cancel"), ok));
  const read = () => {
    const v = k => Math.max(0, Math.floor(Number(form.elements.namedItem(k).value) || 0));
    const cts = [...form.querySelectorAll("input[name=ct]:checked")].map(x => Number(x.value));
    return { P: v("P"), I: v("I"), A: v("A"), T: cts.length, cts };
  };
  const update = () => {
    const a = read();
    const problems = [];
    for (const [k, n] of [["P", "population"], ["I", "IU"], ["A", "AU"]]) if (a[k] > aboard[k]) problems.push(`Only ${fmt(aboard[k])} ${n} aboard.`);
    if (["P", "I", "A"].some(k => Number(form.elements.namedItem(k).value) < 0)) problems.push("Amounts can't be negative.");
    if (where === "unowned" && !a.P && (a.I || a.A || a.T)) problems.push(`${sysName} isn't yours yet: unload population to claim it before unloading IU, AU or troops.`);
    const plan = unloadPlan(target, where, a);
    clear(sum, el("div", {}, plan.length ? `Orders, in this sequence: ${plan.map(d => d.code + (d.item ? ` ${d.item} ${d.amount}` : ` ${d.ct}`)).join(", ")}` : "Nothing to unload yet."));
    err.textContent = problems.join(" ");
    ok.disabled = problems.length > 0 || (!plan.length && !prior.length);
    return problems.length === 0;
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    if (!update()) return;
    const made = unloadPlan(target, where, read());
    const out = [];
    list.forEach((d, i) => { if (i === pos) out.push(...made); if (!drop.has(i)) out.push(d); });
    if (pos >= list.length) out.push(...made);
    try {
      await saveDraft(out);
      dlg.close();
      toast(made.length ? `${prior.length ? "Replaced with" : "Added"} ${made.length} unload order${made.length === 1 ? "" : "s"}${where === "unowned" && read().P ? ": the population lands first and claims the system" : ""}.` : "Unload orders removed.", "good");
    } catch (e) { err.textContent = e.message; }
  });
  clear(dlg, form);
  update();
  if (!dlg.open) dlg.showModal();
  form.elements.P.focus();
}
