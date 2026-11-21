// Production tab: every own system with its profile, the projected end-of-turn stockpiles and
// happiness, infrastructure and tech-install flags, and an inline profile editor that turns the
// changes into CSP orders.  The projection is computed by the server with the real engine
// (POST /api/games/{gid}/production/preview, mhgc/engine/preview.py); this file only displays it.
// AU, IU and EU are edited independently (Dave 2026-11-14: no auto-balancing).  A row whose split
// isn't a valid CSP (three whole numbers 10-80 totalling exactly 100) is shown in red with a hint,
// isn't sent to the preview (its projection is dimmed as stale), and is skipped by "Generate".
"use strict";
import { S, api, el, clear, fmt, emit, toast, canOrder, isHistory, on, getPref, setPref } from "./core.js";
import { saveDraft, rowToDict, openOrder } from "./orders.js";

const KEYS = ["au", "iu", "eu"];
// Production presets (Dave 2026-11-15): one line each, AU / IU / EU %, every share 10-80 and
// totalling exactly 100.  Balanced is 20/40/40 (confirmed by Dave 2026-11-20; G-14).
export const PRESETS = [
  { key: "very-early", label: "Very early", au: 50, iu: 40, eu: 10 },
  { key: "early",      label: "Early",      au: 20, iu: 60, eu: 20 },
  { key: "balanced",   label: "Balanced",   au: 20, iu: 40, eu: 40 },
  { key: "late",       label: "Late",       au: 10, iu: 10, eu: 80 },
  { key: "war",        label: "War",        au: 10, iu: 80, eu: 10 },
];
const presetLabel = p => `${p.label} ${p.au}/${p.iu}/${p.eu}`;
const presetOf = s => PRESETS.find(p => KEYS.every(k => p[k] === s[k]));
// The table's sort: kept in the browser's prefs ("sort.production", like the other tables);
// a browser that never chose one gets population, largest first (Dave 2026-11-15).
const SORT_DEFAULT = { key: "pop", dir: -1 };
const SORT_COLS = {
  name: { get: r => r.name, num: false },
  pop: { get: r => r.pop, num: true },
  mood: { get: r => r.happy_after, num: true },
  au: { get: r => r.au_after, num: true },
  iu: { get: r => r.iu_after, num: true },
  eu: { get: r => r.production.eu, num: true },
};
function sortState() {
  const saved = getPref("sort.production", null);
  return saved && SORT_COLS[saved.key] ? { key: saved.key, dir: saved.dir < 0 ? -1 : 1 } : { ...SORT_DEFAULT };
}
function sortedSystems(list) {
  const st = sortState(), c = SORT_COLS[st.key];
  return list.slice().sort((a, b) => {
    const x = c.get(a), y = c.get(b);
    const d = typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""), undefined, { numeric: true });
    return d * st.dir || a.name.localeCompare(b.name);
  });
}
function sortBy(key) {
  const st = sortState();
  if (st.key === key) st.dir = -st.dir; else { st.key = key; st.dir = SORT_COLS[key].num ? -1 : 1; }
  setPref("sort.production", st);
  build();
}
const P = {
  gid: null, turn: null,
  data: null,          // last preview response
  edits: {},           // {system id: {au, iu, eu}} — only rows the player changed; may be invalid
                       // while being edited (NaN for an empty field)
  open: new Set(),     // rows with the detail line shown
  notes: {},           // system id -> the last Tweak's note ("+2 units: ...", "Already optimal")
  seq: 0, timer: null, loading: false, error: "",
  refs: {},            // system id -> {tr, cells..., inputs}
  box: null,
};

const same = (a, b) => a && b && KEYS.every(k => a[k] === b[k]);
const sum = s => KEYS.reduce((t, k) => t + (Number(s[k]) || 0), 0);
const rowOf = id => P.data && P.data.systems.find(r => r.id === id);
const changedIds = () => Object.keys(P.edits).map(Number).filter(id => { const r = rowOf(id); return r && !same(P.edits[id], r.base); });
const BAND = { RB: "Rebellion", UH: "Unhappy", NH: "Not happy", HA: "Happy", VH: "Very happy", EH: "Extremely happy" };
const badBand = b => b === "RB" || b === "UH" || b === "NH";

