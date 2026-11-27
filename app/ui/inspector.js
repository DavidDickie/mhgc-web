// The selection inspector: what is on the selected square, and the orders that make sense for it.
// Selecting a fleet or ship makes it the "focused unit": Move then asks for a square on the map
// (or right-click / M on the map moves it directly).
"use strict";
import { S, HOME, el, clear, $, emit, fmt, xy, raceName, relColor, shipClass, troopName, canOrder, fleetSpeed, dist, toast, giftableRaces, NOT_AT_WAR_CODES, systemColor, systemOwnerLabel, habText, habAsOf, HAB_LABEL, byName } from "./core.js";
import { key, ownFleets, findOwnFleet, effectiveFleet, placeName, draftShipCount } from "./world.js";
import { openOrder, addOrder, claimSystem, replaceOrder, classicText, describeOrder, catEntry, saveDraft, rowToDict, mergeTargets } from "./orders.js";
import { cargoText } from "./panels.js";
import { battle } from "./report.js";
import { openLoad, openUnload } from "./loaddlg.js";

let mapRef = null;
export function initInspector(map) { mapRef = map; }

export function focusUnit() {
  const f = S.selection && S.selection.focus;
  if (!f || !S.view) return null;
  if (f.kind === "fleet") { const o = findOwnFleet(f.id); return o ? { kind: "fleet", obj: o } : null; }
  const o = S.view.ships.find(q => q.number === f.id);
  return o ? { kind: "ship", obj: o } : null;
}

// Move the focused unit to a square (from the map: right-click, M, or the Move button).
export async function moveFocusedTo(w) {
  const u = focusUnit();
  if (!u) { toast("Select one of your fleets or ships first, then pick where it should go.", "info"); return; }
  if (!canOrder()) { toast("You can only give orders on the current turn.", "error"); return; }
  let fleet = u.kind === "fleet" ? u.obj : null;
  if (u.kind === "ship") {
    const fn = effectiveFleet(u.obj);
    if (fn) {
      toast(`Ship ${u.obj.number} is ${u.obj.fleet === fn ? "in" : "joining"} fleet ${fn}; it moves with the fleet. Moving the fleet instead.`, "info", 5000);
      fleet = findOwnFleet(fn);
      if (!fleet) return;
    }
  }
  const d = fleet ? { code: "MF", fleet: fleet.name, x: w.x, y: w.y } : { code: "MO", ship: u.obj.number, x: w.x, y: w.y };
  // replace an earlier movement order for the same unit rather than stacking them
  const moveCodes = d.code === "MF" ? ["MF", "MFS", "FIS"] : ["MO", "MS", "I", "G"];
  const idKey = d.code === "MF" ? "fleet" : "ship";
  const list = S.draft.map(rowToDict);
  const i = list.findIndex(o => moveCodes.includes(o.code) && o[idKey] === d[idKey]);
  if (i >= 0) list[i] = d; else list.push(d);
  // a fleet this draft creates: its move order must come after the CF / CFXY that creates it
  // (orders run in draft order; an MF before the CF fails with "You don't have a fleet ...")
  if (fleet && fleet.forming) {
    const cf = list.findIndex(o => (o.code === "CF" || o.code === "CFXY") && o.name === fleet.name);
    const mf = list.indexOf(d);
    if (cf > mf) { list.splice(mf, 1); list.splice(cf, 0, d); }
  }
  try {
    await saveDraft(list);
    const sp = fleet ? fleetSpeed(fleet) : u.obj.move;
    const from = fleet || u.obj;
    const turns = sp ? Math.ceil(dist(from.x, from.y, w.x, w.y) / sp) : "?";
    if (fleet && fleet.forming && !fleet.canMoveNow)
      toast(`${classicText(d)}: fleet ${fleet.name} is made by CFXY, so its ships join it after movement. It sets off next turn (about ${turns} turn${turns === 1 ? "" : "s"} from then).`, "info", 7000);
    else toast(`${classicText(d)}  (about ${turns} turn${turns === 1 ? "" : "s"})`, "good", 3000);
  } catch (e) { toast(e.message, "error"); }
}

async function startMove(u) {
  if (!mapRef) return;
  const sp = u.kind === "fleet" ? fleetSpeed(u.obj) : u.obj.move;
  const label = u.kind === "fleet" ? `fleet ${u.obj.name}` : `ship ${u.obj.number}`;
  // show where the unit is before asking where it goes
  mapRef.ensureVisible(u.obj.x, u.obj.y);
  const p = mapRef.pickSquare(`Click where ${label} should go (it starts at the pink ring)`);
  mapRef.pick.from = { x: u.obj.x, y: u.obj.y, speed: sp, label: label[0].toUpperCase() + label.slice(1), ...(u.kind === "fleet" ? { fleet: u.obj.name } : { ship: u.obj.number }) };
  mapRef.dirty = true;
  const w = await p;
  if (w) await moveFocusedTo(w);
}

