// Empire panels: economy and systems, the tech tree, forces (fleets, ships, troops), leaders and
// spies, and diplomacy.  Tables are sortable and filterable; rows centre the map.
"use strict";
import { S, HOME, api, el, clear, fmt, emit, toast, getPref, setPref, xy, relColor, STANCE, atWar, shipClass, troopName, techName, canOrder } from "./core.js";
import { openOrder } from "./orders.js";
import { knownSystems, placeName, effectiveFleet, ownFleets, draftFleets } from "./world.js";

// ---------------------------------------------------------------- sortable, filterable table
// The sort column and direction are kept per table id in the browser's prefs ("sort.<id>"), so
// they survive the panel being rebuilt (draft changes, new turns, history) and page reloads.
// `detail(row)` may return a node shown in a full-width row under that row (expandable rows:
// the Forces tab's fleets show their ships this way).
export function dataTable(id, cols, rows, { onRow, filter, empty, detail, counter = true } = {}) {
  const saved = getPref(`sort.${id}`, null);
  const st = saved && cols.some(c => c.key === saved.key) ? { key: saved.key, dir: saved.dir < 0 ? -1 : 1 } : { key: null, dir: 1 };
  const wrap = el("div");
  const draw = () => {
    let list = filter ? rows.filter(filter) : rows.slice();
    if (st.key) {
      const c = cols.find(q => q.key === st.key);
      list.sort((a, b) => {
        const x = c.get(a), y = c.get(b);
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""), undefined, { numeric: true })) * st.dir;
      });
    }
    const thead = el("thead", {}, el("tr", {}, cols.map(c => el("th", { scope: "col", class: c.num ? "num" : "", "aria-sort": st.key === c.key ? (st.dir > 0 ? "ascending" : "descending") : undefined, title: c.title },
      el("button", { type: "button", onclick: () => { if (st.key === c.key) st.dir = -st.dir; else { st.key = c.key; st.dir = c.num ? -1 : 1; } setPref(`sort.${id}`, { ...st }); draw(); } }, c.label)))));
    const tbody = el("tbody", {}, list.flatMap(r => {
      const tr = el("tr", { class: onRow ? "clickable" : "", tabindex: onRow ? 0 : undefined },
        cols.map(c => el("td", { class: c.num ? "num" : "" }, c.render ? c.render(r) : fmt(c.get(r), c.digits || 0))));
      if (onRow) { tr.addEventListener("click", () => onRow(r)); tr.addEventListener("keydown", e => { if (e.key === "Enter" && e.target === tr) onRow(r); }); }
      const more = detail ? detail(r) : null;
      return more ? [tr, el("tr", { class: "detail-row" }, el("td", { colspan: cols.length }, more))] : [tr];
    }));
    clear(wrap, list.length ? el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, thead, tbody)) : el("p", { class: "hint" }, empty || "Nothing to show."),
      counter ? el("div", { class: "hint" }, `${list.length} of ${rows.length}`) : null);
  };
  draw();
  wrap.redraw = draw;
  return wrap;
}

const goto = (x, y, sel) => emit("goto", { x, y, ...(sel || {}) });

// The host handicap (Dave 2026-11-19, DECISIONS W-28), shown to the host's own race
export function hostHandicapNote() {
  return el("p", { class: "notice handicap" }, el("strong", {}, "Host handicap. "),
    "As host of a multi-player game your race can't win and earns no ranking VP. It is left out of the rankings (host, unranked), so the other races rank as if you weren't there.");
}

