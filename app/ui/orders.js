// Orders: forms generated from /api/orders/catalogue, the draft list (edit, delete, reorder),
// "Check orders", submit / withdraw, and the classic text pane for veterans.
"use strict";
import { S, BOARD, fleetSpeed, api, el, clear, $, toast, emit, on, canOrder, isHistory, confirmBox, ApiError, seatName, shipClass, troopName, techName, xy, giftableRaces, NOT_AT_WAR_CODES } from "./core.js";
import { knownSystems, ownFleets, findOwnFleet, placeName, draftShipCount } from "./world.js";
import { helpFor } from "./help.js";

let mapRef = null;
export function setMap(m) { mapRef = m; }
export const catEntry = code => S.catalogue.orders.find(o => o.code === code);

// ---------------------------------------------------------------- draft rows <-> order dicts
// The server's draft rows are {code, ...args, text: classic text}.  For ECHO and MESSAGE "text"
// is also an argument, so recover the argument from the classic text.
export function rowToDict(row) {
  const d = { ...row };
  if (row.code === "MESSAGE") {
    const lines = String(row.text).split("\n");
    d.text = lines.slice(1, lines[lines.length - 1] === "." ? -1 : undefined).join("\n");
  } else if (row.code === "ECHO") {
    d.text = String(row.text).replace(/^ECHO ?/, "");
    if (!d.text) delete d.text;
  } else delete d.text;
  return d;
}

export async function loadDraft() {
  const r = await api(`/api/games/${S.gid}/orders`, { gid: S.gid });
  S.draft = r.orders; S.submitted = r.submitted; S.checks = null;
  emit("draft");
}

// Replace the whole draft.  Throws ApiError (422 with per-order errors) on bad orders.
export async function saveDraft(dicts) {
  const r = await api(`/api/games/${S.gid}/orders`, { method: "PUT", gid: S.gid, body: { orders: dicts } });
  const was = S.submitted;
  S.draft = r.orders; S.submitted = r.submitted; S.checks = null;
  if (was && r.withdrawn) toast("Your submission was withdrawn because the orders changed. Submit again when ready.", "info", 6000);
  emit("draft");
  return r;
}
const dicts = () => S.draft.map(rowToDict);
export async function addOrder(d, at) {
  const list = dicts();
  if (at === undefined) list.push(d); else list.splice(at, 0, d);
  return saveDraft(list);
}
// Claim an unowned, empty system with a transport: land its population first (that is what
// captures the system), then unload its IUs and AUs.  Unloading IU/AU before the population
// fails, because the system isn't yours yet.  Any unloads of this ship already in the draft
// stay, after the new population order; cargo they already cover is not unloaded twice.
export function claimOrders(list, ship) {
  const c = ship.cargo || {};
  const pop = Math.floor(c.POP || 0);
  if (pop < 1) return null;
  const n = ship.number;
  const isUnload = d => d.code === "U" && Number(d.ship) === n;
  const planned = { P: 0, I: 0, A: 0 };
  for (const d of list) if (isUnload(d)) planned[d.item] = (planned[d.item] || 0) + Number(d.amount || 0);
  const out = list.slice();
  const first = out.findIndex(isUnload);
  const landPop = pop - planned.P;
  if (landPop > 0) out.splice(first < 0 ? out.length : first, 0, { code: "U", ship: n, item: "P", amount: landPop });
  else if (first >= 0) {
    // the draft already lands population, but maybe after IU/AU: move its P unloads first
    const ps = out.filter(d => isUnload(d) && d.item === "P");
    const rest = out.filter(d => !(isUnload(d) && d.item === "P"));
    rest.splice(rest.findIndex(isUnload) < 0 ? rest.length : rest.findIndex(isUnload), 0, ...ps);
    out.splice(0, out.length, ...rest);
  }
  for (const [item, have] of [["I", c.IU || 0], ["A", c.AU || 0]]) {
    const left = have - planned[item];
    if (left > 0) out.push({ code: "U", ship: n, item, amount: left });
  }
  return out;
}
export async function claimSystem(ship) {
  const list = claimOrders(dicts(), ship);
  if (!list) throw new Error(`Ship ${ship.number} carries no population to land.`);
  return saveDraft(list);
}
export async function replaceOrder(i, d) { const list = dicts(); list[i] = d; return saveDraft(list); }
async function removeOrder(i) { const list = dicts(); list.splice(i, 1); return saveDraft(list); }
async function moveOrder(i, j) {
  const list = dicts();
  if (j < 0 || j >= list.length) return;
  const [o] = list.splice(i, 1); list.splice(j, 0, o);
  return saveDraft(list);
}