// A split is a valid CSP when each share is a whole number 10-80 (rules:359) and they total
// exactly 100.  Returns null when valid, otherwise the hint to show on the row.
export function splitProblem(s) {
  const total = sum(s);
  if (KEYS.some(k => !Number.isInteger(s[k]))) return `must total 100 (now ${fmt(total)}; fill in all three)`;
  if (total !== 100) return `must total 100 (now ${fmt(total)})`;
  if (KEYS.some(k => s[k] < 10 || s[k] > 80)) return "each share must be 10–80";
  return null;
}
const validIds = () => changedIds().filter(id => !splitProblem(P.edits[id]));
const invalidIds = () => changedIds().filter(id => splitProblem(P.edits[id]));

// ---------------------------------------------------------------- server calls
async function fetchPreview() {
  const seq = ++P.seq;
  const overrides = {};
  for (const id of Object.keys(P.edits)) if (!splitProblem(P.edits[id])) overrides[id] = P.edits[id];
  P.loading = true; setStatus();
  try {
    const d = await api(`/api/games/${S.gid}/production/preview`, { gid: S.gid, body: { overrides } });
    if (seq !== P.seq) return;                 // a newer request is on its way
    const shape = !P.data || P.data.systems.map(r => r.id).join() !== d.systems.map(r => r.id).join();
    P.data = d; P.error = "";
    // forget edits that now equal the base (e.g. after "Generate CSP orders")
    for (const id of Object.keys(P.edits)) { const r = rowOf(Number(id)); if (!r || same(P.edits[id], r.base)) delete P.edits[id]; }
    if (shape || !P.refs || !Object.keys(P.refs).length) build(); else update();
  } catch (e) {
    if (seq !== P.seq) return;
    P.error = e.message; setStatus();
  } finally { if (seq === P.seq) { P.loading = false; setStatus(); } }
}
function schedule(ms = 220) { clearTimeout(P.timer); P.timer = setTimeout(fetchPreview, ms); setStatus(true); }

// ---------------------------------------------------------------- render
export function renderProduction(box) {
  P.box = box;
  const v = S.currentView;
  if (P.gid !== S.gid || P.turn !== v.current_turn) { P.gid = S.gid; P.turn = v.current_turn; P.data = null; P.edits = {}; P.notes = {}; P.open.clear(); }
  if (isHistory()) {
    clear(box, el("h2", {}, "Production"), el("p", { class: "hint" }, "The production preview is for the current turn. Use \"Back to the current turn\" to see it."));
    return;
  }
  if (!S.view.seat.needs_orders) { clear(box, el("h2", {}, "Production"), el("p", { class: "hint" }, "Your empire gives no orders, so there is nothing to preview.")); return; }
  if (P.data) build();
  else clear(box, el("h2", {}, "Production"), el("p", { class: "hint", id: "prodStatus" }, "Projecting…"));
  fetchPreview();
}

function setStatus(pending) {
  const s = document.getElementById("prodStatus");
  if (!s) return;
  s.textContent = P.error ? `Couldn't project: ${P.error}` : (pending || P.loading) ? "Updating…" : "";
  s.className = P.error ? "err" : "hint";
}