// ---------------------------------------------------------------- economy and systems
export function renderEmpire(box) {
  const v = S.view;
  clear(box);
  const e = v.empire, ec = v.results.economy || {};
  const p = ec.production || {};
  box.append(el("h2", {}, `The ${e.name}`));
  box.append(el("div", { class: "digest" },
    tileKV("EU stockpile", fmt(e.eu)), tileKV("IU depot", fmt(e.iu_depot)),
    tileKV("Production", `${fmt(p.AU)}/${fmt(p.IU)}/${fmt(p.EU)}`, "AU / IU / EU produced this turn"),
    tileKV("Trade EU", fmt(ec.trade_eu)), tileKV("Purchases", fmt(ec.purchases_eu), "EU spent by your orders this turn (builds, techs and other order costs)"),
    tileKV("Techs", String(e.techs.length - 1)), tileKV("VP", e.unranked ? `${e.vp} (host, unranked)` : `${e.vp}/${v.game.vp_to_win}`), tileKV("Autosupply", e.autosisd ? "on" : "off", "AUTOSISD: automatically resupply the IU depot"),
    tileKV("AOMT", e.aomt !== false ? "on" : "off", "Autogenerate orders on missed turn (on by default): if the host forces a turn before you submit, your draft is run as if submitted, or with no draft the computer writes your orders from your own view")));
  box.append(el("div", { class: "actions" },
    el("button", { type: "button", disabled: !canOrder(), onclick: () => openOrder(e.autosisd ? "NOAUTOSISD" : "AUTOSISD") }, e.autosisd ? "Turn autosupply off" : "Turn autosupply on"),
    el("button", { type: "button", disabled: !canOrder(), onclick: () => openOrder("CRN") }, "Rename race")));
  // AOMT (Dave 2026-11-19, DECISIONS W-29): a race setting, switched at once (no order needed)
  const aomtBox = el("input", { type: "checkbox", id: "aomtToggle", checked: e.aomt !== false, disabled: !canOrder() });
  aomtBox.addEventListener("change", async () => {
    const on = aomtBox.checked;
    aomtBox.disabled = true;
    try {
      const r = await api(`/api/games/${S.gid}/aomt`, { method: "POST", gid: S.gid, body: { on } });
      for (const w of [S.view, S.currentView]) if (w && w.empire) w.empire.aomt = r.aomt;
      toast(r.aomt ? "AOMT is on: a turn forced before you submit runs your draft, or with no draft gets orders written by the computer." : "AOMT is off: a turn forced before you submit runs with no orders from you (your draft is not used).", "good", 5000);
    } catch (err) { toast(err.message, "error"); }
    renderEmpire(box);
  });
  box.append(el("div", { class: "aomt-row", id: "aomtRow" },
    el("label", { for: "aomtToggle" }, aomtBox, " Autogenerate orders on missed turn (AOMT)"),
    el("p", { class: "hint" }, e.aomt !== false ? "On (the default). If the host forces a turn before you have submitted, your draft is run as if you had submitted it; if your draft is empty, the computer writes this turn's orders for you from your own view. Your report then says which, and lists them. Classic order: AOMT ON / AOMT OFF." : "Off. If the host forces a turn before you have submitted, your empire gives no orders that turn (a draft you haven't submitted is not used). Classic order: AOMT ON / AOMT OFF.")));
  if (S.summary && S.summary.host_handicap && v.seat.host && !v.seat.view_as)
    box.append(hostHandicapNote());
  box.append(el("h3", { style: { marginTop: ".8rem" } }, "Systems"));
  const rows = v.systems;
  const cols = [
    { key: "name", label: "System", get: s => s.name, render: s => el("span", {}, s.x === HOME && s.y === HOME ? "⌂ " : "", s.name) },
    { key: "at", label: "At", get: s => s.x * 1000 + s.y, render: s => xy(s.x, s.y) },
    { key: "pop", label: "Pop", num: true, get: s => s.pop, digits: 1 },
    { key: "happy", label: "Mood", get: s => s.happy, render: s => el("span", { title: `happiness ${fmt(s.happy, 2)}`, class: s.happy_band === "RB" || s.happy_band === "UH" ? "err" : "" }, s.happy_band, s.trend > 0 ? " ▲" : s.trend < 0 ? " ▼" : "") },
    { key: "hab", label: "Hab", get: s => s.hab_value, render: s => s.hab, title: "Habitability" },
    { key: "sp", label: "SP", num: true, get: s => s.starport, title: "Starport class" },
    { key: "au", label: "AU", num: true, get: s => s.au, title: "AU stockpile" },
    { key: "iu", label: "IU", num: true, get: s => s.iu, title: "IU stockpile" },
    { key: "prof", label: "Profile", get: s => s.profile.au, render: s => `${s.profile.au}/${s.profile.iu}/${s.profile.eu}`, title: "Production profile AU/IU/EU %" },
    { key: "prod", label: "Prod", num: true, get: s => s.production.au + s.production.iu + s.production.eu, render: s => `${s.production.au}/${s.production.iu}/${s.production.eu}`, title: "Produced this turn AU/IU/EU" },
    { key: "inf", label: "Inf", num: true, get: s => s.infra, title: "Infrastructure" },
    { key: "st", label: "Status", get: s => s.status, render: s => el("span", { class: s.status !== "Norm" ? "err" : "" }, s.status) },
  ];
  const q = el("input", { type: "search", id: "sysFilter", placeholder: "Filter systems…", "aria-label": "Filter systems", value: getPref("filter.systems.q", "") });
  let t;
  const tbl = dataTable("systems", cols, rows, { onRow: s => goto(s.x, s.y, { kind: "system", id: s.id }), filter: s => !q.value || s.name.toLowerCase().includes(q.value.toLowerCase()) });
  q.addEventListener("input", () => { setPref("filter.systems.q", q.value); clearTimeout(t); t = setTimeout(tbl.redraw, 120); });
  box.append(el("div", { class: "filter-row" }, q), tbl);
  // artifacts summary
  const arts = v.systems.flatMap(s => s.artifacts.map(a => [a, s.name]));
  if (arts.length) box.append(el("h3", {}, "Artifacts"), el("p", {}, arts.map(([a, n]) => `${a} at ${n}`).join(" · ")));
  const routes = v.systems.flatMap(s => s.trade_routes.map(r => `${s.name} ↔ ${r.name}`));
  if (routes.length) box.append(el("h3", {}, "Trade routes"), el("p", {}, routes.join(" · ")));
}
function tileKV(k, v, title) { return el("div", { class: "tile", title }, el("div", { class: "k" }, k), el("div", { class: "v" }, v)); }

