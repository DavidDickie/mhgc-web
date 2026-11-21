// Final standings (DECISIONS W-16): once a game is over, every race's figures over every turn, for
// everyone in the game and from the lobby.  Plus "Export game for analysis" (W-17).
//
// Charts follow graphs.js (small multiples, recessive grid, crosshair tooltip) but with one line
// per race.  Colour: as on the map, by the viewer's relation to each race (yours / allied /
// neutral / at war / not contacted, core.js REL), or by race (an 8-hue validated categorical
// palette, offered when there are at most 8 races).  Humans are solid lines, computer empires
// dashed, so identity is never colour alone; the legend highlights a race on hover or click, the
// tooltip lists every race at the hovered turn, and the table is the non-visual view.
"use strict";
import { api, el, clear, fmt, toast, seatFor, REL } from "./core.js";

const SVGNS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
// dataviz reference palette, dark-surface steps, fixed order (slot 1 = blue = "yours" on the map)
const RACE_HUES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const SERIES = [
  ["vp", "Victory points", 0], ["systems", "Systems", 0], ["pop", "Population", 1],
  ["nnp", "Net national product", 0], ["techs", "Technologies", 0], ["eu", "EU stockpile", 0],
  ["iu_depot", "IU supply depot", 0], ["warships", "Warships", 0], ["attack", "Fleet attack", 0],
  ["troops", "Combat troops", 0], ["happiness", "Happiness per capita", 2], ["STP", "Starports", 0],
];
const COLS = [
  ["vp", "VP", 0], ["systems", "Systems", 0], ["pop", "Pop", 1], ["nnp", "NNP", 0], ["techs", "Techs", 0],
  ["warships", "Warships", 0], ["troops", "Troops", 0], ["eu", "EU", 0], ["iu_depot", "IU", 0], ["happiness", "Happy", 2],
];

let dlg = null, data = null, gidOpen = null, focusId = null;
const prefKey = "mhgcFinalColour";

function ensureDialog() {
  if (dlg) return dlg;
  dlg = el("dialog", { id: "finalDlg", class: "final-dlg", "aria-labelledby": "finalH" });
  dlg.addEventListener("close", () => { data = null; gidOpen = null; focusId = null; });
  document.body.append(dlg);
  return dlg;
}

export async function openFinal(gid) {
  ensureDialog();
  clear(dlg, el("div", { class: "final-body" }, el("p", { class: "hint" }, "Loading the final standings…")));
  if (!dlg.open) dlg.showModal();
  try { data = await api(`/api/games/${gid}/final`, { gid }); }
  catch (e) { clear(dlg, el("div", { class: "final-body" }, el("p", { class: "err" }, e.message), el("button", { type: "button", class: "ghost", onclick: () => dlg.close() }, "Close"))); return; }
  gidOpen = gid; focusId = null;
  render();
}

// ---- export ---------------------------------------------------------------------------------
export async function exportGame(gid) {
  const s = seatFor(gid);
  try {
    const res = await fetch(`/api/games/${gid}/export`, { headers: s ? { "X-Seat-Token": s.token } : {}, credentials: "same-origin" });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
      toast(msg, "error", 9000); return;
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename="([^"]+)"/.exec(cd);
    const a = el("a", { href: URL.createObjectURL(blob), download: m ? m[1] : `mhgc-${gid}.zip` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    toast("Export downloaded: send the zip for analysis (tools/analyze_game.py reads it).", "good", 7000);
  } catch (e) { toast(e.message, "error"); }
}
// May this browser export now?  Game over: any seat.  Before: the host, in any game (W-17).
export function canExport(summary, seat) {
  if (!summary || !seat) return false;
  if (summary.finished) return true;
  return summary.host_seat === seat;
}
export function exportButton(gid, label = "Export game for analysis", cls = "ghost small") {
  return el("button", { type: "button", class: cls, title: "Download a zip with every turn's orders and results, the standings of every race and the computer empires' decision log", onclick: () => exportGame(gid) }, label);
}

// ---- rendering ------------------------------------------------------------------------------
function colourMode() {
  const can = canByRace(), rel = data.viewer !== null && data.viewer !== undefined;
  let m = localStorage.getItem(prefKey) || (rel ? "relation" : "race");
  if (m === "relation" && !rel) m = can ? "race" : "relation";
  if (m === "race" && !can) m = "relation";
  return m;
}
const canByRace = () => data.empires.length <= RACE_HUES.length;

function colourOf(e, mode) {
  if (mode === "race") {
    // the viewer's own race keeps slot 1 (blue, as "yours" on the map); the rest in id order
    const order = [...data.empires].sort((a, b) => (b.relation === "own") - (a.relation === "own") || a.id - b.id);
    return RACE_HUES[order.findIndex(x => x.id === e.id) % RACE_HUES.length];
  }
  return (REL[e.relation] || REL.none).color;
}
const who = e => e.human ? (e.player ? `${e.player} (human)` : "Human (open seat)") : `Computer${e.persona ? ` · ${e.persona}` : ""}${e.converted_turn !== null && e.converted_turn !== undefined ? ` (${e.player ? e.player + "'s race, " : ""}handed over at turn ${e.converted_turn})` : ""}`;

