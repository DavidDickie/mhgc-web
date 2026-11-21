// Rules and help: renders docs/RULEBOOK.md (served at /api/rulebook) with a small Markdown
// renderer that builds DOM nodes (never innerHTML), and indexes each order's rulebook section so
// order forms can show contextual help.  The rulebook's own "PLAYING IN YOUR BROWSER" chapter
// is the screen help (2026-11-14; it replaced a hard-coded "Using this screen" list).
"use strict";
import { api, el, clear, $ } from "./core.js";

let md = null;
let blocks = null;          // parsed blocks
const codeIndex = new Map(); // order code -> [blocks]

export async function loadRulebook() {
  if (md !== null) return;
  try { md = await api("/api/rulebook", { text: true }); } catch { md = ""; }
  blocks = parse(md);
  indexCodes();
}

// ---------------------------------------------------------------- block parser
function parse(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {
      const body = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push({ t: "pre", text: body.join("\n") });
      continue;
    }
    let m = /^(#{1,4})\s+(.*)$/.exec(ln);
    if (m) { out.push({ t: "h", level: m[1].length, text: m[2] }); i++; continue; }
    if (/^---+\s*$/.test(ln)) { out.push({ t: "hr" }); i++; continue; }
    if (/^\|/.test(ln)) {
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.replace(/^\|/, "").replace(/\|\s*$/, "").split(/(?<!\\)\|/).map(c => c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(/^\|[\s:|-]+\|?\s*$/.test(rows[1] || "") ? 2 : 1).map(cells);
      out.push({ t: "table", head, body });
      continue;
    }
    if (/^>\s?/.test(ln)) {
      const body = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ""));
      out.push({ t: "quote", lines: body });
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(ln)) {
      const items = [];
      const ordered = /^\s*\d+\./.test(ln);
      while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        const l = lines[i++];
        const mm = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(l);
        if (mm) items.push({ depth: Math.floor(mm[1].length / 2), text: mm[3] });
        else items[items.length - 1].text += " " + l.trim();
      }
      out.push({ t: "list", ordered, items });
      continue;
    }
    if (!ln.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\||>|---+\s*$|\s*([-*]|\d+\.)\s+)/.test(lines[i])) para.push(lines[i++]);
    out.push({ t: "p", text: para.join(" ") });
  }
  return out;
}

export const slug = s => s.toLowerCase().replace(/[^a-z0-9 -]/g, "").trim().replace(/\s+/g, "-");

// ---------------------------------------------------------------- inline rendering
function inline(text, hl) {
  const frag = [];
  const re = /(\\[*_\\`|[\]])|`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\((#[^)]+)\)/g;
  let last = 0, m;
  const push = s => { if (s) frag.push(...highlight(s, hl)); };
  while ((m = re.exec(text))) {
    push(text.slice(last, m.index));
    if (m[1]) push(m[1].slice(1));
    else if (m[2] !== undefined) frag.push(el("code", {}, m[2]));
    else if (m[3] !== undefined) frag.push(el("strong", {}, ...inline(m[3], hl)));
    else if (m[4] !== undefined) frag.push(el("em", {}, ...inline(m[4], hl)));
    else if (m[5] !== undefined) frag.push(el("a", { href: m[6], dataset: { anchor: m[6].slice(1) } }, m[5]));
    last = re.lastIndex;
  }
  push(text.slice(last));
  return frag;
}
function highlight(s, hl) {
  if (!hl) return [s];
  const out = [];
  const lower = s.toLowerCase();
  let i = 0, j;
  while ((j = lower.indexOf(hl, i)) >= 0) { out.push(s.slice(i, j), el("mark", {}, s.slice(j, j + hl.length))); i = j + hl.length; }
  out.push(s.slice(i));
  return out;
}
const seenSlugs = new Map();
function renderBlock(b, hl, ids, prefix = "rb-") {
  switch (b.t) {
    case "h": {
      let id = slug(b.text);
      if (ids) { const n = seenSlugs.get(id) || 0; seenSlugs.set(id, n + 1); if (n) id = `${id}-${n}`; }
      return el(`h${b.level}`, ids ? { id: `${prefix}${id}` } : {}, ...inline(b.text, hl));
    }
    case "hr": return el("hr");
    case "pre": return el("pre", {}, el("code", {}, b.text));
    case "quote": return el("blockquote", {}, b.lines.map((l, i) => [i ? el("br") : null, ...inline(l, hl)]));
    case "table": return el("table", {}, el("thead", {}, el("tr", {}, b.head.map(h => el("th", { scope: "col" }, ...inline(h, hl))))),
      el("tbody", {}, b.body.map(r => el("tr", {}, r.map(c => el("td", {}, ...inline(c, hl)))))));
    case "list": {
      const root = el(b.ordered ? "ol" : "ul");
      const stack = [root];
      for (const it of b.items) {
        while (stack.length - 1 < it.depth) { const sub = el("ul"); (stack[stack.length - 1].lastChild || stack[stack.length - 1]).append(sub); stack.push(sub); }
        while (stack.length - 1 > it.depth) stack.pop();
        stack[stack.length - 1].append(el("li", {}, ...inline(it.text, hl)));
      }
      return root;
    }
    default: return el("p", {}, ...inline(b.text, hl));
  }
}

// ---------------------------------------------------------------- order code -> rulebook section
function indexCodes() {
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    if (b.t === "h" && b.level === 4) {
      const sec = [b];
      let j = i + 1;
      while (j < blocks.length && !(blocks[j].t === "h" && blocks[j].level <= 4)) sec.push(blocks[j++]);
      const first = sec[1] && sec[1].t === "p" ? sec[1].text : "";
      const m = /^Classic codes?: (.*)$/.exec(first);
      if (m) for (const c of m[1].matchAll(/`([A-Z]+)\b/g)) if (!codeIndex.has(c[1])) codeIndex.set(c[1], sec);
    }
    if (b.t === "list") {
      for (const it of b.items) {
        const m = /classic code: `([A-Z]+)\b/.exec(it.text);
        if (m && !codeIndex.has(m[1])) codeIndex.set(m[1], [{ t: "p", text: it.text }]);
      }
    }
  }
}
export function helpFor(code) {
  const sec = blocks && codeIndex.get(code);
  if (!sec) return null;
  return el("div", {}, sec.map(b => renderBlock(b)),
    el("p", {}, el("button", { type: "button", class: "link", onclick: () => openHelp(sec[0].t === "h" ? sec[0].text : code) }, "Open in the rulebook")));
}

// ---------------------------------------------------------------- one rendering, two places
// The Help dialog (#helpText/#helpToc, ids "rb-...") and the Rules tab (ids "rp-...") both show
// the rulebook through renderInto, with the same contents list and search.
function renderInto(art, toc, hl, prefix, onJump) {
  seenSlugs.clear();
  const nodes = blocks.map(b => renderBlock(b, hl, true, prefix));
  clear(art, nodes);
  clear(toc);
  const jump = n => { n.scrollIntoView(); if (onJump) onJump(n); };
  for (const n of art.querySelectorAll("h2, h3")) {
    if (!n || n.id === `${prefix}table-of-contents`) continue;
    if (toc.querySelector(`a[href="#${n.id}"]`)) continue;
    toc.append(el("a", { href: `#${n.id}`, class: n.tagName === "H3" ? "l3" : "l2", onclick: e => { e.preventDefault(); jump(n); } }, n.textContent));
  }
  art.querySelectorAll("a[data-anchor]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    const t = art.querySelector(`#${prefix}${a.dataset.anchor}`) || art.querySelector(`#${prefix}${a.dataset.anchor.replace(/-1$/, "")}`);
    if (t) jump(t);
  }));
}
// search box behaviour shared by both: highlight from 3 letters, Enter jumps to the next match
function wireSearch(input, art, rerender) {
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = input.value.trim().toLowerCase();
      rerender(q.length >= 3 ? q : null);
      if (q.length >= 3) { const m = art.querySelector("mark"); if (m) m.scrollIntoView({ block: "center" }); }
    }, 250);
  });
  input.addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const marks = [...art.querySelectorAll("mark")];
    if (!marks.length) return;
    const top = art.scrollTop + art.clientHeight / 2 + 5;
    const next = marks.find(m => m.offsetTop > top) || marks[0];
    next.scrollIntoView({ block: "center" });
  });
}