// ---------------------------------------------------------------- tech tree
export function renderTech(box) {
  const v = S.view;
  clear(box);
  const have = new Set(v.empire.techs);
  const queued = new Set(S.draft.filter(o => o.code === "PT" || o.code === "CRP").map(o => o.tech));
  const spend = S.draft.filter(o => o.code === "PT" || o.code === "CRP").reduce((a, o) => a + (S.ref.techs.find(t => t.id === o.tech)?.cost || 0) * (o.code === "CRP" ? 2 : 1), 0);
  box.append(el("h2", {}, "Technology"));
  box.append(el("p", { class: "hint" }, `You have ${have.size - 1} technologies and ${fmt(v.empire.eu)} EU. `, spend ? `Draft purchases: ${fmt(spend)} EU. ` : "",
    "Buy (PT) a technology whose prerequisites you have; a crash program (CRP) costs double."));
  const show = localStorage.getItem("mhgcTechFilter") || "all";
  box.append(el("div", { class: "subtabs", role: "group", "aria-label": "Show" }, [["all", "All"], ["ready", "Can buy"], ["owned", "Owned"]].map(([k, l]) =>
    el("button", { type: "button", class: `chip-btn ${k === show ? "on" : "ghost"}`, "aria-pressed": k === show ? "true" : "false", onclick: () => { localStorage.setItem("mhgcTechFilter", k); renderTech(box); } }, l))));
  const tiers = {};
  for (const t of S.ref.techs) if (t.id > 0) (tiers[t.tier] ||= []).push(t);
  const wrapT = el("div", { class: "tech-tiers" });
  for (const tier of Object.keys(tiers).map(Number).sort((a, b) => a - b)) {
    const cards = tiers[tier].filter(t => {
      const ready = !have.has(t.id) && t.prereqs.every(p => have.has(p));
      return show === "all" || (show === "owned" && have.has(t.id)) || (show === "ready" && ready);
    }).map(t => {
      const owned = have.has(t.id), ready = !owned && t.prereqs.every(p => have.has(p));
      const cls = owned ? "owned" : queued.has(t.id) ? "queued" : ready ? "ready" : "locked";
      return el("div", { class: `tech ${cls}` },
        el("div", { class: "tn" }, el("span", {}, `${t.id}. ${t.name}`), el("span", { class: "dim" }, owned ? "✓" : `${fmt(t.cost)} EU`)),
        t.unlocks ? el("div", {}, t.unlocks) : null,
        t.prereqs.length ? el("div", { class: "pre" }, "Needs: ", t.prereqs.map(p => el("span", { class: have.has(p) ? "ok" : "" }, techName(p))).reduce((a, x, i) => (i ? [...a, ", ", x] : [x]), [])) : null,
        t.vp ? el("div", { class: "pre" }, `${t.vp} VP`) : null,
        !owned && ready && canOrder() && !queued.has(t.id) ? el("div", { class: "actions" },
          el("button", { type: "button", class: "small", onclick: () => openOrder("PT", { tech: t.id }) }, "Buy"),
          el("button", { type: "button", class: "small ghost", onclick: () => openOrder("CRP", { tech: t.id }) }, "Crash")) : null,
        queued.has(t.id) ? el("div", { class: "warnc" }, "In your draft orders") : null);
    });
    if (cards.length) wrapT.append(el("div", { class: "tier" }, el("h4", {}, tier === 8000 ? "Future technology" : `${fmt(tier)} EU technologies`), el("div", { class: "tier-row" }, cards)));
  }
  box.append(wrapT);
}

