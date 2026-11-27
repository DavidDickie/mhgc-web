// MHGC web UI entry point: routing between the lobby and a game, the top bar, the dock tabs, the
// map wiring, history browsing and polling.
"use strict";
import { S, api, el, clear, $, on, emit, toast, confirmBox, seatFor, pinSeat, forgetSeat, setRaceName, fmt, isHistory, seatName, xy, setBoard, BOARD, HOME, byName } from "./core.js";
import { GalaxyMap } from "./map.js";
import { knownSystems } from "./world.js";
import { initLobby, showLobby, openGame } from "./lobby.js";
import { initAccount, renderAccount, openPassword, gameUrl } from "./account.js";
import { initOrderDialog, loadDraft, renderOrdersPanel, checkOrders, submitTurn, setMap } from "./orders.js";
import { renderReport } from "./report.js";
import { renderStats } from "./graphs.js";
import { renderEmpire, renderTech, renderForces, renderAgents, renderDiplomacy } from "./panels.js";
import { renderChat, fetchChat, resetChat, chatState, unreadTotal, openThread } from "./chat.js";
import { renderProduction } from "./production.js";
import { initInspector, renderInspector, moveFocusedTo } from "./inspector.js";
import { initHelp, openHelp, loadRulebook, renderRules } from "./help.js";
import { openFinal, exportButton, canExport } from "./final.js";

let map = null;
const TABS = [
  ["report", "Report", box => renderReport(box)],
  ["orders", "Orders", box => renderOrdersPanel(box)],
  ["empire", "Empire", box => renderEmpire(box)],
  ["production", "Production", box => renderProduction(box)],
  ["tech", "Tech", box => renderTech(box)],
  ["forces", "Forces", box => renderForces(box)],
  ["agents", "Leaders", box => renderAgents(box)],
  ["diplomacy", "Races", box => renderDiplomacy(box, chatState.recipients)],
  ["stats", "Stats", box => renderStats(box)],
  ["chat", "Chat", box => renderChat(box)],
  ["rules", "Rules", box => renderRules(box)],
];
let activeTab = localStorage.getItem("mhgcTab") || "report";

// ---------------------------------------------------------------- tabs
function buildTabs() {
  const bar = $("tabs"), panels = $("panels");
  clear(bar); clear(panels);
  for (const [id, label] of TABS) {
    bar.append(el("button", { type: "button", role: "tab", id: `tab-${id}`, "aria-controls": `panel-${id}`, "aria-selected": id === activeTab ? "true" : "false", tabindex: id === activeTab ? 0 : -1,
      onclick: () => showTab(id) }, label, el("span", { class: "count", id: `count-${id}`, hidden: true })));
    panels.append(el("section", { class: `panel${id === "chat" ? " chat" : ""}`, role: "tabpanel", id: `panel-${id}`, "aria-labelledby": `tab-${id}`, hidden: id !== activeTab }));
  }
  bar.addEventListener("keydown", e => {
    const i = TABS.findIndex(t => t[0] === activeTab);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const j = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
      showTab(TABS[j][0]); $(`tab-${TABS[j][0]}`).focus();
    }
  });
}
function showTab(id) {
  activeTab = id;
  localStorage.setItem("mhgcTab", id);
  for (const [t] of TABS) {
    $(`tab-${t}`).setAttribute("aria-selected", t === id ? "true" : "false");
    $(`tab-${t}`).tabIndex = t === id ? 0 : -1;
    $(`panel-${t}`).hidden = t !== id;
  }
  chatState.visible = id === "chat";
  renderTab(id);
  updateCounts();
}
function renderTab(id = activeTab) {
  if (!S.view) return;
  const t = TABS.find(x => x[0] === id);
  const box = $(`panel-${id}`);
  const scroll = box.parentElement.scrollTop;
  // a re-render (draft change, polling, new turn) must not steal the focus from a filter box
  const act = document.activeElement;
  const refocus = act && act.id && box.contains(act) ? { id: act.id, start: act.selectionStart, end: act.selectionEnd } : null;
  try { t[2](box); } catch (e) { console.error(e); clear(box, el("p", { class: "err" }, `Couldn't show this panel: ${e.message}`)); }
  box.parentElement.scrollTop = scroll;
  if (refocus) {
    const n = document.getElementById(refocus.id);
    if (n && box.contains(n)) {
      n.focus({ preventScroll: true });
      try { if (refocus.start !== null && refocus.start !== undefined) n.setSelectionRange(refocus.start, refocus.end); } catch { /* not a text input */ }
    }
  }
}
function updateCounts() {
  const set = (id, n, alert) => { const c = $(`count-${id}`); if (!c) return; c.hidden = !n; c.textContent = String(n); c.classList.toggle("alert", !!alert); };
  set("orders", S.draft.length, S.checks && S.checks.some(x => !x.ok));
  set("report", S.view ? (S.view.results.combats || []).length : 0, true);
  set("chat", unreadTotal(), true);
}
on("showTab", showTab);