function build() {
  const box = P.box, d = P.data;
  if (!box || !d) return;
  const may = canOrder();
  P.refs = {};
  const st = sortState();
  // sortable headers (click again to reverse); the sort is applied when the table is built, so
  // rows don't jump about while a split is being edited
  const sh = (key, label, title, num) => el("th", { scope: "col", class: num ? "num" : "", title, dataset: { sort: key },
    "aria-sort": st.key === key ? (st.dir > 0 ? "ascending" : "descending") : undefined },
    el("button", { type: "button", class: "sort-btn", onclick: () => sortBy(key) }, label));
  const head = el("tr", {},
    sh("name", "System", "System name (click to sort)"),
    sh("pop", "Pop", "Population (hover a value for the population after growth)", true),
    sh("mood", "Mood", "Happiness now → after feeding (before uprisings and emperor days)"),
    el("th", { scope: "col", title: "Production profile AU / IU / EU %: each 10–80, must total exactly 100. Each field is edited on its own, or pick a preset." }, "AU/IU/EU %"),
    sh("au", "AU", "AU stockpile at the end of the turn: + production − fed to the population", true),
    sh("iu", "IU", "IU stockpile at the end of the turn: + production − order costs − SISD/autosupply", true),
    sh("eu", "EU", "EU produced (EU goes to the empire stockpile)", true),
    el("th", { scope: "col", title: "Flags: ⚠ infrastructure below population; ★ a system technology you can install now" }, "Flags"));
  const body = el("tbody");
  for (const r of sortedSystems(d.systems)) body.append(...rowEls(r, may));
  const t = d.totals;
  P.refs.total = {
    pop: el("td", { class: "num" }), au: el("td", { class: "num" }), iu: el("td", { class: "num" }), eu: el("td", { class: "num" }),
  };
  const foot = el("tfoot", {}, el("tr", { class: "totals" }, el("th", { scope: "row" }, "Total"), P.refs.total.pop, el("td"), el("td"),
    P.refs.total.au, P.refs.total.iu, P.refs.total.eu, el("td")));
  const gen = el("button", { type: "button", class: "primary", id: "genCsp", onclick: generate }, "Generate CSP orders");
  const resetAll = el("button", { type: "button", class: "ghost small", id: "resetAll", onclick: () => { P.edits = {}; P.notes = {}; build(); schedule(0); } }, "Reset all");
  const tweakAll = el("button", { type: "button", class: "ghost small", id: "tweakAll", disabled: !may, onclick: () => tweak(P.data.systems.map(r => r.id)),
    title: TWEAK_TITLE + " Every row with a valid split is tweaked; rows in red are skipped." }, "± Tweak all");
  const setAll = el("select", { id: "presetAll", class: "preset", disabled: !may, "aria-label": "Set every row's split to a preset",
    title: "Set every system's AU/IU/EU split to a preset (you can still change rows afterwards)" },
    el("option", { value: "" }, "Set all to…"), PRESETS.map(p => el("option", { value: p.key }, presetLabel(p))));
  setAll.addEventListener("change", () => { const p = PRESETS.find(q => q.key === setAll.value); setAll.value = ""; if (p) applyPresetAll(p); });
  P.refs.gen = gen; P.refs.resetAll = resetAll;
  P.refs.empire = el("div", { class: "prod-empire" });
  P.refs.extra = el("div");
  clear(box,
    el("h2", {}, "Production", el("span", { class: "hint", id: "prodStatus", role: "status" })),
    el("p", { class: "estimate", id: "prodEstimate" }, "Estimate, before random events and combat."),
    el("div", { class: "tbl-wrap prod-wrap" }, el("table", { class: "tbl prod", id: "prodTable" }, el("thead", {}, head), body, foot)),
    el("div", { class: "row-end prod-actions" }, setAll, tweakAll, resetAll, gen),
    P.refs.empire, P.refs.extra);
  update();
  setStatus();
}