function render() {
  const mode = colourMode();
  const g = data.game;
  const winner = data.empires.find(e => e.id === data.winner);
  const seat = seatFor(gidOpen);
  const held = seat && (seat.seat === 0 || g.seats.some(s => s.seat === seat.seat && !s.open));
  const head = el("div", { class: "final-head row-between" },
    el("div", {}, el("h2", { id: "finalH" }, "Final standings"),
      el("p", { class: "hint" }, `${g.name} · ${g.size} empires · ${data.turns.length - 1} turns${winner ? ` · ♛ the ${winner.name} won` : ""}`)),
    el("div", { class: "row gap" },
      held ? exportButton(gidOpen) : null,
      el("button", { type: "button", class: "ghost", onclick: () => dlg.close() }, "Close")));
  const modes = [["relation", "As on your map", data.viewer !== null && data.viewer !== undefined], ["race", "By race", canByRace()]];
  const controls = el("div", { class: "final-controls row gap" },
    el("span", { class: "dim" }, "Colour"),
    el("div", { class: "subtabs", role: "group", "aria-label": "Line colours" }, modes.map(([m, l, ok]) => el("button", {
      type: "button", class: `chip-btn ${m === mode ? "on" : "ghost"}`, "aria-pressed": m === mode ? "true" : "false", disabled: !ok,
      title: ok ? "" : m === "relation" ? "Only for players seated in this game" : "Up to 8 races",
      onclick: () => { localStorage.setItem(prefKey, m); render(); } }, l))),
    el("span", { class: "dim" }, "— solid: human · dashed: computer"));
  const legend = el("div", { class: "final-legend", role: "list", "aria-label": "Races" }, data.empires.map(e => {
    const c = colourOf(e, mode);
    const sw = sv("svg", { width: 26, height: 10, "aria-hidden": "true" });
    sw.append(sv("line", { x1: 1, x2: 25, y1: 5, y2: 5, stroke: c, "stroke-width": e.human ? 3 : 2, "stroke-dasharray": e.human ? "" : "4 3", "stroke-linecap": "round" }));
    return el("button", { type: "button", role: "listitem", class: `leg${focusId === e.id ? " on" : ""}`, "aria-pressed": focusId === e.id ? "true" : "false", "data-id": e.id,
      title: `${who(e)}${mode === "relation" ? ` · ${(REL[e.relation] || REL.none).label}` : ""}. Click to highlight.`,
      onmouseenter: () => highlight(e.id), onmouseleave: () => highlight(focusId), onfocus: () => highlight(e.id), onblur: () => highlight(focusId),
      onclick: () => { focusId = focusId === e.id ? null : e.id; render(); } }, sw, e.name, e.human ? el("span", { class: "tag" }, "human") : null);
  }));
  const relKey = mode === "relation" ? el("p", { class: "hint" }, "Colours as on your map: ", ...["own", "ally", "neutral", "war", "stranger"].map(k => el("span", { class: "relkey" }, el("span", { class: "sw", style: { background: REL[k].color } }), REL[k].label))) : null;
  clear(dlg, el("div", { class: "final-body" }, head, table(mode), controls, relKey, legend,
    el("div", { class: "final-graphs" }, SERIES.map(([k, l, d]) => chart(k, l, d, mode)))));
  highlight(focusId);
}

function table(mode) {
  const byId = Object.fromEntries(data.empires.map(e => [e.id, e]));
  return el("div", { class: "tbl-wrap final-tbl" }, el("table", { class: "tbl" },
    el("caption", { class: "sr-only" }, "Final standings, ranked by victory points"),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", class: "num" }, "#"), el("th", { scope: "col" }, "Race"), el("th", { scope: "col" }, "Played by"),
      COLS.map(([, l]) => el("th", { scope: "col", class: "num" }, l)))),
    el("tbody", {}, data.final.map(r => {
      const e = byId[r.id] || r;
      return el("tr", { class: `${r.id === data.winner ? "winner" : ""}${e.relation === "own" ? " you" : ""}` },
        el("td", { class: "num" }, r.rank ?? "–"),
        el("td", {}, el("span", { class: "sw", style: { background: colourOf(e, mode) } }), r.name, r.id === data.winner ? " ♛" : "", r.kind === "dead" ? el("span", { class: "dim" }, " (extinct)") : null,
          r.unranked ? el("span", { class: "dim", title: "The host's race in a game with other human players: it can't win and earns no ranking VP (W-28)" }, " (host, unranked)") : null),
        el("td", { class: "dim" }, who(e)),
        COLS.map(([k, , d]) => el("td", { class: "num" }, fmt(r[k], d))));
    }))));
}