// ---------------------------------------------------------------- top bar
function renderTop() {
  const v = S.view, g = S.summary;
  if (!v) return;
  $("gameName").textContent = v.game.name;
  $("empireName").textContent = v.seat.view_as ? `Viewing as the ${v.empire.name} · host` : `The ${v.empire.name} · ${v.seat.player}${v.seat.host ? " · host" : ""}`;
  document.title = `T${v.current_turn} · ${v.empire.name} · MHGC`;
  const pick = $("turnPick");
  clear(pick, Array.from({ length: v.current_turn + 1 }, (_, i) => v.current_turn - i).map(n => el("option", { value: n, selected: n === v.game.turn }, n === v.current_turn ? `Turn ${n} (now)` : `Turn ${n}`)));
  $("turnPrev").disabled = v.game.turn === 0;
  $("turnNext").disabled = v.game.turn === v.current_turn;
  const cur = S.currentView || v;
  const e = cur.empire;
  const chip = (k, val, title) => el("div", { title }, el("dt", {}, k), el("dd", {}, val));
  clear($("chips"), chip("EU", fmt(e.eu), "EU stockpile"), chip("IU", fmt(e.iu_depot), "IU supply depot"), chip("VP", e.unranked ? `${e.vp}/–` : `${e.vp}/${cur.game.vp_to_win}`, e.unranked ? "Victory points (host, unranked). As host of a multi-player game your race can't win and earns no ranking VP (DECISIONS W-28)." : "Victory points"),
    chip("Sys", fmt(e.stats.SYS), "Systems"), chip("Pop", fmt(e.stats.POP, 1), "Population"), chip("Ships", fmt(cur.ships.length), "Ships"), chip("Tech", fmt(e.techs.length - 1), "Technologies"));
  const wb = $("waitBox");
  clear(wb);
  if (cur.game.winner) wb.append(el("strong", { class: "warnc" }, `♛ ${cur.game.winner_name} won`), el("br"),
    el("button", { type: "button", class: "small primary final-link", onclick: () => openFinal(S.gid) }, "Final standings"));
  else if (g && g.humans === 1 && !g.host_runs && canExport(g, v.seat.seat)) wb.append(exportButton(S.gid, "Export for analysis", "small ghost final-link"));
  else if (g && g.host_runs) wb.append(el("span", { class: "sub" }, "No human gives orders"), el("br"), el("span", {}, `Waiting for the host to run turn ${cur.current_turn + 1}`));
  else if (g) {
    const others = g.waiting_for.filter(s => s !== v.seat.seat);
    wb.append(el("span", { class: `sub ${S.submitted ? "yes" : "no"}` }, S.submitted ? "Submitted" : "Orders open"), el("br"),
      el("span", {}, others.length ? `Waiting for ${others.map(seatName).join(", ")}` : S.submitted ? "Running…" : "Everyone else is in"));
  }
  const may = cur.seat.needs_orders && !cur.game.winner;
  $("submitBtn").textContent = S.submitted ? "Withdraw" : "Submit turn";
  $("submitBtn").className = S.submitted ? "ghost" : "primary";
  $("submitBtn").disabled = !may;
  $("checkBtn").disabled = !may;
  updateCheckBtn();
  $("checkBtn").hidden = $("submitBtn").hidden = !!cur.seat.view_as;     // the host viewing as a race
  $("forceBtn").hidden = !cur.seat.host || !!cur.game.winner;
  $("forceBtn").textContent = g && g.host_runs ? "Run turn" : "Force turn";
  $("forceBtn").className = g && g.host_runs ? "primary" : "danger";
  $("run5Btn").hidden = $("forceBtn").hidden || !(g && g.host_runs);
  renderAccount();
  const hb = $("historyBanner");
  hb.hidden = !isHistory();
  if (isHistory()) clear(hb, el("span", {}, `You are looking at turn ${v.game.turn}. The map and results are as they were then.`),
    el("button", { type: "button", class: "small", onclick: () => showTurn(v.current_turn) }, "Back to the current turn"));
  // search list
  clear($("searchList"), byName(knownSystems().filter(s => s.name)).map(s => el("option", { value: s.name }, `${s.mine ? "yours" : s.owner_name || "unknown"} @${xy(s.x, s.y)}`)));
}