function rowEls(r, may) {
  const ed = P.edits[r.id] || r.base;
  const ins = {};
  const split = el("div", { class: "split" }, KEYS.map(k => {
    const i = el("input", { type: "number", min: 10, max: 80, step: 1, value: ed[k], disabled: !may, id: `sp-${r.id}-${k}`,
      "aria-label": `${r.name} ${k.toUpperCase()} %`, class: `sp-${k}` });
    i.addEventListener("input", () => setField(r.id, k, i.value, k));
    ins[k] = i;
    return i;
  }));
  const hint = el("div", { class: "split-hint", id: `sphint-${r.id}`, role: "status", hidden: true });
  const preset = el("select", { class: "preset", id: `preset-${r.id}`, disabled: !may, "aria-label": `${r.name} preset split`, title: "Set this row's split to a preset" },
    el("option", { value: "" }, "Preset…"), PRESETS.map(p => el("option", { value: p.key }, presetLabel(p))));
  preset.addEventListener("change", () => { const p = PRESETS.find(q => q.key === preset.value); if (p) applyPreset(r.id, p); });
  const reset = el("button", { type: "button", class: "ghost small reset", title: "Back to the current profile", "aria-label": `Reset ${r.name}`, onclick: () => { delete P.edits[r.id]; setNote(r.id, null); syncInputs(r.id); markRow(r.id); schedule(0); } }, "↺");
  const tw = el("button", { type: "button", class: "ghost small tweak", id: `tweak-${r.id}`, disabled: !may, title: TWEAK_TITLE, "aria-label": `Tweak ${r.name}`, onclick: () => tweak([r.id]) }, "±");
  const note = el("div", { class: "tweak-note", id: `sptweak-${r.id}`, role: "status", hidden: !P.notes[r.id] });
  if (P.notes[r.id]) { note.textContent = P.notes[r.id].text; note.classList.toggle("gain", P.notes[r.id].gain > 0); }
  const expand = el("button", { type: "button", class: "ghost small exp", "aria-expanded": P.open.has(r.id) ? "true" : "false", "aria-label": `Details for ${r.name}`, onclick: () => toggle(r.id) }, "▸");
  const name = el("button", { type: "button", class: "linkish", title: "Show on the map", onclick: () => { const s = S.view.systems.find(q => q.id === r.id); if (s) emit("goto", { x: s.x, y: s.y, kind: "system", id: s.id }); } }, r.name);
  const cells = { pop: el("td", { class: "num" }), mood: el("td"), au: el("td", { class: "num" }), iu: el("td", { class: "num" }), eu: el("td", { class: "num" }), flags: el("td", { class: "flags" }), splitTd: el("td", { class: "split-td" }, split, preset, tw, reset, hint, note) };
  const tr = el("tr", { id: `prow-${r.id}`, dataset: { sid: r.id } }, el("td", { class: "nm" }, expand, name), cells.pop, cells.mood, cells.splitTd, cells.au, cells.iu, cells.eu, cells.flags);
  const detail = el("tr", { class: "prod-detail", hidden: !P.open.has(r.id) }, el("td", { colspan: 8 }));
  P.refs[r.id] = { tr, detail, ins, reset, expand, hint, preset, tw, note, ...cells };
  return [tr, detail];
}

function toggle(id) {
  if (P.open.has(id)) P.open.delete(id); else P.open.add(id);
  const ref = P.refs[id];
  ref.detail.hidden = !P.open.has(id);
  ref.expand.setAttribute("aria-expanded", P.open.has(id) ? "true" : "false");
  ref.expand.textContent = P.open.has(id) ? "▾" : "▸";
  fillDetail(id);
}

// One field changes; the other two stay as they are (no coupling).  `from` is the control the
// value came from ("au"/"iu"/"eu" for the number input, "slider" for a slider), which is not
// rewritten, so typing isn't disturbed.
function setField(id, key, raw, from) {
  const r = rowOf(id);
  if (!r) return;
  const txt = String(raw).trim();
  const v = txt === "" ? NaN : Number(txt);
  P.edits[id] = { ...(P.edits[id] || r.base), [key]: v };
  setNote(id, null);
  syncInputs(id, from === "slider" ? null : key, from === "slider" ? key : null);
  markRow(id);
  schedule();
}

// A preset sets all three shares at once, as if typed: the row is marked changed (when it
// differs from the current profile) and the live preview runs.
function applyPreset(id, p) {
  const r = rowOf(id);
  if (!r) return;
  P.edits[id] = { au: p.au, iu: p.iu, eu: p.eu };
  setNote(id, null);
  syncInputs(id);
  markRow(id);
  schedule();
}
function applyPresetAll(p) {
  if (!P.data) return;
  for (const r of P.data.systems) { P.edits[r.id] = { au: p.au, iu: p.iu, eu: p.eu }; setNote(r.id, null); syncInputs(r.id); markRow(r.id); }
  schedule();
  toast(`Every system set to ${presetLabel(p)}. Generate CSP orders to put the changes in your draft.`, "info", 4000);
}

function syncInputs(id, exceptInput, exceptSlider) {
  const ref = P.refs[id], r = rowOf(id);
  if (!ref || !r) return;
  const s = P.edits[id] || r.base;
  const pm = presetOf(s);
  ref.preset.value = pm ? pm.key : "";
  ref.preset.classList.toggle("match", !!pm);
  ref.preset.title = pm ? `Preset: ${presetLabel(pm)} (pick another to change the split)` : "Set this row's split to a preset";
  for (const k of KEYS) {
    const ok = Number.isFinite(s[k]);
    if (k !== exceptInput && (!ok || Number(ref.ins[k].value) !== s[k] || ref.ins[k].value === "")) ref.ins[k].value = ok ? s[k] : "";
    const sl = ref.detail.querySelector(`input[type=range][data-k=${k}]`);
    if (sl) {
      if (k !== exceptSlider && ok) sl.value = s[k];
      sl.nextElementSibling.textContent = ok ? `${s[k]}%` : "–";
    }
  }
}