function highlight(id) {
  if (!dlg) return;
  for (const p of dlg.querySelectorAll("path.race")) {
    const on = id === null || id === undefined || Number(p.dataset.id) === id;
    p.setAttribute("opacity", on ? 1 : 0.15);
    if (on && id !== null && id !== undefined) p.parentNode.append(p);      // bring to front
  }
}

function chart(key, label, digits, mode) {
  const W = 320, H = 150, L = 34, R = 8, T = 10, B = 18;
  const turns = data.turns;
  const lines = data.empires.map(e => ({ e, c: colourOf(e, mode), v: (data.series[key] || {})[e.id] || [] }));
  const all = lines.flatMap(l => l.v.filter(x => x !== null && x !== undefined));
  const hi = Math.max(0, ...all), min = Math.min(0, ...all);
  const max = hi > min ? hi : min + 1;          // an all-zero series still gets a 0..1 axis
  const t0 = turns[0] || 0, t1 = turns[turns.length - 1] || 1;
  const X = t => L + (t1 === t0 ? (W - L - R) / 2 : (t - t0) / (t1 - t0) * (W - L - R));
  const Y = v => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": `${label} over turns, one line per race` });
  for (const v of [min, (min + max) / 2, max]) {
    svg.append(sv("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#ffffff1a", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    const tx = sv("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end", fill: "#8f9bb6", "font-size": 9 }); tx.textContent = short(v); svg.append(tx);
  }
  for (const t of [t0, Math.round((t0 + t1) / 2), t1]) { const tx = sv("text", { x: X(t), y: H - 5, "text-anchor": "middle", fill: "#8f9bb6", "font-size": 9 }); tx.textContent = `T${t}`; svg.append(tx); }
  // humans last, so they draw on top
  for (const l of [...lines].sort((a, b) => a.e.human - b.e.human)) {
    let d = "", pen = false;
    l.v.forEach((v, i) => {
      if (v === null || v === undefined) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(turns[i]).toFixed(1)},${Y(v).toFixed(1)}`; pen = true;
    });
    if (!d) continue;
    svg.append(sv("path", { class: "race", "data-id": l.e.id, d, fill: "none", stroke: l.c, "stroke-width": l.e.human ? 2.6 : 1.7, "stroke-dasharray": l.e.human ? "" : "5 3", "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }));
  }
  const cross = sv("line", { y1: T, y2: H - B, stroke: "#e6ebf5", "stroke-width": 1, opacity: 0, "vector-effect": "non-scaling-stroke" });
  svg.append(cross);
  const tip = el("div", { class: "gtip final-tip", hidden: true });
  const lead = lines.filter(l => l.v.length).sort((a, b) => (b.v[b.v.length - 1] || 0) - (a.v[a.v.length - 1] || 0))[0];
  const box = el("div", { class: "graph final-graph" },
    el("h4", {}, el("span", {}, label), lead ? el("span", { class: "now" }, `${lead.e.name} ${fmt(lead.v[lead.v.length - 1], digits)}`) : null),
    svg, tip);
  svg.addEventListener("pointermove", ev => {
    if (!turns.length) return;
    const r = svg.getBoundingClientRect();
    const fx = (ev.clientX - r.left) / r.width * W;
    let i = 0;
    for (let j = 0; j < turns.length; j++) if (Math.abs(X(turns[j]) - fx) < Math.abs(X(turns[i]) - fx)) i = j;
    cross.setAttribute("x1", X(turns[i])); cross.setAttribute("x2", X(turns[i])); cross.setAttribute("opacity", .5);
    const rows = lines.filter(l => l.v[i] !== null && l.v[i] !== undefined).sort((a, b) => b.v[i] - a.v[i]);
    clear(tip, el("div", { class: "tt" }, `Turn ${turns[i]}`), rows.map(l => el("div", { class: `tr${focusId === l.e.id ? " on" : ""}` },
      el("span", { class: `sw${l.e.human ? "" : " dash"}`, style: { background: l.c } }), el("span", { class: "nm" }, l.e.name), el("span", { class: "v" }, fmt(l.v[i], digits)))));
    tip.hidden = false;
    const left = (X(turns[i]) / W) * r.width;
    tip.style.left = `${left > r.width * 0.6 ? left - 8 : left + 8}px`;
    tip.style.transform = left > r.width * 0.6 ? "translate(-100%, 0)" : "translate(0, 0)";
    tip.style.top = "26px";
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("opacity", 0); });
  return box;
}
function short(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${Math.round(v / 1e3)}k`;
  if (a >= 100 || Number.isInteger(v)) return String(Math.round(v));
  return v.toFixed(2);
}