async function startIntercept(u) {
  const p = mapRef.pickSquare("Click a square with a foreign ship to intercept");
  const w = await p;
  if (!w) return;
  const q = mapRef.idx.get(key(w.x, w.y));
  const t = q && q.foreign[0];
  if (!t) { toast("No scanned foreign ship there.", "error"); return; }
  openOrder(u.kind === "fleet" ? "FIS" : "I", u.kind === "fleet" ? { fleet: u.obj.name, target: t.number } : { ship: u.obj.number, target: t.number });
}

const btn = (label, fn, cls) => el("button", { type: "button", class: cls, onclick: fn }, label);
const kv = pairs => el("dl", { class: "kv" }, pairs.filter(p => p && p[1] !== undefined && p[1] !== null && p[1] !== "").map(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
function draftFor(pred) {
  const rows = S.draft.map((o, i) => [o, i]).filter(([o]) => pred(o));
  if (!rows.length) return "";
  return el("div", { class: "hint" }, "Draft: ", rows.map(([o, i]) => el("code", { title: `order ${i + 1}` }, o.text.split("\n")[0])).reduce((a, x, i) => (i ? [...a, " · ", x] : [x]), []));
}
function moreOrders(category, prefill, label = "Other orders") {
  if (!canOrder()) return "";
  // no Gift ship unless some contacted race is one you are not at war with
  const opts = S.catalogue.orders.filter(o => o.category === category && !(NOT_AT_WAR_CODES.has(o.code) && !giftableRaces(o.code).length));
  const sel = el("select", { "aria-label": label }, opts.map(o => el("option", { value: o.code }, `${describeOrder(o)} (${o.code})`)));
  return el("div", { class: "field-row", style: { marginTop: ".3rem" } }, sel, btn("Order…", () => openOrder(sel.value, prefill), "small"));
}

export function renderInspector() {
  const box = $("inspector");
  const sel = S.selection;
  if (!sel || !S.view || !mapRef) { box.hidden = true; return; }
  const q = mapRef.idx.get(key(sel.x, sel.y)) || { x: sel.x, y: sel.y, system: null, fleets: [], ships: [], fleetShips: [], foreign: [], foreignFleets: [], combats: [] };
  const may = canOrder();
  const fu = focusUnit();
  clear(box);
  box.hidden = false;
  box.append(el("div", { class: "insp-head" },
    el("h2", {}, q.system && q.system.name ? q.system.name : "Deep space", el("span", { class: "dim", style: { fontWeight: 400, fontSize: ".85em" } }, `  ${xy(q.x, q.y)}`)),
    btn("✕", () => emit("deselect"), "icon-btn")));
  const distHome = dist(HOME, HOME, q.x, q.y);
  box.append(el("div", { class: "hint" }, `${distHome} square${distHome === 1 ? "" : "s"} from home`,
    fu && (fu.obj.x !== q.x || fu.obj.y !== q.y) ? ` · ${dist(fu.obj.x, fu.obj.y, q.x, q.y)} from ${fu.kind === "fleet" ? fu.obj.name : fu.obj.number}` : ""));
  if (fu && may && (fu.obj.x !== q.x || fu.obj.y !== q.y)) {
    box.append(el("div", { class: "actions" }, btn(`Send ${fu.kind === "fleet" ? `fleet ${fu.obj.name}` : `ship ${fu.obj.number}`} here`, () => moveFocusedTo(q), "primary")));
  }

  if (q.system) box.append(systemCard(q.system, q, may));
  for (const f of q.fleets) box.append(fleetCard(f, may));
  if (q.ships.length) box.append(shipList(q, may));
  if (q.foreign.length || q.foreignFleets.length) box.append(foreignCard(q, fu, may));
  for (const c of q.combats) box.append(battle(c, S.view));
  if (!q.system && !q.fleets.length && !q.ships.length && !q.foreign.length && !q.combats.length) {
    const c = mapRef.coverageOf(q.x, q.y);
    box.append(el("p", { class: "hint" }, c === "never" ? "Never scanned: there could be a system here you have not seen."
      : c === "past" ? "Nothing seen here. You scanned this square on an earlier turn, but it is outside your scans now."
      : "Nothing you can see here."));
  }
}

function systemCard(s, q, may) {
  const v = S.view;
  const own = s.kind === "own";
  const owner = own ? v.empire.name : systemOwnerLabel(s);
  const box = el("div", { class: `obj${S.selection.focus && S.selection.focus.kind === "system" ? " focus" : ""}` });
  box.append(el("h3", {}, el("span", { class: "sw", style: { background: own ? relColor(v.empire.id) : systemColor(s) } }), s.name || "Unnamed system",
    el("span", { class: "badge" }, own ? (s.x === HOME && s.y === HOME ? "home" : "yours") : s.kind === "memory" ? `seen turn ${s.last_seen}` : `${s.level} scan`)));
  if (own) {
    box.append(kv([
      ["Population", fmt(s.pop, 1)],
      ["Mood", `${s.happy_band} ${fmt(s.happy, 2)}${s.trend > 0 ? " ▲" : s.trend < 0 ? " ▼" : ""}`],
      ["Habitability", `${HAB_LABEL[s.hab] || s.hab} [${s.hab}] (${s.hab_value})${s.mr ? " · Metal rich [MR]" : ""}${s.ar ? " · Agriculture rich [AR]" : ""}`],
      ["Status", s.status], ["Starport", s.starport ? `class ${s.starport}` : "none"],
      ["Infrastructure", s.infra], ["Stockpile", `${s.au} AU · ${s.iu} IU`],
      ["Profile", `${s.profile.au}% AU · ${s.profile.iu}% IU · ${s.profile.eu}% EU`],
      ["AU release", s.au_release.mode === "pct" ? `${s.au_release.value}% a turn` : `${s.au_release.value} AU a turn`],
      ["Produced", `${s.production.au} AU · ${s.production.iu} IU · ${s.production.eu} EU (ate ${s.production.eaten})`],
      ["Scan range", s.scan_range], ["Governor", s.governor],
      ["Artifacts", s.artifacts.join(", ")], ["Trade", s.trade_routes.map(r => r.name).join(", ")],
    ]));
    const ground = groundNow(s, q, own);
    if (ground) box.append(ground);
    box.append(draftFor(o => o.system === s.name || o.to === s.name));
    if (may) {
      const n = s.name;
      box.append(el("div", { class: "actions" },
        btn("Build ship", () => openOrder("BS", { system: n }), "primary"),
        btn("Build troops", () => openOrder("BCU", { system: n })),
        btn("Profile", () => openOrder("CSP", { system: n, au: s.profile.au, iu: s.profile.iu, eu: s.profile.eu })),
        btn("Infrastructure", () => openOrder("BI", { system: n })),
        btn("Starport +1", () => openOrder("BSP", { system: n })),
        btn("Artifact", () => openOrder("BT", { system: n })),
        btn("AU release", () => openOrder("CAP", { system: n, amount: s.au_release.mode === "pct" ? s.au_release.value : undefined })),
        btn("IU to depot", () => openOrder("SISD", { system: n })),
        q.ships.length ? btn("Fleet from ships here", () => openOrder("CFXY", { x: s.x, y: s.y })) : null));
      box.append(moreOrders("system", { system: n }));
      // the troop orders (disband, salvage, posture) for your troops on this system
      const mineHere = s.troops.filter(t => t.owner === v.empire.id);
      if (mineHere.length) box.append(moreOrders("troop", { ct: mineHere[0].number }, "Troop orders"));
    }
  } else {
    box.append(kv([
      ["Owner", owner],
      s.kind === "memory" ? ["Last seen", `turn ${s.last_seen}${s.via === "cdrom" ? " (from a CD-ROM of Ancient Wisdom)" : ""}`] : null,
      ["Population", s.pop !== undefined ? fmt(s.pop, 1) : null], ["Mood", s.happy !== undefined ? fmt(s.happy, 2) : null],
      ["Habitability", habText(s) ? el("span", { class: s.kind === "memory" || habAsOf(s) ? "remembered" : "" },
        `${HAB_LABEL[s.hab] || s.hab} [${s.hab}]${s.mr ? " · Metal rich [MR]" : ""}${s.ar ? " · Agriculture rich [AR]" : ""}`,
        habAsOf(s) ? el("span", { class: "dim" }, ` (as of turn ${s.details_turn})`) : "") : "unknown (needs a short range scan)"],
      ["Status", s.status], ["Starport", s.starport], ["Infrastructure", s.infra],
      ["Stockpile", s.au !== undefined ? `${s.au} AU · ${s.iu} IU` : null], ["Artifacts", (s.artifacts || []).join(", ")],
      ["Leader", s.leader && (s.leader.name || String(s.leader))],
    ]));
    if (s.kind === "scan" && s.level === "long") box.append(el("p", { class: "hint" }, habText(s)
      ? `Long range scan: only the name, owner and position. Habitability and resources are from your short range scan on turn ${s.details_turn}.`
      : "Long range scan: only the name, owner and position. Get a short range scan for more."));
    if (s.kind === "memory" && habText(s)) box.append(el("p", { class: "hint" }, `Remembered from turn ${s.details_turn}: habitability can change (terraforming), so it may differ now.`));
    const ground = groundNow(s, q, own);
    if (ground) box.append(ground);
  }
  return box;
}

function fleetCard(f, may) {
  const v = S.view;
  const df = S.draftFleets;
  const focus = S.selection.focus && S.selection.focus.kind === "fleet" && S.selection.focus.id === f.name;
  const members = f.ships.map(n => v.ships.find(s => s.number === n)).filter(Boolean);
  const leaving = new Set(df ? members.filter(s => df.leaves.has(s.number) || (df.joins.has(s.number) && df.joins.get(s.number) !== f.name)).map(s => s.number) : []);
  const joining = !f.forming && df ? v.ships.filter(s => df.joins.get(s.number) === f.name && !f.ships.includes(s.number)) : [];
  const after = [...members.filter(s => !leaving.has(s.number)), ...joining];
  const box = el("div", { class: `obj${focus ? " focus" : ""}${f.forming ? " forming" : ""}`, "data-fleet": f.name });
  box.append(el("h3", {}, el("span", { class: "sw", style: { background: relColor(v.empire.id) } }),
    btn(`Fleet ${f.name}`, () => emit("focus", { kind: "fleet", id: f.name }), "link"),
    el("span", { class: "badge" }, `${after.length} ship${after.length === 1 ? "" : "s"}`),
    f.forming ? el("span", { class: "badge forming", title: "Created by this turn's draft" }, "forming") : null));
  if (f.forming) box.append(el("p", { class: "hint" }, f.canMoveNow
    ? "Forming: this turn's draft creates it (CF) and adds the ships (AF). Orders run before movement, so it can be given a move order now and sets off this turn."
    : "Forming by CFXY: your unfleeted ships on this square join it at the end of movement, so it can't move this turn. A move order given now is carried out from next turn. (Use Make fleet in the ship list to move it this turn.)"));
  const going = f.dest && (f.dest.x !== f.x || f.dest.y !== f.y) ? placeName(f.dest.x, f.dest.y) : f.order;
  const typ = s => S.ref.ships.find(t => t.code === s.type) || {};
  const atk = after.reduce((a, s) => a + (typ(s).attack || 0), 0);
  const dfn = after.reduce((a, s) => a + (typ(s).defense || 0), 0);
  box.append(kv([["Going", going], ["Speed", `${f.speed}${f.speed === "A" ? ` (${fleetSpeed(f)})` : ""}`], ["Posture / role", `${f.posture} / ${f.role}`],
    ["Attack / defence", `${atk} / ${dfn}`], ["Admiral", f.admiral], ["Ships", summarize(after.map(s => s.class))],
    joining.length ? ["Joining (draft)", joining.map(s => s.number).join(", ")] : null,
    df && df.merged && [...df.merged].some(([, b]) => b === f.name) ? ["Merging in (draft)", [...df.merged].filter(([, b]) => b === f.name).map(([a]) => `fleet ${a}`).join(", ")] : null,
    leaving.size ? ["Leaving (draft)", [...leaving].join(", ")] : null]));
  box.append(draftFor(o => o.fleet === f.name || (o.code === "MGF" && o.into === f.name) || ((o.code === "CF" || o.code === "CFXY") && o.name === f.name)));
  if (focus) {
    box.append(el("ul", { class: "unit-list" }, [...members, ...joining].map(s => el("li", {}, btn([`${s.number} ${s.class}`, el("span", { class: "dim" },
      leaving.has(s.number) ? "leaving" : joining.includes(s) ? "joining" : `${s.posture}/${s.role}${s.cargo ? " · " + cargoText(s) : ""}`)], () => emit("focus", { kind: "ship", id: s.number }))))));
    if (may) {
      const n = f.name;
      box.append(el("div", { class: "actions" },
        btn("Move (click map)", () => startMove({ kind: "fleet", obj: f }), "primary"),
        btn("Move to system", () => openOrder("MFS", { fleet: n })),
        btn("Intercept", () => startIntercept({ kind: "fleet", obj: f })),
        btn("Speed", () => openOrder("FS", { fleet: n, speed: f.speed })),
        btn("Posture", () => openOrder("CFP", { fleet: n })),
        btn("Role", () => openOrder("CFCR", { fleet: n })),
        btn("Load", () => openLoad({ kind: "fleet", id: n })),
        btn("Unload", () => openUnload({ kind: "fleet", id: n })),
        btn("Add ships", () => openOrder("AF", { fleet: n })),
        btn("Remove ships", () => openOrder("LF", { fleet: n })),
        mergeButton(f),
        f.forming ? btn("Cancel this fleet", () => cancelForming(f), "ghost") : btn("Disband", () => openOrder("DF", { fleet: n }), "ghost")));
      box.append(moreOrders("fleet", { fleet: n }));
    }
  } else box.append(el("div", { class: "actions" }, btn("Select", () => emit("focus", { kind: "fleet", id: f.name }), "small")));
  return box;
}

// "Merge into…" (MGF, DECISIONS G-27): pick another of your fleets on this square; the order is
// appended to the draft and the merged fleet is selected.  MGF acts at once, like AF, so the
// merged fleet moves this turn with the other fleet's orders.
function mergeButton(f) {
  const targets = mergeTargets(f.name);
  const b = el("button", { type: "button", id: "mergeIntoBtn", disabled: !targets.length,
    title: targets.length ? `Move all of ${f.name}'s ships into another of your fleets here; ${f.name} is then disbanded` : "No other fleet of yours on this square: fleets merge only at the same square" }, "Merge into…");
  b.onclick = () => {
    const card = b.closest(".obj");
    const old = card.querySelector(".merge-row");
    if (old) { old.remove(); return; }
    const sel = el("select", { id: "mergeSel", "aria-label": `Fleet to merge ${f.name} into` }, targets.map(g => el("option", { value: g.name }, `${g.name} (${draftShipCount(g)} ships)${g.forming ? " forming" : ""}`)));
    const ok = el("button", { type: "button", id: "mergeOk", class: "primary small" }, "Merge");
    ok.onclick = async () => {
      const into = sel.value;
      const d = { code: "MGF", fleet: f.name, into };
      try {
        await saveDraft([...S.draft.map(rowToDict), d]);
        toast(`${classicText(d)}: fleet ${f.name}'s ships join ${into} at once, and ${f.name} is disbanded. ${into} moves this turn with its own orders.`, "good", 6000);
        emit("focus", { kind: "fleet", id: into });
      } catch (e) { toast(e.message, "error"); }
    };
    card.querySelector(".actions").after(el("div", { class: "field-row merge-row", style: { marginTop: ".3rem" } },
      el("label", { for: "mergeSel" }, `Merge ${f.name} into `), sel, ok,
      el("span", { class: "hint" }, " all its ships move over; the other fleet keeps its name, posture, role, speed and orders")));
    sel.focus();
  };
  return b;
}

// Take a forming fleet out of the draft: its CF/CFXY and every order naming it.
async function cancelForming(f) {
  const list = S.draft.map(rowToDict);
  const keep = list.filter(o => !(o.fleet === f.name || ((o.code === "CF" || o.code === "CFXY") && o.name === f.name)));
  try {
    await saveDraft(keep);
    toast(`Fleet ${f.name} cancelled: ${list.length - keep.length} order${list.length - keep.length === 1 ? "" : "s"} removed from the draft.`, "info");
    if (S.selection) { S.selection.focus = null; emit("focus", null); }
  } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- Make fleet (2026-11-16)
// Fleet names: one token in the classic text (no spaces, no leading #), 12 characters at most
// (mhgc/orders.py), and different from your own fleets (including the ones this draft creates);
// other races may use the same names (Dave 2026-11-16, DECISIONS G-16).
const NAME_OK = /^[A-Za-z0-9_.\-]+$/;
export function fleetNameProblem(name) {
  const n = String(name || "");
  if (!n) return "Give the fleet a name.";
  if (n.length > 12) return `Fleet names can be at most 12 characters; this one has ${n.length}.`;
  if (!NAME_OK.test(n)) return "Use letters, digits and _ - . only (no spaces).";
  const own = ownFleets().find(f => f.name.toLowerCase() === n.toLowerCase());
  if (own) return own.name === n ? `You already have a fleet called ${n}${own.forming ? " (forming in this draft)" : ""}.` : `That is too close to your fleet ${own.name}; pick another name.`;
  return null;
}
export function defaultFleetName(q) {
  const sysName = q.system && q.system.name ? String(q.system.name).replace(/[^A-Za-z0-9]/g, "") : "";
  const base = (sysName || "TF").slice(0, 9);
  for (let i = 1; i < 1000; i++) {
    const n = `${base}${i}`.slice(0, 12);
    if (!fleetNameProblem(n)) return n;
  }
  return "";
}
// The orders for "Make fleet": CF <name> x y, then AF <name> <ships> (10 a line).  CF and AF act
// at once, before movement, so a later MF moves the new fleet this turn.  (CFXY would only
// collect the ships after movement.)  Appended to the draft, so anything else already there for
// these ships runs first; their own move orders (MO/MS/I/G) would be overridden by the fleet's,
// so they are dropped when dropMoves is set.
export function makeFleetOrders(list, name, x, y, ships, dropMoves) {
  const nums = new Set(ships);
  const out = dropMoves ? list.filter(o => !(["MO", "MS", "I", "G", "WTP"].includes(o.code) && nums.has(Number(o.ship)))) : list.slice();
  out.push({ code: "CF", name, x, y });
  for (let i = 0; i < ships.length; i += 10) out.push({ code: "AF", fleet: name, ships: ships.slice(i, i + 10) });
  return out;
}
export function addToFleetOrders(list, fleet, ships) {
  const out = list.slice();
  for (let i = 0; i < ships.length; i += 10) out.push({ code: "AF", fleet, ships: ships.slice(i, i + 10) });
  return out;
}

let fleetDlg = null;
function makeFleetDialog(q, ships) {
  if (!fleetDlg) {
    fleetDlg = el("dialog", { id: "fleetDlg", class: "fleet-dlg", "aria-labelledby": "fleetDlgH" });
    document.body.append(fleetDlg);
  }
  const dlg = fleetDlg;
  const list0 = S.draft.map(rowToDict);
  const nums = ships.map(s => s.number);
  const moves = list0.filter(o => ["MO", "MS", "I", "G", "WTP"].includes(o.code) && nums.includes(Number(o.ship)));
  const input = el("input", { id: "fleetName", name: "name", maxlength: 12, autocomplete: "off", value: defaultFleetName(q), "aria-describedby": "fleetNameHint fleetNameErr" });
  const err = el("p", { class: "err", id: "fleetNameErr", role: "alert" });
  const drop = moves.length ? el("input", { type: "checkbox", id: "fleetDropMoves", checked: true }) : null;
  const preview = el("pre", { class: "order-preview", id: "fleetPreview", "aria-label": "Orders to add" });
  const ok = el("button", { type: "submit", class: "primary", id: "fleetOk" }, "Make fleet");
  const update = () => {
    const name = input.value.trim();
    const p = fleetNameProblem(name);
    err.textContent = p || "";
    ok.disabled = !!p;
    const orders = makeFleetOrders([], name || "?", q.x, q.y, nums, false);
    preview.textContent = orders.map(classicText).join("\n");
  };
  input.addEventListener("input", update);
  const form = el("form", { class: "form", method: "dialog" },
    el("h2", { id: "fleetDlgH" }, `Make a fleet at ${q.system && q.system.name ? q.system.name : "deep space"} ${xy(q.x, q.y)}`),
    el("p", { class: "hint" }, `${ships.length} ship${ships.length === 1 ? "" : "s"}:`),
    el("ul", {}, ships.map(s => el("li", {}, `${s.number} ${s.class}`))),
    el("label", { for: "fleetName" }, "Fleet name"),
    input,
    el("p", { class: "hint", id: "fleetNameHint" }, "Up to 12 letters, digits, _ - or . (no spaces), different from your other fleets. Other races may use the same names; your orders always mean your own fleet."),
    err,
    drop ? el("label", { class: "selall" }, drop, `Drop their own move orders from the draft (${moves.map(o => classicText(o)).join("; ")}): a ship in a fleet moves with the fleet.`) : null,
    el("p", { class: "hint" }, "Adds these orders to the end of your draft. They run before movement, so you can give the new fleet a move order this turn:"),
    preview,
    el("div", { class: "row-end gap" }, el("button", { type: "button", class: "ghost", onclick: () => dlg.close() }, "Cancel"), ok));
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const name = input.value.trim();
    const p = fleetNameProblem(name);
    if (p) { err.textContent = p; input.focus(); return; }
    try {
      await saveDraft(makeFleetOrders(S.draft.map(rowToDict), name, q.x, q.y, nums, drop && drop.checked));
      dlg.close();
      picked.set.clear();
      if (S.selection) S.selection.focus = { kind: "fleet", id: name };
      emit("focus", { kind: "fleet", id: name });
      toast(`Fleet ${name} is forming (CF + AF in your draft). Use Move (click map) to send it this turn.`, "good", 6000);
    } catch (ex) { err.textContent = ex.message; }
  });
  clear(dlg, form);
  update();
  dlg.showModal();
  input.select();
}

async function addToFleet(fleetName, ships) {
  try {
    await saveDraft(addToFleetOrders(S.draft.map(rowToDict), fleetName, ships.map(s => s.number)));
    picked.set.clear();
    if (S.selection) S.selection.focus = { kind: "fleet", id: fleetName };
    emit("focus", { kind: "fleet", id: fleetName });
    toast(`Added: AF ${fleetName} ${ships.map(s => s.number).join(" ")}`, "good", 4000);
  } catch (e) { toast(e.message, "error"); }
}

// the loose ships ticked in the selection panel, per square (kept across re-renders)
const picked = { key: null, set: new Set() };

function shipList(q, may) {
  const v = S.view;
  const box = el("div", { class: "obj" });
  const focusId = S.selection.focus && S.selection.focus.kind === "ship" ? S.selection.focus.id : null;
  const k = key(q.x, q.y);
  if (picked.key !== k) { picked.key = k; picked.set.clear(); }
  for (const n of [...picked.set]) if (!q.ships.some(s => s.number === n)) picked.set.delete(n);
  box.append(el("h3", {}, el("span", { class: "sw", style: { background: relColor(v.empire.id) } }), `${q.ships.length} ship${q.ships.length === 1 ? "" : "s"} (not in a fleet)`));
  const boxes = [];
  let makeBtn = null, addBtn = null, allBox = null;
  const sync = () => {
    const n = picked.set.size;
    if (makeBtn) { makeBtn.textContent = n ? `Make fleet (${n})` : "Make fleet"; makeBtn.disabled = !n; }
    if (addBtn) { addBtn.textContent = n ? `Add ${n} to fleet` : "Add to fleet"; addBtn.disabled = !n; }
    if (allBox) { allBox.checked = n === q.ships.length; allBox.indeterminate = n > 0 && n < q.ships.length; }
  };
  box.append(el("ul", { class: `unit-list${may ? " pick-list" : ""}` }, q.ships.map(s => {
    const cb = may ? el("input", { type: "checkbox", class: "ship-pick", value: s.number, checked: picked.set.has(s.number), "aria-label": `Pick ship ${s.number} ${s.class}`,
      onchange: e => { if (e.target.checked) picked.set.add(s.number); else picked.set.delete(s.number); sync(); } }) : null;
    if (cb) boxes.push(cb);
    return el("li", {}, cb,
      el("button", { type: "button", class: s.number === focusId ? "sel" : "", "aria-pressed": s.number === focusId ? "true" : "false", onclick: () => emit("focus", { kind: "ship", id: s.number }) },
        el("span", {}, `${s.number} ${s.class}`), el("span", { class: "dim" }, s.dest && (s.dest.x !== s.x || s.dest.y !== s.y) ? `→ ${xy(s.dest.x, s.dest.y)}` : s.order === "STAND" ? "idle" : s.order)));
  })));
  if (may) {
    allBox = el("input", { type: "checkbox", id: "pickAllShips", onchange: e => { for (const cb of boxes) { cb.checked = e.target.checked; const n = Number(cb.value); if (cb.checked) picked.set.add(n); else picked.set.delete(n); } sync(); } });
    const chosen = () => q.ships.filter(s => picked.set.has(s.number));
    makeBtn = btn("Make fleet", () => { if (chosen().length) makeFleetDialog(q, chosen()); }, "primary small");
    makeBtn.id = "makeFleetBtn";
    const tools = el("div", { class: "fleet-tools" }, el("label", { class: "selall" }, allBox, "Select all"));
    const acts = el("div", { class: "actions" }, makeBtn);
    if (q.fleets.length) {
      const fsel = el("select", { id: "addToFleetSel", "aria-label": "Fleet to add the ships to" }, byName(q.fleets).map(f => el("option", { value: f.name }, `${f.name}${f.forming ? " (forming)" : ""}`)));
      addBtn = btn("Add to fleet", () => { if (chosen().length) addToFleet(fsel.value, chosen()); }, "small");
      addBtn.id = "addToFleetBtn";
      acts.append(addBtn, fsel);
    }
    tools.append(acts, el("div", { class: "hint" }, "Tick ships, then Make fleet (or add them to a fleet here). The new fleet can move this turn."));
    box.append(tools);
    sync();
  }
  const s = focusId !== null ? q.ships.find(x => x.number === focusId) : null;  if (s) {
    box.append(el("h4", {}, `Ship ${s.number}: ${s.class}`));
    box.append(kv([["Posture / role", `${s.posture} / ${s.role}`], ["Move / scan", `${s.move} / ${s.scan}`], ["Cargo", s.cargo ? cargoText(s) : null],
      ["Going", s.dest && (s.dest.x !== s.x || s.dest.y !== s.y) ? placeName(s.dest.x, s.dest.y) : s.order], ["Target", s.target]]));
    box.append(draftFor(o => o.ship === s.number || (o.ships || []).includes(s.number)));
    if (may) {
      const n = s.number;
      const cargo = s.cargo_capacity > 0;
      // an unowned (empty) system here and population aboard: offer to claim it
      const here = q.system;
      const claimable = cargo && here && here.kind !== "own" && here.owner_kind === "unowned" && Math.floor((s.cargo && s.cargo.POP) || 0) >= 1;
      if (claimable) box.append(el("div", { class: "actions" },
        btn(`Claim ${here.name || "this system"} (land population)`, () => claimSystem(s).then(() => toast(`Added: land population${(s.cargo.IU || s.cargo.AU) ? ", then the IU/AU cargo" : ""} on ${here.name || "the system"}.`, "info")).catch(e => toast(e.message, "error")), "primary"),
        el("span", { class: "hint" }, "Landing population claims an unowned system; the IU/AU cargo is unloaded after it.")));
      box.append(el("div", { class: "actions" },
        btn("Move (click map)", () => startMove({ kind: "ship", obj: s }), "primary"),
        btn("Move to system", () => openOrder("MS", { ship: n })),
        btn("Intercept", () => startIntercept({ kind: "ship", obj: s })),
        btn("Guard", () => addOrder({ code: "G", ship: n }).catch(e => toast(e.message, "error"))),
        btn("Posture", () => openOrder("SP", { ship: n })),
        btn("Role", () => openOrder("CSCR", { ship: n })),
        cargo ? btn("Load", () => openLoad({ kind: "ship", id: n })) : null,
        cargo ? btn("Unload", () => openUnload({ kind: "ship", id: n })) : null,
        ownFleets().length ? btn("Join fleet", () => openOrder("AF", { ships: [n] })) : null,
        btn("Disband", () => openOrder("DS", { ship: n }), "ghost")));
      box.append(moreOrders("ship", { ship: n }));
    }
  }
  return box;
}

function foreignCard(q, fu, may) {
  const box = el("div", { class: "obj" });
  const owners = [...new Set(q.foreign.map(s => s.owner))];
  box.append(el("h3", {}, el("span", { class: "sw", style: { background: relColor(owners[0]) } }), `${q.foreign.length} foreign ship${q.foreign.length === 1 ? "" : "s"}`));
  for (const ff of q.foreignFleets) box.append(el("div", { class: "hint" }, `Fleet ${ff.name} of the ${ff.owner_name}: ${ff.ships.length} ships`));
  box.append(el("ul", { class: "unit-list" }, q.foreign.map(s => el("li", {}, el("div", { class: "row-between", style: { padding: ".1em .3em" } },
    el("span", {}, el("span", { style: { color: relColor(s.owner) } }, "● "), `${s.owner_name} ${shipClass(s.type)} ${s.number}`),
    el("span", { class: "dim" }, `${s.level}${s.posture ? ` · ${s.posture}/${s.role}` : ""}${s.moved && s.ox !== undefined ? ` · from ${xy(s.ox, s.oy)}` : ""}`),
    fu && may ? btn("Intercept", () => openOrder(fu.kind === "fleet" ? "FIS" : "I", fu.kind === "fleet" ? { fleet: fu.obj.name, target: s.number } : { ship: fu.obj.number, target: s.number }), "small") : null)))));
  return box;
}

// The troops on a system's ground now (after this turn's battles; Dave 2026-11-16).  Yours come
// from the view's own troop list wherever they stand.  Other races' troops: on your own system
// the view lists everyone standing on it; elsewhere only a short range scan this turn shows them
// (a long scan or map memory shows none).
function groundNow(s, q, own) {
  const v = S.view;
  const me = v.empire.id;
  const mine = v.troops.filter(t => t.system === s.id && t.ship === null);
  const scanned = own || (s.kind === "scan" && s.level === "short");
  const foreign = scanned ? (s.troops || []).filter(t => t.owner !== me) : [];
  const battle = q.combats.some(c => c.system === s.id);
  if (!mine.length && !foreign.length && !battle) return null;
  const line = (label, list, owner) => el("div", { class: "gline", "data-owner": String(owner) },
    el("span", { class: "sw", style: { background: relColor(owner), width: ".6em", height: ".6em", borderRadius: "50%", display: "inline-block", marginRight: ".3em" } }),
    el("strong", {}, `${label}: `), list.length ? summarize(list.map(t => `${troopName(t.type)} (${t.posture_name || t.posture})`)) : "none");
  const box = el("div", { class: "ground-now", "data-ground": "now" },
    el("div", { class: "glabel" }, battle ? "Troops on the ground after the battle" : "Troops on the ground"));
  box.append(line("Yours", mine, me));
  const owners = [...new Set(foreign.map(t => t.owner))].sort((a, b) => a - b);
  for (const o of owners) {
    const list = foreign.filter(t => t.owner === o);
    box.append(line(list[0].owner_name || raceName(o), list, o));
  }
  if (!scanned) box.append(el("div", { class: "hint" }, "Other races' troops here show only on a short range scan; the battle report lists those in the battle."));
  return box;
}

function summarize(list) {
  const m = new Map();
  for (const x of list) m.set(x, (m.get(x) || 0) + 1);
  return [...m].map(([k, n]) => (n > 1 ? `${n} × ${k}` : k)).join(", ");
}
export { catEntry };