function markRow(id) {
  const ref = P.refs[id], r = rowOf(id);
  if (!ref || !r) return;
  const ch = !!P.edits[id] && !same(P.edits[id], r.base);
  const bad = ch ? splitProblem(P.edits[id]) : null;
  ref.tr.classList.toggle("changed", ch);
  ref.tr.classList.toggle("invalid", !!bad);
  ref.reset.hidden = !ch;
  ref.hint.hidden = !bad;
  ref.hint.textContent = bad || "";
  for (const k of KEYS) ref.ins[k].setAttribute("aria-invalid", bad ? "true" : "false");
  markStale(id);
  updateButtons();
}

// The projection of an invalid row is the server's for its current profile (the edit isn't
// sent), so it is dimmed and says so until the split is fixed.
function markStale(id) {
  const ref = P.refs[id];
  if (!ref) return;
  const stale = !!P.edits[id] && !!splitProblem(P.edits[id]);
  for (const c of ["mood", "au", "iu", "eu", "flags"]) ref[c].classList.toggle("stale", stale);
  ref.tr.title = stale ? "This row's split isn't valid yet, so its projection (dimmed) is for the current profile." : "";
}

function updateButtons() {
  if (!P.refs.gen) return;
  const n = validIds().length, bad = invalidIds().length;
  P.refs.gen.disabled = !canOrder() || !(n || bad);
  P.refs.gen.textContent = `Generate CSP orders${n ? ` (${n})` : ""}`;
  P.refs.gen.title = bad ? `${bad} row${bad > 1 ? "s don't" : " doesn't"} total 100 and will be skipped` : "";
  P.refs.resetAll.disabled = !changedIds().length;
}


function update() {
  const d = P.data;
  for (const r of d.systems) {
    const ref = P.refs[r.id];
    if (!ref) continue;
    ref.pop.textContent = fmt(r.pop, 1); ref.pop.title = `population ${fmt(r.pop, 2)} → ${fmt(r.pop_after, 2)} after growth`;
    ref.mood.title = `happiness ${fmt(r.happy, 2)} now, ${fmt(r.happy_after, 2)} after feeding`;
    clear(ref.mood, el("span", { class: badBand(r.band) ? "err" : "" }, r.band || "–"),
      r.band_after !== r.band || Math.abs(r.happy_after - r.happy) > 0.005
        ? ["→", el("span", { class: `mood-after ${badBand(r.band_after) ? "err" : ""}` }, r.lost ? "lost" : r.band_after, r.trend_after > 0 ? "▲" : r.trend_after < 0 ? "▼" : "")] : "");
    ref.au.textContent = fmt(r.au_after); ref.au.title = `+${r.production.au} produced, −${r.eaten} fed`;
    ref.iu.textContent = fmt(r.iu_after); ref.iu.title = `+${r.production.iu} produced`;
    ref.eu.textContent = fmt(r.production.eu); ref.eu.title = "EU produced (goes to the empire stockpile)";
    const flags = [];
    if (r.insufficient_infra) flags.push(el("span", { class: "flag infra", title: `Insufficient infrastructure: ${r.infra} IF for ${fmt(r.pop, 2)} population. Each IF up to the population adds production (BI, 10 IU each).` }, "⚠IF"));
    if (r.tech_available.length) flags.push(el("button", { type: "button", class: "flag tech", title: `Tech available: ${r.tech_available.map(t => `${t.name} (${t.key}, ${t.iu} IU + ${t.eu} EU)`).join("; ")}`, "aria-label": `Tech available on ${r.name}`, onclick: () => { if (!P.open.has(r.id)) toggle(r.id); } }, `★${r.tech_available.length}`));
    if (r.risk && r.risk.kind !== "emperor_day") flags.push(el("span", { class: "flag risk", title: r.risk.kind === "rebellion" ? "Happiness reaches 0: the system rebels" : `Uprising risk ${r.risk.chance}%` }, r.risk.kind === "rebellion" ? "✖ RB" : `! ${r.risk.chance}%`));
    clear(ref.flags, flags);
    syncInputs(r.id);
    markRow(r.id);
    const sp = ref.splitTd;
    sp.classList.toggle("from-draft", r.draft_csp);
    sp.title = r.draft_csp ? "Starts from the CSP already in your draft" : "";
    if (P.open.has(r.id)) fillDetail(r.id);
  }
  const t = d.totals;
  P.refs.total.pop.textContent = fmt(t.pop, 1); P.refs.total.pop.title = `population ${fmt(t.pop, 2)} → ${fmt(t.pop_after, 2)} after growth`;
  P.refs.total.au.textContent = fmt(t.au_after); P.refs.total.au.title = `+${t.production.au} produced, −${t.eaten} fed`;
  P.refs.total.iu.textContent = fmt(t.iu_after); P.refs.total.iu.title = `+${t.production.iu} produced (system stockpiles)`;
  P.refs.total.eu.textContent = fmt(t.production.eu);
  renderEmpireBlock();
}