// The Check button carries the draft's warning count (DECISIONS G-20): "Check orders ⚠ 2".
function updateCheckBtn() {
  const b = $("checkBtn");
  const n = (S.advice || []).length;
  clear(b, "Check orders", n ? el("span", { class: "warn-count", id: "checkWarnCount", title: `${n} warning${n > 1 ? "s" : ""} about the draft; they don't stop you submitting` }, `⚠ ${n}`) : null);
  b.setAttribute("aria-label", n ? `Check orders (${n} warning${n > 1 ? "s" : ""})` : "Check orders");
}

// ---------------------------------------------------------------- rendering everything
function renderAll() {
  renderTop();
  map.refresh();
  renderInspector();
  renderTab();
  updateCounts();
}
on("draft", () => { map.refresh(); renderTop(); renderInspector(); if (["orders", "tech", "forces"].includes(activeTab)) renderTab(); updateCounts(); });
on("advice", () => { updateCheckBtn(); if (activeTab === "orders") renderTab(); });
on("chatUpdated", () => { if (activeTab === "chat") renderTab("chat"); else if (activeTab === "diplomacy") renderTab(); updateCounts(); });
on("refreshSummary", refreshSummary);
on("newTurn", () => reloadGame(true));

// Is this page's login still good?  (A password change or host reset elsewhere logs it out.)
function stillIn(summary) {
  const me = seatFor(S.gid);
  if (!me) return false;
  return me.seat === 0 ? summary.you_host_login : summary.you === me.seat;
}
function loggedOut() {
  const me = seatFor(S.gid);
  if (me) forgetSeat(S.gid, me.seat);
  toast(me && me.seat === 0 ? "Your host login has ended (the host password was changed). Log in again." : `This browser was logged out of the ${me && me.race ? me.race : "race"}: its password was changed or reset, it logged out everywhere, or the race was handed over. Log in again.`, "error", 10000);
  const gid = S.gid;
  S.gid = null; history.replaceState(null, "", location.pathname);
  showLobby().then(() => openGame(gid)).catch(() => {});
}

async function refreshSummary() {
  try { S.summary = await api(`/api/games/${S.gid}`, { gid: S.gid }); } catch { return; }
  if (!stillIn(S.summary)) { loggedOut(); return; }
  const me = S.summary.seats.find(s => s.seat === (S.currentView && S.currentView.seat.seat));
  if (me) S.submitted = me.submitted;
  renderTop();
  if (activeTab === "orders") renderTab();
}