// ---------------------------------------------------------------- forces
// Ships in a fleet are listed under their fleet (Dave 2026-11-18): the Ships sub-tab has the
// loose ships only (unless "Include ships in fleets" is ticked), and each fleet row expands to
// its ships, with the same columns.  Fleet membership is the draft's (world.js draftFleets):
// a ship an AF order adds, or a CF/CFXY fleet the draft is forming, counts already.
const dest = o => (o.dest && (o.dest.x !== o.x || o.dest.y !== o.y)) ? placeName(o.dest.x, o.dest.y) : o.order === "STAND" ? "–" : o.order;
function shipCols(planned, withFleet) {
  return [
    { key: "number", label: "Ship", num: true, get: s => s.number, render: s => String(s.number) },
    { key: "class", label: "Class", get: s => s.class },
    { key: "at", label: "At", get: s => placeName(s.x, s.y), render: s => placeName(s.x, s.y) },
    { key: "dest", label: "Going", get: s => dest(s), render: s => planned.has(s.number) ? el("span", { class: "warnc", title: "has draft orders" }, dest(s), " ✎") : dest(s) },
    { key: "pr", label: "P/R", get: s => s.posture + s.role, render: s => `${s.posture}/${s.role}`, title: "Posture / combat role" },
    withFleet ? { key: "fleet", label: "Fleet", get: s => effectiveFleet(s) || "", render: s => fleetCell(s) } : null,
    { key: "cargo", label: "Cargo", get: s => s.cargo_used || 0, render: s => s.cargo ? cargoText(s) : "", title: "Cargo used / capacity" },
  ].filter(Boolean);
}
function fleetCell(s) {
  const f = effectiveFleet(s);
  if (!f) return s.fleet ? el("span", { class: "dim", title: "leaves its fleet by a draft order" }, `(leaving ${s.fleet})`) : "";
  return f !== s.fleet ? el("span", { class: "warnc", title: "joins this fleet by a draft order" }, `${f} (joining)`) : f;
}
// "2 Transport · 1 Frigate", largest group first
export function composition(ships) {
  const n = new Map();
  for (const s of ships) n.set(s.class, (n.get(s.class) || 0) + 1);
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([c, k]) => `${k} ${c}`).join(" · ");
}
// the ships each fleet has once the draft has run: fleet name -> [ship view rows]
export function fleetMembers() {
  const out = new Map();
  for (const s of S.view.ships) {
    const f = effectiveFleet(s);
    if (f) { if (!out.has(f)) out.set(f, []); out.get(f).push(s); }
  }
  return out;
}