function fillDetail(id) {
  const ref = P.refs[id], r = rowOf(id);
  if (!ref || !r) return;
  const td = ref.detail.firstElementChild;
  const s = P.edits[id] || r.base;
  const sliders = el("div", { class: "sliders" }, KEYS.map(k => {
    const out = el("output", {}, `${s[k]}%`);
    const sl = el("input", { type: "range", min: 10, max: 80, step: 1, value: Number.isFinite(s[k]) ? s[k] : 10, disabled: !canOrder(), "aria-label": `${r.name} ${k.toUpperCase()} % slider`, dataset: { k } });
    if (!Number.isFinite(s[k])) out.textContent = "–";
    sl.addEventListener("input", () => setField(id, k, sl.value, "slider"));
    return el("label", { class: "slider-row" }, el("span", {}, k.toUpperCase()), sl, out);
  }));
  const p = r.production;
  const facts = el("p", { class: "hint" },
    `Produces ${p.au} AU / ${p.iu} IU / ${p.eu} EU; feeds ${r.eaten} AU. Current profile ${r.base.au}/${r.base.iu}/${r.base.eu}${r.draft_csp ? " (from your draft)" : ""}. Infrastructure ${r.infra}.`,
    r.risk ? ` ${r.risk.kind === "emperor_day" ? `"We love the emperor" day chance ${r.risk.chance}%.` : r.risk.kind === "rebellion" ? "Happiness reaches 0: the system rebels." : `Uprising risk ${r.risk.chance}%.`}` : "");
  const techs = r.tech_available.length || r.tech_blocked.length ? el("div", { class: "techs" },
    el("strong", {}, "System technologies"),
    el("ul", {}, r.tech_available.map(t => el("li", {}, `★ ${t.name} (${t.key}): ${t.iu} IU + ${t.eu} EU${t.maint_eu ? `, ${t.maint_eu} EU/turn upkeep` : ""} `,
      el("button", { type: "button", class: "small", disabled: !canOrder(), onclick: () => openOrder("BT", { system: r.order_name, artifact: t.key }) }, "Install…"))),
    r.tech_blocked.map(t => el("li", { class: "dim" }, `${t.name} (${t.key}): ${t.reason}`)))) : null;
  clear(td, sliders, facts, techs);
}