// ---------------------------------------------------------------- entering a game
let entered = null;          // {gid, seat}: the race this page shows (one per page load)
async function enterGame(gid, seatNo) {
  if (seatNo !== undefined && seatNo !== null && !Number.isNaN(seatNo)) pinSeat(gid, seatNo);
  const seat = seatFor(gid);
  if (!seat) {
    try {
      const g = await api(`/api/games/${gid}`);
      await showLobby();
      openGame(g);
    } catch { toast("That game doesn't exist any more.", "error"); history.replaceState(null, "", location.pathname); showLobby(); }
    return;
  }
  // a page plays one race: another race (or game) loads the page afresh, so nothing is shared
  if (entered && (entered.gid !== gid || entered.seat !== seat.seat)) { location.assign(gameUrl(gid, seat.seat)); return; }
  let me;
  try { me = await api(`/api/games/${gid}`, { gid }); }
  catch { forgetSeat(gid); toast("That game doesn't exist any more.", "error"); history.replaceState(null, "", location.pathname); return showLobby(); }
  S.gid = gid;
  if (!stillIn(me)) { loggedOut(); return; }
  if (me.you_must_set_password) {
    const info = me.seats.find(s => s.seat === seat.seat);
    const ok = await openPassword("must", { race: info ? info.race : seat.race, reset: info && info.password, gid });
    if (!ok) { S.gid = null; history.replaceState(null, "", location.pathname); return showLobby(); }
  }
  // a game from before host passwords were required: its host sets one now (Dave 2026-11-15)
  if (me.you_must_set_host_password) {
    const ok = await openPassword("hostmust", { gid });
    if (!ok) { S.gid = null; history.replaceState(null, "", location.pathname); return showLobby(); }
    try { me = await api(`/api/games/${gid}`, { gid }); } catch { /* the reload below shows any problem */ }
  }
  if (seat.seat === 0) {
    try { S.hostRaces = (await api(`/api/games/${gid}/host/races`, { gid })).races; } catch (e) { toast(e.message, "error"); S.gid = null; return showLobby(); }
    const want = Number(new URLSearchParams(location.search).get("as"));
    const pick = S.hostRaces.find(r => r.id === want) || S.hostRaces.find(r => r.human && !r.open) || S.hostRaces[0];
    S.viewAs = pick ? pick.id : null;
  } else {
    S.viewAs = null; S.hostRaces = null;
    const info = me.seats.find(s => s.seat === seat.seat);
    if (info) setRaceName(gid, seat.seat, info.race);
  }
  entered = { gid, seat: seat.seat };
  history.replaceState(null, "", gameUrl(gid, seat.seat, S.viewAs));
  resetChat();
  S.selection = null;
  try {
    await reloadGame(false);
  } catch (e) {
    if (e.status === 401) { loggedOut(); return; }
    else if (e.status === 404) { forgetSeat(gid); toast("That game doesn't exist any more.", "error"); }
    else toast(e.message, "error");
    S.gid = null; history.replaceState(null, "", location.pathname);
    return showLobby();
  }
  $("lobby").hidden = true; $("game").hidden = false;
  $("skipLink").setAttribute("href", "#gameMain");
  map.resize();
  fitHome();
  map.setCursor(HOME, HOME, false);
  renderAll();
  fetchChat(false).catch(() => {});
}

// Start centred on home, zoomed to what the empire knows (but not beyond ~40 squares across).
function fitHome() {
  const v = S.view;
  let d = 6;
  for (const s of [...v.systems, ...v.known_systems]) { const k = Math.max(Math.abs(s.x - HOME), Math.abs(s.y - HOME)); if (k <= 20) d = Math.max(d, k); }
  map.centerOn(HOME, HOME, Math.min(map.W, map.H) / (2 * d + 6));
}

async function reloadGame(announce) {
  const gid = S.gid;
  const keepHistory = isHistory() ? S.view.game.turn : null;
  const [summary, view] = await Promise.all([api(`/api/games/${gid}`, { gid }), api(`/api/games/${gid}/view`, { gid })]);
  if (!stillIn(summary)) { loggedOut(); return; }
  S.summary = summary; S.currentView = view; S.view = view;
  if (view.game.board && view.game.board !== BOARD) { setBoard(view.game.board); if (map) map.resize(); }
  S.versionSeen = summary.version;
  await loadDraft();
  S.stats = await api(`/api/games/${gid}/stats`, { gid }).catch(() => null);
  // the first time this browser sees the game over, show the final standings (DECISIONS W-16)
  if (summary.finished && !localStorage.getItem(`mhgcFinalSeen.${gid}`)) {
    localStorage.setItem(`mhgcFinalSeen.${gid}`, "1");
    setTimeout(() => openFinal(gid), 300);
  }
  if (announce) {
    toast(`Turn ${view.current_turn} has run. Your results are in the Report tab.`, "good", 7000);
    if (keepHistory === null) showTab("report");
  }
  if (map && !$("game").hidden) renderAll();
}

async function showTurn(n) {
  const cur = S.currentView;
  if (!cur) return;
  n = Math.max(0, Math.min(cur.current_turn, n));
  if (n === cur.current_turn) S.view = cur;
  else {
    try { S.view = await api(`/api/games/${S.gid}/view?turn=${n}`, { gid: S.gid }); } catch (e) { toast(e.message, "error"); return; }
  }
  renderAll();
}