export function renderForces(box) {
  const v = S.view;
  let forcesTab = getPref("filter.forces.tab", "fleets");
  if (!["fleets", "ships", "troops"].includes(forcesTab)) forcesTab = "fleets";
  clear(box);
  if (!S.draftFleets) S.draftFleets = draftFleets();
  const fleets = ownFleets();
  const members = fleetMembers();
  const loose = v.ships.filter(s => !effectiveFleet(s));
  const planned = new Set(S.draft.filter(o => o.ship !== undefined).map(o => o.ship));
  const goShip = s => goto(s.x, s.y, { kind: "ship", id: s.number });
  box.append(el("h2", {}, "Forces"));
  box.append(el("div", { class: "subtabs", role: "tablist" }, [["fleets", `Fleets (${fleets.length})`], ["ships", `Ships (${loose.length} loose)`], ["troops", `Troops (${v.troops.length})`]].map(([k, l]) =>
    el("button", { type: "button", role: "tab", id: `forces-${k}`, "aria-selected": k === forcesTab ? "true" : "false", class: `chip-btn ${k === forcesTab ? "on" : "ghost"}`, title: k === "ships" ? `${loose.length} ships not in a fleet, of ${v.ships.length}` : undefined, onclick: () => { setPref("filter.forces.tab", k); renderForces(box); } }, l))));
  if (forcesTab === "fleets") {
    const open = new Set(getPref("forces.openFleets", []));
    const toggle = name => { if (open.has(name)) open.delete(name); else open.add(name); setPref("forces.openFleets", [...open]); tbl.redraw(); };
    const shipsOf = f => members.get(f.name) || [];
    const allOpen = fleets.length && fleets.every(f => open.has(f.name));
    box.append(el("div", { class: "actions" },
      el("button", { type: "button", disabled: !canOrder(), onclick: () => openOrder("CFXY", { x: HOME, y: HOME }) }, "New fleet…"),
      fleets.length ? el("button", { type: "button", class: "ghost", id: "fleetsExpandAll", onclick: () => { setPref("forces.openFleets", allOpen ? [] : fleets.map(f => f.name)); renderForces(box); } }, allOpen ? "Collapse all" : "Show all ships") : null));
    const tbl = dataTable("fleets", [
      { key: "name", label: "Fleet", get: f => f.name, render: f => el("span", { class: "fleet-name" },
        el("button", { type: "button", class: "expander", "aria-expanded": open.has(f.name) ? "true" : "false", "aria-label": `${open.has(f.name) ? "Hide" : "Show"} the ships of fleet ${f.name}`, title: open.has(f.name) ? "Hide its ships" : "Show its ships",
          onclick: e => { e.stopPropagation(); toggle(f.name); } }, open.has(f.name) ? "▾" : "▸"),
        " ", f.name, f.forming ? el("span", { class: "badge warn", title: `formed by this turn's ${f.via} order` }, "forming") : null) },
      { key: "at", label: "At", get: f => placeName(f.x, f.y), render: f => placeName(f.x, f.y) },
      { key: "n", label: "Ships", num: true, get: f => shipsOf(f).length },
      { key: "comp", label: "Composition", get: f => composition(shipsOf(f)), render: f => composition(shipsOf(f)) || el("span", { class: "dim" }, f.forming && f.via === "CFXY" && f.ships.length ? `gathers ${f.ships.length} after movement` : "no ships") },
      { key: "dest", label: "Going", get: f => dest(f), render: f => dest(f) },
      { key: "speed", label: "Speed", get: f => String(f.speed) },
      { key: "posture", label: "Posture", get: f => f.posture },
      { key: "role", label: "Role", get: f => f.role },
      { key: "adm", label: "Admiral", get: f => f.admiral || "" },
    ], fleets, {
      onRow: f => goto(f.x, f.y, { kind: "fleet", id: f.name }),
      empty: "No fleets. Create one with New fleet, or from a square with ships on the map.",
      detail: f => open.has(f.name) ? el("div", { class: "fleet-ships", "aria-label": `Ships of fleet ${f.name}` },
        shipsOf(f).length ? dataTable("fleetShips", shipCols(planned, false), shipsOf(f), { onRow: goShip, counter: false })
          : el("p", { class: "hint" }, f.forming && f.via === "CFXY" ? "No loose ships on its square yet; ships there when the turn moves join it." : "No ships in this fleet.")) : null,
    });
    box.append(tbl);
  } else if (forcesTab === "ships") {
    // The filters are rebuilt with the panel, so they start from the saved prefs (the "idle
    // only" box used to come back unchecked whenever the draft changed, e.g. after giving the
    // ship you had clicked an order).
    const f = { q: "", type: "", idle: false, inFleets: false, ...getPref("filter.ships", {}) };
    const rows = f.inFleets ? v.ships : loose;
    const q = el("input", { type: "search", id: "shipFilter", placeholder: "Filter: number, class, fleet…", "aria-label": "Filter ships", value: f.q });
    const types = [...new Set(rows.map(s => s.type))];
    if (f.type && !types.includes(f.type)) types.push(f.type);      // keep a saved type that has no ships now
    // grouped as in the Build ship picker (G-22): scouts, transports, then the four ship lines
    const tyOpt = t => el("option", { value: t, selected: t === f.type }, shipClass(t));
    const tyGroups = (S.ref.ship_groups || []).map(g => [g.label, S.ref.ships.filter(r => r.group === g.key && types.includes(r.code)).map(r => r.code)]).filter(([, l]) => l.length);
    const grouped = new Set(tyGroups.flatMap(([, l]) => l));
    const ty = el("select", { id: "shipTypeFilter", "aria-label": "Ship type" }, el("option", { value: "" }, "All types"),
      tyGroups.map(([label, l]) => el("optgroup", { label }, l.map(tyOpt))), types.filter(t => !grouped.has(t)).map(tyOpt));
    const idle = el("input", { type: "checkbox", id: "idleOnly", checked: !!f.idle });
    const inFleets = el("input", { type: "checkbox", id: "inFleets", checked: !!f.inFleets });
    const filt = s => (!ty.value || s.type === ty.value) && (!idle.checked || (s.order === "STAND" && !effectiveFleet(s) && !planned.has(s.number)))
      && (!q.value || `${s.number} ${s.class} ${effectiveFleet(s) || ""}`.toLowerCase().includes(q.value.toLowerCase()));
    const tbl = dataTable("ships", shipCols(planned, !!f.inFleets), rows, { filter: filt, onRow: goShip,
      empty: rows.length || !v.ships.length ? "No ships match." : "Every ship is in a fleet: see the Fleets tab, or tick Include ships in fleets." });
    const save = () => setPref("filter.ships", { q: q.value, type: ty.value, idle: idle.checked, inFleets: inFleets.checked });
    for (const c of [q, ty, idle]) c.addEventListener("input", () => { save(); tbl.redraw(); });
    inFleets.addEventListener("input", () => { save(); renderForces(box); });
    const hidden = v.ships.length - loose.length;
    box.append(el("div", { class: "filter-row" }, q, ty, el("label", { for: "idleOnly", class: "row gap" }, idle, "Idle only"),
      el("label", { for: "inFleets", class: "row gap", title: "Ships in fleets are listed under their fleet in the Fleets tab" }, inFleets, `Include ships in fleets${hidden ? ` (${hidden})` : ""}`)), tbl);
  } else {
    box.append(dataTable("troops", [
      { key: "number", label: "Troop", num: true, get: t => t.number, render: t => String(t.number) },
      { key: "type", label: "Type", get: t => troopName(t.type) },
      { key: "where", label: "Where", get: t => t.ship ? `ship ${t.ship}` : sysNameOwn(t.system) },
      { key: "posture", label: "Posture", get: t => t.posture_name },
      { key: "built", label: "Built", num: true, get: t => t.built_turn },
    ], v.troops, { onRow: t => { const at = troopAt(t); if (at) goto(at.x, at.y); }, empty: "No combat troops." }));
  }
}
const sysNameOwn = id => (S.view.systems.find(s => s.id === id) || knownSystems().find(s => s.id === id) || {}).name || "–";
function troopAt(t) {
  if (t.ship) return S.view.ships.find(s => s.number === t.ship);
  return S.view.systems.find(s => s.id === t.system);
}
export function cargoText(s) {
  const c = s.cargo;
  const parts = [];
  if (c.AU) parts.push(`${c.AU} AU`); if (c.IU) parts.push(`${c.IU} IU`); if (c.POP) parts.push(`${c.POP} pop`); if (c.CT && c.CT.length) parts.push(`${c.CT.length} CT`);
  return `${parts.join(", ") || "empty"} (${s.cargo_used || 0}/${s.cargo_capacity})`;
}