function renderEmpireBlock() {
  const d = P.data, e = d.empire, box = P.refs.empire;
  const sign = n => (n > 0 ? `+${fmt(n)}` : fmt(n));
  const rows = e.ledger.map(l => el("tr", {}, el("td", {}, l.label + (l.count > 1 ? ` (${l.count})` : "")),
    el("td", { class: "num" }, l.iu ? sign(l.iu) : ""), el("td", { class: "num" }, l.eu ? sign(l.eu) : ""),
    el("td", { class: "num dim" }, l.system_iu ? sign(l.system_iu) : "")));
  clear(box,
    el("h3", {}, "Empire after this turn"),
    el("div", { class: "digest" },
      tile("EU stockpile", `${fmt(e.eu_start)} → ${fmt(e.eu_after)}`, "prodEu"),
      tile("IU supply depot", `${fmt(e.depot_start)} → ${fmt(e.depot_after)}`, "prodDepot"),
      tile("Produced", `${fmt(d.totals.production.au)}/${fmt(d.totals.production.iu)}/${fmt(d.totals.production.eu)}`, null, "AU / IU / EU produced by all systems"),
      tile("Autosupply", e.autosisd ? "on" : "off", null, "AUTOSISD: IUs move to the depot from random systems when ship upkeep needs them")),
    el("table", { class: "tbl ledger" }, el("thead", {}, el("tr", {}, el("th", {}, "Maintenance listing (projected)"), el("th", { class: "num" }, "Depot IU"), el("th", { class: "num" }, "EU"), el("th", { class: "num", title: "IUs from system stockpiles (not the depot)" }, "System IU"))),
      el("tbody", {}, el("tr", {}, el("td", {}, "Start of turn"), el("td", { class: "num" }, fmt(e.depot_start)), el("td", { class: "num" }, fmt(e.eu_start)), el("td")), rows,
        el("tr", { class: "totals" }, el("td", {}, "End of turn"), el("td", { class: "num" }, fmt(e.depot_after)), el("td", { class: "num" }, fmt(e.eu_after)), el("td")))),
    e.losses.length ? el("div", { class: "err" }, e.losses.map(l => el("div", {}, l.text))) : null);
  const extra = P.refs.extra;
  const o = d.orders;
  clear(extra,
    o.failed.length ? el("div", {}, el("h3", {}, "Draft orders that fail in the projection"), el("ul", { class: "small-list" }, o.failed.map(f => el("li", {}, el("code", {}, f.text), ` — ${f.error}`)))) : null,
    o.skipped.length ? el("div", {}, el("h3", {}, "Draft orders not projected"), el("ul", { class: "small-list" }, o.skipped.map(f => el("li", {}, el("code", {}, f.text), ` — ${f.reason}`)))) : null,
    el("details", { class: "prod-notes", open: true }, el("summary", {}, "What the estimate includes"), el("ul", {}, d.notes.map(n => el("li", {}, n)))));
}
function tile(k, v, id, title) { return el("div", { class: "tile", title }, el("div", { class: "k" }, k), el("div", { class: "v", id }, v)); }