// ---------------------------------------------------------------- polling
let polling = false, lastTurn = null;
async function poll() {
  if (!S.gid || $("game").hidden || polling) return;
  polling = true;
  try {
    const v = await api(`/api/games/${S.gid}/version`);
    if (lastTurn === null) lastTurn = v.turn;
    if (v.turn !== (S.currentView && S.currentView.current_turn)) {
      const viewing = isHistory() ? S.view.game.turn : null;
      await reloadGame(viewing === null);
      if (viewing !== null) { toast(`Turn ${v.turn} has run. Use "Back to the current turn" to see it.`, "good", 7000); await showTurn(viewing); }
    } else if (v.version !== S.versionSeen) {
      S.versionSeen = v.version;
      await refreshSummary();
    }
    if (v.chat_last > chatState.last) await fetchChat(true);
  } catch (e) {
    if (e.status === 404) { toast("This game was dropped.", "error", 8000); forgetSeat(S.gid); S.gid = null; history.replaceState(null, "", location.pathname); showLobby(); }
    else if (e.status === 401) loggedOut();
    /* otherwise the server is restarting: try again next tick */
  } finally { polling = false; }
}
setInterval(() => { if (!document.hidden) poll(); }, 3000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

// ---------------------------------------------------------------- map wiring
function selectSquare(w, focus) {
  const q = map.idx.get(`${w.x},${w.y}`);
  let f = focus || null;
  if (!f && q) {
    if (q.fleets.length === 1 && !q.ships.length) f = { kind: "fleet", id: q.fleets[0].name };
    else if (!q.fleets.length && q.ships.length === 1) f = { kind: "ship", id: q.ships[0].number };
    else if (q.system && q.system.kind === "own") f = { kind: "system", id: q.system.id };
  }
  // keep a focused unit when clicking elsewhere, so "Send ... here" is offered
  const prev = S.selection && S.selection.focus;
  if (!f && prev && (prev.kind === "fleet" || prev.kind === "ship")) f = prev;
  S.selection = { x: w.x, y: w.y, focus: f };
  map.dirty = true;
  renderInspector();
}
on("select", w => selectSquare(w, w.focus));
on("deselect", () => { S.selection = null; map.dirty = true; renderInspector(); });
on("focus", f => { if (S.selection) { S.selection.focus = f; renderInspector(); } });
on("mapMove", w => moveFocusedTo(w));
on("goto", o => {
  const B = BOARD, near = (a, c) => c + ((((a - c) % B) + B + Math.floor(B / 2)) % B - Math.floor(B / 2));
  map.centerOn(near(o.x, map.cx), near(o.y, map.cy), Math.max(map.scale, 16));
  map.setCursor(o.x, o.y, false);
  selectSquare({ x: o.x, y: o.y }, o.kind ? { kind: o.kind, id: o.id } : null);
});
on("cursor", c => {
  const q = map.idx.get(`${c.x},${c.y}`);
  const lines = q ? map.squareSummary(q).map(([a, b]) => `${a}: ${b}`) : [];
  const cov = { now: "in your scans now", past: "scanned before, not now", never: "never scanned" }[map.coverageOf(c.x, c.y)];
  if (cov) lines.push(cov);
  $("cursorInfo").textContent = `${xy(c.x, c.y)}${lines.length ? " · " + lines.join(" · ") : ""}`;
});
on("pickmode", label => {
  const b = $("pickBanner");
  b.hidden = !label;
  if (label) clear(b, el("span", {}, label), el("span", { class: "dim" }, "Esc to cancel"), el("button", { type: "button", class: "small", onclick: () => map.endPick(null) }, "Cancel"));
});
on("chatWith", id => openThread(id));

// The host runs a game no human gives orders in (W-24): one turn at a time, the screen refreshed
// after each, stopping at the end of the game.
let running = false;
async function runTurns(n) {
  if (running) return;
  running = true;
  $("forceBtn").disabled = $("run5Btn").disabled = true;
  try {
    for (let i = 0; i < n; i++) {
      const r = await api(`/api/games/${S.gid}/force`, { method: "POST", gid: S.gid });
      await reloadGame(false);
      toast(n > 1 ? `Turn ${r.turn} has run (${i + 1} of ${n}).` : `Turn ${r.turn} has run.`, "good", 3000);
      if (r.finished) break;
    }
  } catch (e) { toast(e.message, "error"); }
  finally { running = false; $("forceBtn").disabled = $("run5Btn").disabled = false; }
}

// ---------------------------------------------------------------- boot
async function boot() {
  map = new GalaxyMap($("map"), $("minimap"), $("mapTip"));
  window.__mhgc = { S, map };          // read-only handle for browser tests and debugging
  setMap(map);
  initInspector(map);
  map.layerControls($("layerList"), $("legend"));
  buildTabs();
  initLobby(enterGame);
  initOrderDialog();
  initHelp();
  $("toLobby").addEventListener("click", () => { S.gid = null; history.replaceState(null, "", location.pathname); showLobby(); });
  $("helpBtn").addEventListener("click", () => openHelp());
  $("lobbyHelp").addEventListener("click", () => openHelp());
  $("checkBtn").addEventListener("click", checkOrders);
  $("submitBtn").addEventListener("click", submitTurn);
  initAccount();
  $("run5Btn").addEventListener("click", () => runTurns(5));
  $("forceBtn").addEventListener("click", async () => {
    if (S.summary && S.summary.host_runs) return runTurns(1);    // nobody waits: no confirmation
    const w = S.summary ? S.summary.waiting_for.filter(s => s !== S.view.seat.seat) : [];
    const msg = w.length ? `${w.map(seatName).join(", ")} ${w.length === 1 ? "hasn't" : "haven't"} submitted. Their empires give no orders this turn (they still produce, grow and pay upkeep).` : "Run the turn now.";
    if (!(await confirmBox("Force the turn?", msg, "Force turn", true))) return;
    try { await api(`/api/games/${S.gid}/force`, { method: "POST", gid: S.gid }); await reloadGame(true); }
    catch (e) { toast(e.message, "error"); }
  });
  $("turnPick").addEventListener("change", e => showTurn(Number(e.target.value)));
  $("turnPrev").addEventListener("click", () => showTurn(S.view.game.turn - 1));
  $("turnNext").addEventListener("click", () => showTurn(S.view.game.turn + 1));
  $("zoomIn").addEventListener("click", () => map.zoom(1.3));
  $("zoomOut").addEventListener("click", () => map.zoom(1 / 1.3));
  $("zoomHome").addEventListener("click", () => { map.centerOn(HOME, HOME); map.setCursor(HOME, HOME, false); });
  $("searchForm").addEventListener("submit", e => {
    e.preventDefault();
    const q = $("searchBox").value.trim().toLowerCase();
    if (!q) return;
    const all = knownSystems().filter(s => s.name);
    const hit = all.find(s => s.name.toLowerCase() === q) || all.find(s => s.name.toLowerCase().startsWith(q)) || all.find(s => s.name.toLowerCase().includes(q));
    if (!hit) { toast(`No known system called "${$("searchBox").value}".`, "error"); return; }
    $("searchBox").value = "";
    emit("goto", { x: hit.x, y: hit.y, ...(hit.mine ? { kind: "system", id: hit.id } : {}) });
    $("map").focus();
  });
  $("searchBox").addEventListener("change", () => { if (knownSystems().some(s => s.name === $("searchBox").value)) $("searchForm").requestSubmit(); });
  document.addEventListener("keydown", e => {
    if (e.target.closest("input, textarea, select, dialog")) return;
    if (e.key === "?") { e.preventDefault(); openHelp(); }
    else if (e.key === "/" && !$("game").hidden) { e.preventDefault(); $("searchBox").focus(); }
  });
  try {
    [S.catalogue, S.ref] = await Promise.all([api("/api/orders/catalogue"), api("/api/reference")]);
  } catch (e) { toast(`Can't reach the server: ${e.message}`, "error", 10000); }
  loadRulebook();
  const q = new URLSearchParams(location.search);
  const gid = q.get("game");
  if (gid) await enterGame(gid, q.get("seat") !== null ? Number(q.get("seat")) : undefined); else await showLobby();
}
boot();
