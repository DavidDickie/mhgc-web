// Statistics over turns: small multiples, one series per chart (so no legend is needed: the
// title names it), a crosshair tooltip with the value and rank, and a table view.
"use strict";
import { S, el, clear, fmt } from "./core.js";

export const STAT_LABEL = {
  GNP: "Gross national product", NNP: "Net national product", WAR: "Warships", NWR: "Non-warships",
  STP: "Starports", POP: "Population", HAP: "Happiness per capita", PRD: "Productivity per capita",
  SYS: "Systems", GWR: "Population growth rate", TEC: "Technologies", VCT: "Victory conditions",
  CTS: "Combat troops",
};
const SERIES = [
  ["VP", "Victory points", t => t.vp, null],
  ["POP", STAT_LABEL.POP, t => t.values.POP, "POP"],
  ["NNP", STAT_LABEL.NNP, t => t.values.NNP, "NNP"],
  ["GNP", STAT_LABEL.GNP, t => t.values.GNP, "GNP"],
  ["SYS", STAT_LABEL.SYS, t => t.values.SYS, "SYS"],
  ["TEC", STAT_LABEL.TEC, t => t.values.TEC, "TEC"],
  ["EU", "EU stockpile", t => t.economy.eu, null],
  ["IU", "IU supply depot", t => t.economy.iu_depot, null],
  ["WAR", STAT_LABEL.WAR, t => t.values.WAR, "WAR"],
  ["NWR", STAT_LABEL.NWR, t => t.values.NWR, "NWR"],
  ["CTS", STAT_LABEL.CTS, t => t.values.CTS, "CTS"],
  ["STP", STAT_LABEL.STP, t => t.values.STP, "STP"],
  ["HAP", STAT_LABEL.HAP, t => t.values.HAP, "HAP"],
  ["PRD", STAT_LABEL.PRD, t => t.values.PRD, "PRD"],
  ["GWR", STAT_LABEL.GWR, t => t.values.GWR, "GWR"],
];
const SVGNS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const LINE = "#3987e5";        // one series per chart: categorical slot 1, dark-mode step

function chart(key, label, get, rankKey, turns) {
  const W = 200, H = 92, L = 30, R = 6, T = 8, B = 16;
  const pts = turns.map(t => ({ turn: t.turn, v: Number(get(t)) || 0, rank: rankKey ? t.ranks[rankKey] : null }));
  const max = Math.max(1e-9, ...pts.map(p => p.v)), min = Math.min(0, ...pts.map(p => p.v));
  const t0 = pts.length ? pts[0].turn : 0, t1 = pts.length ? pts[pts.length - 1].turn : 1;
  const X = t => L + (t1 === t0 ? (W - L - R) / 2 : (t - t0) / (t1 - t0) * (W - L - R));
  const Y = v => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": `${label} over turns` });
  // recessive grid: baseline + max
  for (const v of [min, max]) {
    svg.append(sv("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#ffffff1a", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    const tx = sv("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end", fill: "#8f9bb6", "font-size": 8 }); tx.textContent = short(v); svg.append(tx);
  }
  for (const t of [t0, t1]) { const tx = sv("text", { x: X(t), y: H - 4, "text-anchor": "middle", fill: "#8f9bb6", "font-size": 8 }); tx.textContent = `T${t}`; svg.append(tx); }
  if (pts.length) {
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.turn).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
    svg.append(sv("path", { d: `${d}L${X(t1)},${Y(min)}L${X(t0)},${Y(min)}Z`, fill: LINE, opacity: .12 }));
    svg.append(sv("path", { d, fill: "none", stroke: LINE, "stroke-width": 2, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }));
    const last = pts[pts.length - 1];
    svg.append(sv("circle", { cx: X(last.turn), cy: Y(last.v), r: 2.5, fill: LINE }));
  }
  const cross = sv("line", { y1: T, y2: H - B, stroke: "#e6ebf5", "stroke-width": 1, opacity: 0, "vector-effect": "non-scaling-stroke" });
  const dot = sv("circle", { r: 3, fill: "#e6ebf5", opacity: 0 });
  svg.append(cross, dot);
  const now = pts.length ? pts[pts.length - 1] : null;
  const tip = el("div", { class: "gtip", hidden: true });
  const box = el("div", { class: "graph" },
    el("h4", {}, el("span", { title: key }, label),
      el("span", { class: "now" }, now ? fmt(now.v, 2) : "–", now && now.rank ? el("span", { class: "dim" }, ` #${now.rank}`) : null)),
    svg, tip);
  svg.addEventListener("pointermove", e => {
    if (!pts.length) return;
    const r = svg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width * W;
    let best = pts[0];
    for (const p of pts) if (Math.abs(X(p.turn) - fx) < Math.abs(X(best.turn) - fx)) best = p;
    cross.setAttribute("x1", X(best.turn)); cross.setAttribute("x2", X(best.turn)); cross.setAttribute("opacity", .5);
    dot.setAttribute("cx", X(best.turn)); dot.setAttribute("cy", Y(best.v)); dot.setAttribute("opacity", 1);
    tip.hidden = false;
    tip.textContent = `Turn ${best.turn}: ${fmt(best.v, 2)}${best.rank ? ` (rank ${best.rank})` : ""}`;
    tip.style.left = `${(X(best.turn) / W) * r.width + 6}px`;
    tip.style.top = `${(Y(best.v) / H) * r.height + 24}px`;
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); });
  return box;
}
function short(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${Math.round(v / 1e3)}k`;
  if (a >= 100 || Number.isInteger(v)) return String(Math.round(v));
  return v.toFixed(2);
}

export function renderStats(box) {
  clear(box);
  box.append(el("h2", {}, "Statistics over turns"));
  const turns = (S.stats && S.stats.turns) || [];
  if (!turns.length) { box.append(el("p", { class: "hint" }, "No statistics yet.")); return; }
  const mode = localStorage.getItem("mhgcStatsMode") || "graphs";
  box.append(el("div", { class: "subtabs", role: "group", "aria-label": "Display" },
    ["graphs", "table"].map(m => el("button", { type: "button", class: `chip-btn ${m === mode ? "on" : "ghost"}`, "aria-pressed": m === mode ? "true" : "false",
      onclick: () => { localStorage.setItem("mhgcStatsMode", m); renderStats(box); } }, m === "graphs" ? "Graphs" : "Table"))));
  box.append(el("p", { class: "hint" }, "Your own figures each turn; # is your rank among all races, computer empires included (1 = first or tied). Hover a graph for exact values."));
  if (mode === "graphs") {
    box.append(el("div", { class: "graphs" }, SERIES.map(([k, l, g, rk]) => chart(k, l, g, rk, turns))));
  } else {
    box.append(el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Turn"), SERIES.map(([k, l]) => el("th", { scope: "col", class: "num", title: l }, k)))),
      el("tbody", {}, [...turns].reverse().map(t => el("tr", {}, el("td", {}, t.turn), SERIES.map(([, , g, rk]) => el("td", { class: "num" }, fmt(Number(g(t)) || 0, 2), rk && t.ranks[rk] ? el("span", { class: "dim" }, ` #${t.ranks[rk]}`) : null))))))));
  }
}