export async function checkOrders(quiet = false) {
  try {
    const sig = draftSig();
    const r = await api(`/api/games/${S.gid}/orders/check`, { method: "POST", gid: S.gid });
    S.checks = r.results;
    S.advice = r.advice || []; S.adviceSig = sig;
    emit("draft"); emit("advice");
    if (quiet === true) return;
    const bad = r.results.filter(x => !x.ok).length, warn = S.advice.length;
    const w = warn ? `${warn} warning${warn > 1 ? "s" : ""} (⚠)` : "";
    toast(bad ? `${bad} order${bad > 1 ? "s have" : " has"} a problem${w ? `, and ${w}` : ""}. See the Orders tab.`
      : warn ? `All orders can run, with ${w}. See the Orders tab.` : r.results.length ? "All orders check out." : "No orders to check.", bad ? "error" : warn ? "info" : "good");
    emit("showTab", "orders");
  } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- advice (DECISIONS G-20)
// Non-blocking warnings from the server's dry run (engine/advice.py): a load/unload after a warp
// of the same unit, cargo unloaded where the draft loaded it before the unit moves, a name a
// rename in the draft changes.  Fetched quietly whenever the draft
// changes, so the draft list and the top bar's Check button show them without pressing Check;
// they never block Submit.
const draftSig = () => S.draft.map(r => r.text).join("\n");
let adviceTimer = null;
function scheduleAdvice() {
  if (!S.view || !S.gid || !canOrder()) { if (S.advice && S.advice.length) { S.advice = []; S.adviceSig = null; emit("advice"); } return; }
  const sig = draftSig();
  if (sig === S.adviceSig) return;
  clearTimeout(adviceTimer);
  if (!S.draft.length) { S.advice = []; S.adviceSig = sig; emit("advice"); return; }
  adviceTimer = setTimeout(async () => {
    try {
      const r = await api(`/api/games/${S.gid}/orders/check`, { method: "POST", gid: S.gid });
      if (draftSig() !== sig) return;               // the draft changed meanwhile: a newer fetch follows
      S.advice = r.advice || []; S.adviceSig = sig;
      emit("advice");
    } catch { /* advice is a nicety: never get in the way */ }
  }, 250);
}
on("draft", scheduleAdvice);
export const adviceFor = i => (S.advice || []).filter(a => a.index === i);
// A fix either rewrites the order (`fix.order`, renames) or moves it (`fix.move_to`, a cargo
// order put before the warp that moved its unit).
const fixTitle = f => f.order ? `Rewrite this order as: ${classicText(f.order)}` : `Move this order to position ${f.move_to + 1}`;
async function applyFix(i, fix) {
  const had = !!S.checks;
  try {
    if (fix.order) {
      await replaceOrder(i, fix.order);
      toast(`Order ${i + 1} now reads: ${classicText(fix.order)}`, "good", 3000);
    } else {
      await moveOrder(i, fix.move_to);
      toast(`Moved order ${i + 1} to position ${fix.move_to + 1}.`, "good", 3000);
    }
    if (had) await checkOrders(true);
  } catch (e) { toast(e.message, "error"); }
}

export async function submitTurn() {
  try {
    if (S.submitted) {
      await api(`/api/games/${S.gid}/submit`, { method: "DELETE", gid: S.gid });
      S.submitted = false;
      toast("Submission withdrawn. You can keep editing.");
      emit("draft"); emit("refreshSummary");
      return;
    }
    if (!S.draft.length && !(await confirmBox("Submit with no orders?", "Your empire will give no orders this turn. It still produces, grows and pays upkeep.", "Submit anyway"))) return;
    const r = await api(`/api/games/${S.gid}/submit`, { method: "POST", gid: S.gid });
    if (r.turn_ran) { toast(`Everyone is in. Turn ${r.turn} has run.`, "good"); emit("newTurn"); }
    else { S.submitted = true; toast(`Submitted. Waiting for ${r.waiting_for.map(seatName).join(", ")}.`, "good", 6000); emit("draft"); emit("refreshSummary"); }
  } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- pickers from the view
function ownShipOptions(filter) {
  return S.view.ships.filter(filter || (() => true)).sort((a, b) => a.number - b.number).map(s =>
    [s.number, `${s.number} ${s.class} @${placeName(s.x, s.y)}${s.fleet ? ` [${s.fleet}]` : ""}`]);
}
function techOptions(code, argName) {
  const have = new Set(S.view.empire.techs);
  const all = S.ref.techs.filter(t => t.id > 0);
  const buyable = t => !have.has(t.id) && t.prereqs.every(p => have.has(p));
  let list;
  if ((code === "GT") || (code === "TTNPR" && argName === "give")) list = all.filter(t => have.has(t.id));
  else if (code === "PT" || code === "CRP") list = [...all.filter(buyable), ...all.filter(t => !have.has(t.id) && !buyable(t))];
  else list = all.filter(t => !have.has(t.id));
  return list.map(t => [t.id, `${t.id} ${t.name} (${t.cost * (code === "CRP" ? 2 : 1)} EU)${!have.has(t.id) && !buyable(t) && (code === "PT" || code === "CRP") ? " - needs prerequisites" : ""}`]);
}
// the combat troops an order can use: on the ground for loading, aboard for landing
function troopOptions(code, values) {
  const where = t => t.ship ? `aboard ${t.ship}` : `at ${S.view.systems.find(s => s.id === t.system)?.name || "?"}`;
  let list = S.view.troops;
  // troops the draft moves this turn count too (W-31): orders run in draft order, so a troop a
  // drafted LACT/FLACT lands can be loaded again, and one a drafted LOCT/FLOCT loads can be landed
  const drafted = codes => new Set(dicts().filter(d => codes.includes(d.code)).map(d => Number(d.ct)));
  const f = code === "FLACT" ? findOwnFleet(values.fleet) : null;
  const boardedHere = () => new Set(dicts().filter(d => (d.code === "LOCT" && (code === "LACT" ? Number(d.ship) === Number(values.ship) : !f || f.ships.includes(Number(d.ship))))
    || (d.code === "FLOCT" && (code === "LACT" ? (findOwnFleet(d.fleet)?.ships || []).includes(Number(values.ship)) : !f || d.fleet === f.name))).map(d => Number(d.ct)));
  if (code === "LOCT" || code === "FLOCT") { const landed = drafted(["LACT", "FLACT"]); list = list.filter(t => (!t.ship || landed.has(t.number)) && t.type !== "M"); }
  else if (code === "LACT" && values.ship !== undefined && values.ship !== "") { const b = boardedHere(); list = list.filter(t => t.ship === Number(values.ship) || b.has(t.number)); }
  else if (code === "LACT") { const b = drafted(["LOCT", "FLOCT"]); list = list.filter(t => t.ship || b.has(t.number)); }
  else if (code === "FLACT") { const b = boardedHere(); list = list.filter(t => (t.ship && (!f || f.ships.includes(t.ship))) || b.has(t.number)); }
  return list.map(t => [t.number, `${t.number} ${troopName(t.type)} ${where(t)}`]);
}
function raceOptions(code) {
  // GS is never offered for a race you are at war with (your own stance; theirs is hidden)
  return giftableRaces(code).map(r => [r.name, `${r.name} (${r.kind === "npr" ? "computer" : r.kind})`]);
}
// system orders, plus the orders whose destination must be your own system (ML, WTP, WTPF)
const OWN_SYSTEM_CODES = new Set(["NSY", "CSP", "CAP", "CAPN", "SISD", "CI", "BCU", "BS", "BI", "DI", "BT", "DT", "BSP", "DSP", "TP", "SR", "SSI", "ML", "WTP", "WTPF"]);

function choiceSelect(name, options, value, optional, extraAttrs = {}) {
  const s = el("select", { name, id: `f_${name}`, ...extraAttrs });
  if (optional) s.append(el("option", { value: "" }, "(default)"));
  for (const [v, label] of options) s.append(el("option", { value: String(v), selected: value !== undefined && String(value) === String(v) }, label));
  if (!optional && value === undefined && !options.length) s.append(el("option", { value: "" }, "(none available)"));
  return s;
}

function buildField(entry, a, values) {
  const code = entry.code, name = a.name, val = values[name];
  const id = `f_${name}`;
  let control, extra = null;
  const numberInput = (lo, hi) => el("input", { type: "number", name, id, inputmode: "numeric", min: lo ?? undefined, max: hi ?? undefined, value: val ?? "", required: !a.optional });
  if (code === "TTNPR" && (name === "give" || name === "want")) {
    // a tech, or "Any tech costing..." with a cost picker below (Dave 2026-11-19, DECISIONS G-23)
    const opts = techOptions(code, name);
    const any = ttnprAny(values, name, opts.length);
    control = choiceSelect(name, [...opts, ["ANY", "Any tech costing..."]], any ? "ANY" : val, false);
  } else if (code === "TTNPR" && (name === "give_any_cost" || name === "want_any_cost")) {
    const side = name.split("_")[0];
    if (!ttnprAny(values, side, techOptions(code, side).length)) return el("div", { class: "field", hidden: true });
    const have = new Set(S.view.empire.techs);
    const opts = anyCostOptions(entry).map(c => {
      const all = S.ref.techs.filter(t => t.id > 0 && t.id < 51 && t.cost === c);
      const mine = all.filter(t => have.has(t.id)).length;
      const note = side === "give" ? `you own ${mine} of ${all.length}` : `you lack ${all.length - mine} of ${all.length}`;
      return [c, `${c} EU (${note})`];
    });
    control = choiceSelect(name, opts, val ?? defaultAnyCost(entry, side), false);
  } else if (a.kind === "choice" && name === "artifact" && code === "BT") {
    // Dave 2026-11-15: leave out what the chosen system already has; keep the ones it can't
    // afford yet (a transport may bring the IUs), marked with the shortfall.
    const have = new Set(S.view.empire.techs);
    const sysName = values.system ?? (S.view.systems[0] && S.view.systems[0].name);
    const sys = S.view.systems.find(q => q.name === sysName);
    const onSys = new Set(sys ? sys.artifacts : []);
    const eu = S.view.empire.eu;
    const ready = [], short = [], locked = [];
    for (const c of a.choices) {
      const label0 = `${c} - ${a.labels[c] || c}`;
      if (c === "S") { ready.push([c, `${label0} (spy)`]); continue; }
      if (onSys.has(c)) continue;
      const r = S.ref.artifacts.find(t => t.key === c);
      if (!r) continue;
      if (c === "EESS" && !onSys.has("ESS")) continue;          // only where the ESS already stands
      const cost = `${r.iu_cost} IU, ${r.eu_cost} EU`;
      if (!have.has(r.tech)) { locked.push([c, `${label0} (${cost}) - needs ${techName(r.tech)}`]); continue; }
      const gaps = [];
      if (sys && sys.iu < r.iu_cost) gaps.push(`${r.iu_cost - sys.iu} IU short here`);
      if (eu < r.eu_cost) gaps.push(`${r.eu_cost - eu} EU short`);
      (gaps.length ? short : ready).push([c, `${label0} (${cost})${gaps.length ? ` - ${gaps.join(", ")}` : ""}`]);
    }
    const s = el("select", { name, id });
    if (a.optional) s.append(el("option", { value: "" }, "(default)"));
    for (const [label, list] of [["Can build now", ready], ["Not enough resources here yet", short], ["Needs a technology", locked]]) {
      if (!list.length) continue;
      s.append(el("optgroup", { label }, list.map(([c, l]) => el("option", { value: c, selected: val !== undefined && String(val) === c }, l))));
    }
    if (!s.querySelector("option")) s.append(el("option", { value: "" }, sys ? `${sys.name} already has every artifact you could build` : "(none available)"));
    control = s;
  } else if (a.kind === "choice" && name === "type" && (code === "BS" || code === "BCU")) {
    // what the empire can build now first, with costs; the rest marked with the tech they need
    const have = new Set(S.view.empire.techs);
    const table = code === "BS" ? S.ref.ships : code === "BCU" ? S.ref.troops : S.ref.artifacts;
    const keyOf = r => r.code || r.key;
    const rows = a.choices.map(c => {
      const r = table.find(t => keyOf(t) === c) || { tech: 0 };
      const ok = have.has(r.tech);
      const stats = code === "BS" ? ` A${r.attack}/D${r.defense} mv${r.move}${r.cargo ? ` cargo ${r.cargo}` : ""}` : code === "BCU" ? ` A${r.attack}/D${r.defense}` : "";
      return [c, `${c} - ${a.labels[c] || r.name || c} (${r.iu_cost ?? "?"} IU, ${r.eu_cost ?? "?"} EU${stats})${ok ? "" : ` - needs ${techName(r.tech)}`}`, ok];
    });
    const s = el("select", { name, id });
    if (a.optional) s.append(el("option", { value: "" }, "(default)"));
    const opt = (c, label, ok) => el("option", { value: c, class: ok ? null : "locked", selected: val !== undefined && String(val) === c }, label);
    if (code === "BS") {
      // Dave 2026-11-19 (DECISIONS G-22): by the rules' groups (scouts, transports, then the four
      // ship lines of the Mixed Fleet Bonus), and by tech level then cost within a group; the
      // ones still needing a technology stay in place, marked with it
      const byCode = Object.fromEntries(rows.map(r => [r[0], r]));
      const groups = S.ref.ship_groups || [];
      for (const g of groups) {
        const list = S.ref.ships.filter(t => t.group === g.key && byCode[t.code]).map(t => byCode[t.code]);
        if (!list.length) continue;
        const n = list.filter(r => r[2]).length;
        s.append(el("optgroup", { label: `${g.label} (${n ? `${n} of ${list.length} available` : "needs a technology"})` }, list.map(([c, l, ok]) => opt(c, l, ok))));
      }
      const rest = rows.filter(r => !S.ref.ships.some(t => t.code === r[0] && groups.some(g => g.key === t.group)));
      if (rest.length) s.append(el("optgroup", { label: "Other" }, rest.map(([c, l, ok]) => opt(c, l, ok))));
    } else {
      const og1 = el("optgroup", { label: "Available" }), og2 = el("optgroup", { label: "Needs a technology" });
      for (const [c, label, ok] of rows) (ok ? og1 : og2).append(opt(c, label, ok));
      s.append(og1); if (og2.children.length) s.append(og2);
    }
    control = s;
  } else if (a.kind === "choice") {
    const opts = a.choices.map(c => [c, a.labels && a.labels[c] ? `${c} - ${a.labels[c]}` : c]);
    control = choiceSelect(name, opts, val, a.optional);
  } else if (a.kind === "speed") {
    control = choiceSelect(name, [["A", "A - automatic (slowest ship)"], ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => [n, String(n)])], val ?? "A", false);
  } else if (a.kind === "ints") {
    const chosen = new Set((val || []).map(Number));
    const fleetName = values.fleet;
    const filt = code === "LF" && fleetName ? s => s.fleet === fleetName : code === "AF" ? s => s.fleet !== fleetName : null;
    control = el("div", { class: "checks", id, role: "group", "aria-label": "Ships" },
      ownShipOptions(filt).map(([n, label]) => el("label", {}, el("input", { type: "checkbox", name, value: n, checked: chosen.has(n) }), label)));
  } else if (a.kind === "list") {
    const chosen = new Set(val || []);
    const opts = raceOptions();
    control = el("div", { class: "checks", id, role: "group", "aria-label": "Recipients" },
      opts.length ? opts.map(([n, label]) => el("label", {}, el("input", { type: "checkbox", name, value: n, checked: chosen.has(n) }), label))
        : el("span", { class: "dim" }, "No contacted races yet: the message goes to every race."));
  } else if (a.kind === "text") {
    control = el("textarea", { name, id, rows: code === "MESSAGE" ? 6 : 2, maxlength: 4000 }, val ?? "");
  } else if (name === "ship" && code === "SL") {
    // SL: the system loads any ship in orbit, including other races' ships (rulebook "System
    // loads cargo onto a ship"), so offer scanned foreign ships at your systems too
    const mine = new Set(S.view.systems.map(s => `${s.x},${s.y}`));
    const foreign = S.view.scans.ships.filter(s => mine.has(`${s.x},${s.y}`) && s.owner !== S.view.empire.id)
      .map(s => [s.number, `${s.number} ${s.owner_name} ${shipClass(s.type)} @${placeName(s.x, s.y)}`]);
    control = choiceSelect(name, [...ownShipOptions(s => s.cargo_capacity > 0), ...foreign], val, a.optional);
  } else if (name === "ship") {
    control = choiceSelect(name, ownShipOptions(), val, a.optional);
  } else if (name === "ct") {
    control = choiceSelect(name, troopOptions(code, values), val, a.optional);
  } else if (code === "TP" && name === "amount" && values.item === "C") {
    // farcasting a combat troop: the "amount" is the troop's number
    const from = S.view.systems.find(s => s.name === values.system);
    const opts = S.view.troops.filter(t => !t.ship && (!from || t.system === from.id)).map(t => [t.number, `${t.number} ${troopName(t.type)}`]);
    control = choiceSelect(name, opts, val, a.optional);
  } else if (name === "spy") {
    control = choiceSelect(name, S.view.spies.map(s => [s.number, `Spy ${s.number}${s.system ? ` at ${systemLabel(s.system)}` : ""}`]), val, a.optional);
  } else if (name === "tech" || name === "give" || name === "want") {
    control = choiceSelect(name, techOptions(code, name), val, a.optional);
  } else if (name === "target") {
    const listId = `dl_${name}`;
    control = el("input", { type: "number", name, id, min: 0, value: val ?? "", list: listId, required: true });
    extra = el("datalist", { id: listId }, S.view.scans.ships.map(s => el("option", { value: s.number }, `${s.owner_name} ${shipClass(s.type)} @${placeName(s.x, s.y)}`)));
  } else if (name === "fleet") {
    control = choiceSelect(name, ownFleets().map(f => [f.name, `${f.name} (${draftShipCount(f)} ships @${placeName(f.x, f.y)})${f.forming ? " forming" : ""}`]), val, a.optional);
  } else if (name === "into" && code === "MGF") {
    // merge fleets (DECISIONS G-27): your other fleets on the same square as the first one
    control = choiceSelect(name, mergeTargets(values.fleet).map(f => [f.name, `${f.name} (${draftShipCount(f)} ships @${placeName(f.x, f.y)})${f.forming ? " forming" : ""}`]), val, a.optional);
  } else if (name === "leader") {
    control = choiceSelect(name, S.view.leaders.map(l => [l.name, `${l.name} (${l.status}${l.system ? `, ${systemLabel(l.system)}` : ""}${l.fleet ? `, fleet ${l.fleet}` : ""})`]), val, a.optional);
  } else if (name === "race") {
    const opts = raceOptions(code);
    control = opts.length || NOT_AT_WAR_CODES.has(code) ? choiceSelect(name, opts, val, a.optional) : el("input", { name, id, value: val ?? "", required: true, placeholder: "race name" });
  } else if ((name === "system" || name === "to") && (OWN_SYSTEM_CODES.has(code))) {
    control = choiceSelect(name, S.view.systems.map(s => [s.name, `${s.name} @${xy(s.x, s.y)}`]), val, a.optional);
  } else if (name === "system") {
    const listId = "dl_system";
    control = el("input", { name, id, value: val ?? "", list: listId, required: true, autocomplete: "off", placeholder: "system name" });
    extra = el("datalist", { id: listId }, knownSystems().filter(s => s.name).map(s => el("option", { value: s.name }, `${s.mine ? "yours" : s.owner_name || "unknown"} @${xy(s.x, s.y)}`)));
  } else if (name === "count" && (code === "BS" || code === "BCU")) {
    // how many to build (DECISIONS G-19): a number box, 1 by default
    control = el("input", { type: "number", name, id, inputmode: "numeric", min: a.lo ?? 1, max: a.hi ?? 50, step: 1, value: val ?? 1 });
  } else if (["int", "nat", "coord", "pct"].includes(a.kind)) {
    const lo = a.lo ?? (a.kind === "int" ? null : 0), hi = a.kind === "coord" ? BOARD - 1 : a.hi ?? (a.kind === "pct" ? 100 : null);
    control = numberInput(lo, hi);
  } else {
    control = el("input", { name, id, value: val ?? "", required: !a.optional, maxlength: 40 });
  }
  const label = el("label", { for: id, class: "lab" }, el("span", {}, fieldLabel(a)), a.optional && code !== "TTNPR" ? el("span", { class: "opt" }, "optional") : null);
  const help = a.help && a.help !== a.name ? el("span", { class: "fhelp", id: `${id}_h` }, a.help) : null;
  if (help && control.setAttribute) control.setAttribute("aria-describedby", `${id}_h`);
  const row = el("div", { class: "field-row" }, control);
  if (name === "y" && entry.args.some(x => x.name === "x")) {
    row.append(el("button", { type: "button", class: "small", onclick: () => pickOnMap(entry) }, "Pick on map"));
  }
  return el("div", { class: "field" }, label, row, extra, help);
}
// TTNPR "ANY <cost>" (DECISIONS G-23): is this side (give / want) ANY in these form values?
function ttnprAny(values, side, nTechs) {
  const c = values[`${side}_any_cost`];
  if (c !== undefined && c !== null && c !== "") return true;
  if (values[side] === "ANY") return true;
  return (values[side] === undefined || values[side] === "") && !nTechs;   // nothing else to pick
}
const anyCostOptions = entry => entry.any_costs || [...new Set(S.ref.techs.filter(t => t.id > 0 && t.id < 51).map(t => t.cost))].sort((a, b) => a - b);
// the first cost with something to pick from the player's side: a tech of theirs to give, one
// they lack to want
function defaultAnyCost(entry, side) {
  const have = new Set(S.view.empire.techs);
  const costs = anyCostOptions(entry);
  return costs.find(c => S.ref.techs.some(t => t.id > 0 && t.id < 51 && t.cost === c && (side === "give") === have.has(t.id))) ?? costs[0];
}
const systemLabel = id => { const s = knownSystems().find(q => q.id === id); return s ? (s.name || xy(s.x, s.y)) : `#${id}`; };
function fieldLabel(a) {
  const L = { x: "X", y: "Y", au: "AU %", iu: "IU %", eu: "EU %", gc: "Ground combat points", rd: "Raid points", other: "Role for the other points", ct: "Combat troop", to: "To system", give: "Tech you give", want: "Tech you want", give_any_cost: "Any tech you give, costing", want_any_cost: "Any tech you want, costing" };
  return L[a.name] || a.name[0].toUpperCase() + a.name.slice(1);
}

function readForm(entry) {
  const f = $("orderForm");
  const d = { code: entry.code };
  for (const a of entry.args) {
    if (a.kind === "ints") { d[a.name] = [...f.querySelectorAll(`input[name="${a.name}"]:checked`)].map(i => Number(i.value)); continue; }
    if (a.kind === "list") { d[a.name] = [...f.querySelectorAll(`input[name="${a.name}"]:checked`)].map(i => i.value); continue; }
    // namedItem, not f.elements[name]: a field called "item" (L, U, TP...) would otherwise return the
    // collection's own item() method and the value would be silently dropped
    const c = f.elements.namedItem(a.name);
    if (!c) continue;
    let v = c.value;
    if (v === "" || v === undefined) continue;
    if (["int", "nat", "coord", "pct"].includes(a.kind)) v = Number(v);
    else if (a.kind === "speed" && v !== "A") v = Number(v);
    d[a.name] = v;
  }
  if (entry.code === "TTNPR") {
    // ANY sides (G-23): the select says "ANY", the cost comes from the field below it (or its
    // default while that field isn't shown yet); a tech number drops any cost left over
    for (const side of ["give", "want"]) {
      if (d[side] === "ANY" || Number.isNaN(d[side])) {
        delete d[side];
        if (d[`${side}_any_cost`] === undefined) d[`${side}_any_cost`] = defaultAnyCost(entry, side);
      } else if (d[side] !== undefined) delete d[`${side}_any_cost`];
    }
  }
  return d;
}
export function classicText(d) {
  const entry = catEntry(d.code);
  if (d.code === "MESSAGE") return `MESSAGE${(d.recipients || []).map(r => " " + r).join("")}\n${d.text || ""}\n.`;
  if (d.code === "TTNPR") {     // TTNPR <give|ANY cost> <want|ANY cost> <race> (G-23)
    const side = (t, c) => c !== undefined && c !== null && c !== "" ? `ANY ${c}` : (t ?? "");
    return ["TTNPR", side(d.give, d.give_any_cost), side(d.want, d.want_any_cost), d.race ?? ""].filter(x => x !== "").join(" ");
  }
  const parts = [d.code];
  for (const a of entry.args) {
    const v = d[a.name];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    if (a.name === "count" && Number(v) === 1) continue;        // the default, as the server writes it
    parts.push(Array.isArray(v) ? v.join(" ") : String(v));
  }
  return parts.join(" ");
}

// ---------------------------------------------------------------- the order dialog
let dlgState = null;    // {entry, index}
export function openOrder(code, values = {}, index) {
  if (!canOrder()) { toast(isHistory() ? "You are looking at an earlier turn. Go back to the current turn to give orders." : "This empire can't give orders now.", "error"); return; }
  const entry = catEntry(code);
  if (!entry) return;
  dlgState = { entry, index };
  $("orderH").textContent = describeOrder(entry);
  $("orderCode").textContent = entry.usage;
  $("orderHelp").textContent = entry.help && entry.help !== describeOrder(entry) ? entry.help : "";
  const fields = $("orderFields");
  clear(fields, entry.args.map(a => buildField(entry, a, values)));
  if (!entry.args.length) fields.append(el("p", { class: "hint" }, "This order has no options."));
  if (code === "CSP") fields.append(el("p", { class: "hint", id: "cspSum" }));
  if (code === "BS" || code === "BCU") fields.append(el("p", { class: "hint", id: "buildSum", "aria-live": "polite" }));
  const more = helpFor(code);
  $("orderMore").hidden = !more;
  if (more) clear($("orderMoreBody"), more);
  $("orderErr").textContent = "";
  $("orderOk").textContent = index === undefined ? "Add order" : "Save changes";
  const upd = () => {
    const d = readForm(entry);
    $("orderPreview").textContent = classicText(d);
    if (code === "BS" || code === "BCU") $("buildSum").textContent = buildSummary(code, d);
    if (code === "CSP") { const s = (d.au || 0) + (d.iu || 0) + (d.eu || 0); $("cspSum").textContent = `Total ${s}% ${s === 100 ? "✓" : "(must be 100)"}`; $("cspSum").className = s === 100 ? "hint ok" : "hint warnc"; }
  };
  $("orderForm").oninput = upd;
  $("orderForm").onchange = ev => {
    const dep = { AF: ["fleet"], LF: ["fleet"], MGF: ["fleet"], FLACT: ["fleet"], LACT: ["ship"], TP: ["item", "system"], BT: ["system"], TTNPR: ["give", "want"] }[code];
    if (dep && dep.includes(ev.target.name)) { openOrder(code, readForm(entry), index); return; }
    upd();
  };
  upd();
  const dlg = $("orderDlg");
  if (!dlg.open) dlg.showModal();
  const first = fields.querySelector("input, select, textarea");
  (first || $("orderOk")).focus();
}
// "3 Transports: 60 IU and 60 EU in all; the class 2 starport at H615 has room for 2 more this
// turn (the draft's other builds there counted)".  An estimate: Check runs the real engine.
function buildSummary(code, d) {
  const n = Math.max(1, Number(d.count) || 1);
  const r = (code === "BS" ? S.ref.ships : S.ref.troops).find(t => t.code === d.type);
  const sys = S.view.systems.find(q => q.name === d.system);
  if (!r) return "";
  const m = sys && sys.status === "UA" ? 2 : 1;
  const unit = code === "BS" ? 1 : 0.5;
  const what = code === "BS" ? (n === 1 ? r.name : `${n} ${/s$/i.test(r.name) ? r.name : r.name + "s"}`) : `${n} ${r.name} troop${n === 1 ? "" : "s"}`;
  let txt = `${what}: ${n * r.iu_cost * m} IU and ${n * r.eu_cost * m} EU${n > 1 ? " in all" : ""}${m > 1 ? " (double: under attack)" : ""}.`;
  if (sys) {
    const used = S.draft.filter((o, i) => i !== dlgState?.index && o.system === sys.name && (o.code === "BS" || o.code === "BCU"))
      .reduce((a, o) => a + (o.code === "BCU" ? 0.5 : 1) * (Number(o.count) || 1), 0);
    const room = Math.max(0, Math.floor((sys.starport - used) / unit + 1e-9));
    txt += ` The class ${sys.starport} starport at ${sys.name} has room for ${room} more this turn${used ? " (counting the draft's other builds there)" : ""}.`;
    if (room < n) txt += room ? ` Only ${room} would be built; the rest stop there.` : " None can be built there this turn.";
  }
  return txt;
}
export function describeOrder(entry) {
  return (entry.help || entry.code).split(/[.:(]/)[0].trim();
}

async function pickOnMap(entry) {
  if (!mapRef) return;
  const values = readForm(entry);
  const st = dlgState;
  $("orderDlg").close();
  let from = null;
  if (values.ship !== undefined) { const s = S.view.ships.find(q => q.number === values.ship); if (s) from = { x: s.x, y: s.y, speed: s.move, label: `Ship ${s.number}`, ship: s.number }; }
  if (values.fleet) { const f = findOwnFleet(values.fleet); if (f) from = { x: f.x, y: f.y, speed: fleetSpeed(f) || 1, label: `Fleet ${f.name}`, fleet: f.name }; }
  const p = mapRef.pickSquare(`Click the destination for ${describeOrder(entry).toLowerCase()}`);
  if (mapRef.pick) mapRef.pick.from = from;
  const w = await p;
  if (w) { values.x = w.x; values.y = w.y; }
  openOrder(entry.code, values, st.index);
}

export function initOrderDialog() {
  $("orderForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    if (!dlgState) return;
    const d = readForm(dlgState.entry);
    const btn = $("orderOk");
    btn.disabled = true;
    try {
      if (dlgState.index === undefined) await addOrder(d); else await replaceOrder(dlgState.index, d);
      $("orderDlg").close();
      toast(`${dlgState.index === undefined ? "Added" : "Updated"}: ${classicText(d).split("\n")[0]}`, "good", 2500);
    } catch (e) {
      $("orderErr").textContent = e instanceof ApiError && e.detail && e.detail.errors ? e.detail.errors.map(x => x.error).join("; ") : e.message;
    } finally { btn.disabled = false; }
  });
}

// ---------------------------------------------------------------- the Orders panel
let dragFrom = null;
export function renderOrdersPanel(box) {
  const v = S.view;
  // keep anything typed in the classic pane across re-renders (polling, draft changes)
  const old = box.querySelector("#classicText");
  const keep = old && old.dataset.dirty === "1" ? { value: old.value, focus: document.activeElement === old, a: old.selectionStart, b: old.selectionEnd } : null;
  clear(box);
  if (!v) return;
  box.append(el("h2", {}, `Orders for turn ${v.current_turn + 1}`));
  if (isHistory()) {
    box.append(el("p", { class: "hint" }, `You are viewing turn ${v.game.turn}. Orders are for the current turn; the draft below is still editable.`));
  }
  if (v.game.winner) box.append(el("p", { class: "warnc" }, `The game is over: the ${v.game.winner_name} have won.`));
  if (!v.seat.needs_orders) box.append(el("p", { class: "warnc" }, "Your empire no longer gives orders."));
  const mayEdit = v.seat.needs_orders && !v.game.winner;

  // submit bar
  const waiting = S.summary ? S.summary.waiting_for.filter(s => s !== v.seat.seat) : [];
  box.append(el("div", { class: "submit-bar" },
    el("span", { class: "state" }, S.submitted
      ? el("span", { class: "ok" }, "✓ Submitted", waiting.length ? el("span", { class: "dim" }, ` · waiting for ${waiting.map(seatName).join(", ")}`) : null)
      : el("span", { class: "warnc" }, "Not submitted yet")),
    el("button", { type: "button", class: "ghost", onclick: checkOrders, disabled: !mayEdit }, "Check orders",
      (S.advice || []).length ? el("span", { class: "warn-count" }, `⚠ ${S.advice.length}`) : null),
    el("button", { type: "button", class: S.submitted ? "ghost" : "primary", onclick: submitTurn, disabled: !mayEdit }, S.submitted ? "Withdraw" : "Submit turn")));

  // add an order
  const sel = el("select", { id: "addOrderSel", "aria-label": "Order to add" });
  const cats = S.catalogue.categories;
  for (const [cat, label] of Object.entries(cats)) {
    const og = el("optgroup", { label });
    for (const o of S.catalogue.orders.filter(o => o.category === cat)) og.append(el("option", { value: o.code }, `${describeOrder(o)} (${o.code})`));
    sel.append(og);
  }
  box.append(el("div", { class: "add-order" }, sel,
    el("button", { type: "button", onclick: () => openOrder(sel.value), disabled: !mayEdit }, "New order…")));
  box.append(el("p", { class: "hint" }, "Tip: select a fleet or ship on the map, then right-click a square (or press M) to move it there. Systems have their own build buttons."));

  // the draft
  const list = el("ol", { class: "order-list", "aria-label": "Draft orders" });
  S.draft.forEach((row, i) => {
    const chk = S.checks && S.checks[i];
    const entry = catEntry(row.code);
    const adv = adviceFor(i);
    const item = el("li", { class: `order-item${chk ? (chk.ok ? (adv.length ? " good warn" : " good") : " bad") : adv.length ? " warn" : ""}`, draggable: mayEdit ? "true" : undefined, dataset: { i } },
      el("span", { class: "n" }, `${i + 1}.`),
      el("div", {},
        el("div", { class: "txt" }, row.text),
        entry ? el("div", { class: "desc" }, describeOrder(entry)) : null,
        chk ? el("div", { class: `chk ${chk.ok ? "ok" : "err"}` }, chk.ok ? `✓ ${chk.messages.join("; ") || "OK"}` : `✗ ${chk.error}`,
          !chk.ok && chk.fix && mayEdit ? el("button", { type: "button", class: "small fix", title: fixTitle(chk.fix), onclick: () => applyFix(i, chk.fix) }, `Fix: ${chk.fix.label}`) : null) : null,
        adv.map(a => el("div", { class: "chk advice", role: "note", dataset: { kind: a.kind } }, el("span", { "aria-hidden": "true" }, "⚠"), el("div", {}, el("span", { class: "sr-only" }, "Warning: "), el("span", { class: "atext" }, a.text),
          a.fix && mayEdit ? el("button", { type: "button", class: "small fix", title: fixTitle(a.fix), onclick: () => applyFix(i, a.fix) }, `Fix: ${a.fix.label}`) : null)))),
      el("div", { class: "btns" },
        el("button", { type: "button", title: "Move up", "aria-label": `Move order ${i + 1} up`, disabled: !mayEdit || i === 0, onclick: () => moveOrder(i, i - 1).catch(e => toast(e.message, "error")) }, "↑"),
        el("button", { type: "button", title: "Move down", "aria-label": `Move order ${i + 1} down`, disabled: !mayEdit || i === S.draft.length - 1, onclick: () => moveOrder(i, i + 1).catch(e => toast(e.message, "error")) }, "↓"),
        el("button", { type: "button", title: "Edit", "aria-label": `Edit order ${i + 1}`, disabled: !mayEdit || !entry, onclick: () => openOrder(row.code, rowToDict(row), i) }, "✎"),
        el("button", { type: "button", title: "Delete", "aria-label": `Delete order ${i + 1}`, disabled: !mayEdit, onclick: () => removeOrder(i).catch(e => toast(e.message, "error")) }, "✕")));
    item.addEventListener("dragstart", e => { dragFrom = i; item.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; });
    item.addEventListener("dragend", () => item.classList.remove("dragging"));
    item.addEventListener("dragover", e => { e.preventDefault(); item.classList.add("drop-before"); });
    item.addEventListener("dragleave", () => item.classList.remove("drop-before"));
    item.addEventListener("drop", e => {
      e.preventDefault(); item.classList.remove("drop-before");
      if (dragFrom !== null && dragFrom !== i) moveOrder(dragFrom, dragFrom < i ? i - 1 : i).catch(er => toast(er.message, "error"));
      dragFrom = null;
    });
    list.append(item);
  });
  if (!S.draft.length) list.append(el("li", { class: "hint" }, "No orders yet. Orders run in the order listed; a failed order changes nothing."));
  box.append(list);
  if (S.draft.length && mayEdit) box.append(el("div", { class: "row-end" }, el("button", { type: "button", class: "ghost small", onclick: async () => {
    if (!(await confirmBox("Clear all orders?", "This deletes every order in the draft (and withdraws a submission).", "Clear all", true))) return;
    await api(`/api/games/${S.gid}/orders`, { method: "DELETE", gid: S.gid });
    await loadDraft();
  } }, "Clear all")));

  // classic text pane
  const ta = el("textarea", { id: "classicText", spellcheck: "false", "aria-describedby": "classicHint", disabled: !mayEdit }, S.draft.map(r => r.text).join("\n"));
  ta.addEventListener("input", () => { ta.dataset.dirty = "1"; });
  if (keep) { ta.value = keep.value; ta.dataset.dirty = "1"; }
  const err = el("div", { class: "err", role: "alert", id: "classicErr" });
  const send = async () => {
    err.textContent = "";
    const text = ta.value;
    try {
      const r = await api(`/api/games/${S.gid}/orders`, { method: "PUT", gid: S.gid, body: { text } });
      S.draft = r.orders; S.submitted = false; S.checks = null;
      ta.dataset.dirty = "";
      if (r.warnings && r.warnings.length) toast(r.warnings.map(w => `line ${w.line}: ${w.warning}`).join("; "), "info", 7000);
      emit("draft");
      toast(`Draft now has ${r.orders.length} orders.`, "good");
    } catch (e) {
      err.textContent = e.detail && e.detail.errors ? e.detail.errors.map(x => `Line ${x.line ?? (x.index + 1)}: ${x.text} - ${x.error}`).join("\n") : e.message;
    }
  };
  box.append(el("details", { class: "section classic", open: localStorage.getItem("mhgcClassicOpen") === "1" || undefined,
    ontoggle: e => localStorage.setItem("mhgcClassicOpen", e.target.open ? "1" : "0") },
    el("summary", {}, el("h3", {}, "Classic order text")),
    el("p", { class: "hint", id: "classicHint" }, "Type or paste orders in the classic format, one per line (MESSAGE blocks end with a line holding a single dot). Lines starting with # are comments."),
    el("label", { for: "classicText", class: "sr-only" }, "Classic orders"), ta, err,
    el("div", { class: "row-end gap", style: { marginTop: ".4rem" } },
      el("button", { type: "button", class: "ghost", disabled: !mayEdit, onclick: () => { ta.value = S.draft.map(r => r.text).join("\n"); ta.dataset.dirty = ""; err.textContent = ""; } }, "Reset to draft"),
      el("button", { type: "button", disabled: !mayEdit, onclick: () => send() }, "Use this text as the draft"))));
  if (keep && keep.focus) { ta.focus(); ta.setSelectionRange(keep.a, keep.b); }
}

// The fleets a fleet can merge into (MGF, DECISIONS G-27): your other fleets on its square.
export function mergeTargets(name) {
  const f = findOwnFleet(name);
  if (!f) return [];
  return ownFleets().filter(g => g.name !== f.name && g.x === f.x && g.y === f.y);
}