// ---------------------------------------------------------------- leaders and spies
export function renderAgents(box) {
  const v = S.view;
  clear(box);
  box.append(el("h2", {}, "Leaders"));
  const bar = (label, n) => el("div", { class: "row gap", title: `${label} ${n}` }, el("span", { style: { width: "5.5em" }, class: "dim" }, label),
    el("span", { style: { flex: 1, height: "6px", background: "#1c2741", borderRadius: "3px", position: "relative" } },
      el("span", { style: { position: "absolute", left: 0, top: 0, bottom: 0, width: `${Math.max(0, Math.min(100, n))}%`, background: n >= 70 ? "#3ddc97" : n >= 40 ? "#4ea1ff" : "#f0b429", borderRadius: "3px" } })),
    el("span", { style: { width: "2.2em", textAlign: "right" } }, String(n)));
  if (!v.leaders.length) box.append(el("p", { class: "hint" }, "No leaders."));
  for (const l of v.leaders) {
    const where = l.fleet ? `admiral of fleet ${l.fleet}` : l.system ? `governor of ${sysNameOwn(l.system)}` : l.status;
    box.append(el("div", { class: "obj" },
      el("h3", {}, l.name, el("span", { class: "badge" }, l.status), l.transit ? el("span", { class: "badge warn" }, `arrives in ${l.transit}`) : null),
      el("div", { class: "dim" }, `${where} · age ${l.age}`),
      l.description ? el("details", {}, el("summary", { class: "hint" }, "Biography"), el("p", { class: "hint" }, l.description)) : null,
      el("div", { style: { display: "grid", gap: "2px", margin: ".3rem 0", fontSize: ".85em" } },
        bar("Management", l.mgmt), bar("Engineering", l.eng), bar("Combat", l.combat), bar("Intelligence", l.intel), bar("Social", l.social)),
      canOrder() ? el("div", { class: "actions" },
        el("button", { type: "button", onclick: () => openOrder("ML", { leader: l.name }) }, "Move to system"),
        el("button", { type: "button", onclick: () => openOrder("MLF", { leader: l.name }) }, "Move to fleet"),
        !l.renamed ? el("button", { type: "button", class: "ghost", onclick: () => openOrder("CLN", { leader: l.name }) }, "Rename") : null,
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("PLOI", { leader: l.name }) }, "Put on ice")) : null));
  }
  box.append(el("h2", { style: { marginTop: "1rem" } }, "Spies"));
  if (!v.spies.length) box.append(el("p", { class: "hint" }, "No spies. With Biomodification (tech 14) a system can build one: Build tech artifact, option S."));
  for (const sp of v.spies) {
    box.append(el("div", { class: "obj" },
      el("h3", {}, `Spy ${sp.number}`, sp.transit ? el("span", { class: "badge warn" }, `in transit, ${sp.transit} turns`) : null),
      el("div", { class: "dim" }, sp.system ? `at ${sysNameOwn(sp.system)}` : "no post", sp.mission ? ` · last mission ${sp.mission}` : ""),
      canOrder() ? el("div", { class: "actions" },
        el("button", { type: "button", onclick: () => openOrder("SMV", { spy: sp.number }) }, "Move"),
        el("label", { class: "sr-only", for: `spyM${sp.number}` }, "Mission"),
        (() => {
          const s = el("select", { id: `spyM${sp.number}` }, ["SOS", "SOT", "SOL", "SVS", "SOE", "SOM", "SON", "SAL", "SSB", "SET", "SUP", "SRS"].map(c => {
            const e = S.catalogue.orders.find(o => o.code === c);
            return el("option", { value: c }, `${c} - ${(e && e.help || c).split(":")[0].split("(")[0]}`);
          }));
          return [s, el("button", { type: "button", onclick: () => openOrder(s.value, { spy: sp.number }) }, "Mission…")];
        })()) : null));
  }
}