// ---------------------------------------------------------------- the help dialog
let rendered = false;
function renderAll(hl) {
  renderInto($("helpText"), $("helpToc"), hl, "rb-");
  rendered = true;
}
export async function openHelp(target) {
  await loadRulebook();
  if (!rendered) renderAll();
  const dlg = $("helpDlg");
  if (!dlg.open) dlg.showModal();
  if (target) {
    const t = $("helpText").querySelector(`#rb-${slug(target)}`) || [...$("helpText").querySelectorAll("h2,h3,h4")].find(h => h.textContent.toLowerCase().includes(String(target).toLowerCase()));
    if (t) { t.scrollIntoView(); return; }
  }
  $("helpText").focus();
}
export function initHelp() {
  wireSearch($("helpSearch"), $("helpText"), hl => renderAll(hl));
}

// ---------------------------------------------------------------- the Rules tab
// Built once and kept: the app re-renders panels often (polling, draft changes), and rebuilding
// 1900 lines of rules each time would lose the reader's place.  The article scrolls on its own;
// its position is remembered across tab switches (a hidden element can lose its scroll offset).
let rulesPane = null, rulesScroll = 0;
export async function renderRules(box) {
  if (rulesPane && box.contains(rulesPane.root)) { restoreRules(); return; }
  if (blocks === null) {
    clear(box, el("p", { class: "hint" }, "Loading the rulebook…"));
    await loadRulebook();
  }
  const art = el("article", { class: "md rules-text", id: "rulesText", tabindex: "-1" });
  const toc = el("nav", { class: "help-toc rules-toc", "aria-label": "Rulebook contents" });
  const search = el("input", { type: "search", id: "rulesSearch", placeholder: "Search the rules…", "aria-label": "Search the rules" });
  const details = el("details", { class: "rules-contents" }, el("summary", {}, "Contents"), toc);
  const root = el("div", { class: "rules-pane" },
    el("div", { class: "rules-head" }, search, details), art);
  const render = hl => renderInto(art, toc, hl, "rp-", () => { details.open = false; });
  render(null);
  wireSearch(search, art, render);
  art.addEventListener("scroll", () => { if (art.offsetParent) rulesScroll = art.scrollTop; }, { passive: true });
  rulesPane = { root, art };
  clear(box, root);
  box.classList.add("rules");
  restoreRules();
}
function restoreRules() {
  const art = rulesPane.art;
  requestAnimationFrame(() => { art.scrollTop = rulesScroll; });
}