// ---------------------------------------------------------------- Tweak
// The split tweak (Dave 2026-11-18; the old players' trick from Richard Aronson's FAQ): output is
// rounded down to whole units, so shares that land just above whole numbers waste less.  The
// server (POST /production/tweak, engine/economy.tweak_split) searches every valid split within
// ±3 points of each share and returns the one with the most units in which no resource goes down
// (fewest points moved on a tie; the current split if nothing beats it).  Applying it acts as
// typing: the row is changed, previewed and picked up by "Generate CSP orders".
const TWEAK_TITLE = "Tweak: move the shares by up to 3 points each to recover what rounding down to whole units wastes. AU, IU and EU never go down, so feeding and happiness are unaffected.";
const NAMES = { au: "AU", iu: "IU", eu: "EU" };
export function tweakNote(t) {
  if (t.optimal) return "Already optimal";
  const outs = t.changes.filter(c => c.out_to !== c.out_from).map(c => `${NAMES[c.key]} ${c.out_from}→${c.out_to}`);
  return `+${t.gain} unit${t.gain === 1 ? "" : "s"}: ${outs.join(", ")}`;
}
function setNote(id, n) {
  if (n) P.notes[id] = n; else delete P.notes[id];
  const ref = P.refs[id];
  if (!ref || !ref.note) return;
  ref.note.hidden = !n;
  ref.note.textContent = n ? n.text : "";
  ref.note.title = n ? n.title || "" : "";
  ref.note.classList.toggle("gain", !!n && n.gain > 0);
}
async function tweak(ids) {
  if (!P.data || !canOrder()) return;
  const one = ids.length === 1;
  const bad = ids.filter(id => P.edits[id] && splitProblem(P.edits[id]));
  const ok = ids.filter(id => !bad.includes(id));
  for (const id of bad) setNote(id, { text: "Not tweaked: fix the split first", gain: 0, title: splitProblem(P.edits[id]) });
  if (!ok.length) {
    toast(one ? `${rowOf(ids[0]).name}: the split must be valid before it can be tweaked (${splitProblem(P.edits[ids[0]])}).` : "No row has a valid split to tweak.", "error", 6000);
    return;
  }
  const overrides = {};
  for (const id of Object.keys(P.edits)) if (!splitProblem(P.edits[id])) overrides[id] = P.edits[id];
  let d;
  try {
    d = await api(`/api/games/${S.gid}/production/tweak`, { gid: S.gid, body: { overrides, systems: ok } });
  } catch (e) { toast(`Couldn't tweak: ${e.message}`, "error"); return; }
  let gain = 0, changed = 0, optimal = 0;
  for (const t of d.systems) {
    const r = rowOf(t.id);
    if (!r) continue;
    const from = `${t.split.au}/${t.split.iu}/${t.split.eu}`, to = `${t.suggestion.au}/${t.suggestion.iu}/${t.suggestion.eu}`;
    if (!t.optimal) {
      P.edits[t.id] = { ...t.suggestion };
      if (same(P.edits[t.id], r.base)) delete P.edits[t.id];
      gain += t.gain; changed++;
      syncInputs(t.id); markRow(t.id);
    } else optimal++;
    setNote(t.id, { text: tweakNote(t), gain: t.gain,
      title: t.optimal ? `No split within ±${d.max_delta} points of ${from} gives more units without lowering one.`
        : `Split ${from} → ${to}; produces ${t.before.au}/${t.before.iu}/${t.before.eu} → ${t.after.au}/${t.after.iu}/${t.after.eu} AU/IU/EU.` });
  }
  if (changed) schedule(0);
  if (one) {
    const t = d.systems[0];
    toast(`${rowOf(t.id).name}: ${tweakNote(t)}.${t.optimal ? "" : " Generate CSP orders to put it in your draft."}`, t.optimal ? "info" : "good", 4000);
  } else {
    const parts = [changed ? `+${gain} unit${gain === 1 ? "" : "s"} on ${changed} system${changed === 1 ? "" : "s"}` : "nothing to gain", optimal ? `${optimal} already optimal` : "", bad.length ? `${bad.length} skipped (not a valid split)` : ""].filter(Boolean);
    toast(`Tweak all: ${parts.join("; ")}.${changed ? " Generate CSP orders to put the changes in your draft." : ""}`, changed ? "good" : "info", 5000);
  }
}

// ---------------------------------------------------------------- CSP orders
async function generate() {
  const ids = validIds(), bad = invalidIds().length;
  const skipped = bad ? `${bad} row${bad > 1 ? "s don't" : " doesn't"} total 100` : "";
  if (!canOrder()) return;
  if (!ids.length) { if (bad) toast(`${skipped}, so no CSP orders were generated. Fix ${bad > 1 ? "them" : "it"} (shown in red) first.`, "error", 6000); return; }
  const list = S.draft.map(rowToDict);
  let added = 0, replaced = 0;
  for (const id of ids) {
    const r = rowOf(id), s = P.edits[id];
    const names = new Set([r.name, r.order_name]);
    const at = [];
    list.forEach((d, i) => { if (d.code === "CSP" && names.has(d.system)) at.push(i); });
    if (at.length) {
      const last = at[at.length - 1];
      list[last] = { code: "CSP", system: list[last].system, au: s.au, iu: s.iu, eu: s.eu };
      for (const i of at.slice(0, -1).reverse()) list.splice(i, 1);
      replaced++;
    } else { list.push({ code: "CSP", system: r.order_name, au: s.au, iu: s.iu, eu: s.eu }); added++; }
  }
  try {
    await saveDraft(list);
    toast(`${added ? `${added} CSP order${added > 1 ? "s" : ""} added` : ""}${added && replaced ? ", " : ""}${replaced ? `${replaced} replaced` : ""}.${bad ? ` Skipped: ${skipped} (still shown in red).` : ""} See the Orders tab.`, bad ? "info" : "good", bad ? 7000 : 4000);
  } catch (e) { toast(e.message, "error"); }
}

// A draft change (from any tab) changes the base profiles and costs: refresh if visible.
on("draft", () => { if (P.box && !P.box.closest("[hidden]") && S.view && !isHistory()) schedule(0); });