// ---------------------------------------------------------------- diplomacy
export function renderDiplomacy(box, chatRecipients) {
  const v = S.view;
  clear(box);
  box.append(el("h2", {}, "Diplomacy"));
  box.append(el("p", { class: "hint" }, "Races you have contacted, and your stance towards them. You never see their stance towards you. Declaring war is immediate; an alliance needs both sides; ending a war needs both to offer peace."));
  if (!v.races.length) { box.append(el("p", { class: "hint" }, "No contacts yet. Scan another race's ships or systems to make contact.")); return; }
  const humans = new Set((chatRecipients || []).map(r => r.empire));
  for (const r of v.races) {
    const st = r.our_stance;
    const may = canOrder() && r.kind !== "extinct";
    box.append(el("div", { class: "obj" },
      el("h3", {}, el("span", { class: "sw", style: { background: relColor(r.id) } }), r.name,
        el("span", { class: "badge" }, r.kind === "npr" ? "computer" : r.kind === "player" ? "human" : r.kind), el("span", { class: `badge ${st === "A" ? "good" : st === "W" || st === "E" ? "bad" : ""}` }, STANCE[st] || st)),
      r.deny_trade !== null && r.deny_trade !== undefined ? el("div", { class: "dim" }, `Denying ${r.deny_trade}% of their DCT trade`) : null,
      r.split_trade !== null && r.split_trade !== undefined ? el("div", { class: "dim" }, `Splitting DCT trade ${r.split_trade}%`) : null,
      may ? el("div", { class: "actions" },
        st !== "A" && st !== "W" && st !== "E" ? el("button", { type: "button", onclick: () => openOrder("DA", { race: r.name }) }, "Ally") : null,
        st !== "W" && st !== "E" ? el("button", { type: "button", class: "danger", onclick: () => openOrder("DW", { race: r.name }) }, "Declare war") : null,
        st === "A" || st === "W" ? el("button", { type: "button", onclick: () => openOrder("EWA", { race: r.name }) }, st === "W" ? "Offer peace" : "End alliance") : null,
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("GE", { race: r.name }) }, "Gift EU"),
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("GT", { race: r.name }) }, "Gift tech"),
        !atWar(st) && v.ships.length ? el("button", { type: "button", class: "ghost", onclick: () => openOrder("GS", { race: r.name }) }, "Gift ship") : null,
        r.kind === "npr" ? el("button", { type: "button", class: "ghost", onclick: () => openOrder("TTNPR", { race: r.name }) }, "Trade tech") : null,
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("DD", { race: r.name, amount: r.deny_trade ?? undefined }) }, "Deny trade"),
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("SD", { race: r.name, amount: r.split_trade ?? undefined }) }, "Split trade"),
        st !== "W" && st !== "E" ? el("button", { type: "button", class: "ghost", onclick: () => openOrder("SSI", { race: r.name }) }, "Send system info") : null,
        el("button", { type: "button", class: "ghost", onclick: () => openOrder("MESSAGE", { recipients: [r.name] }) }, "Message (with orders)"),
        humans.has(r.id) ? el("button", { type: "button", class: "ghost", onclick: () => emit("chatWith", r.id) }, "Chat privately") : null) : null));
  }
}
