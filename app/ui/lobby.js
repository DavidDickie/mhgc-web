// The lobby: pick a game (or create one), then log in to a race, take an open seat, or log in as
// the host (DECISIONS W-21, W-23).  Also leave, drop, final standings and export.
"use strict";
import { api, el, clear, $, toast, confirmBox, racesFor, keepSeat, forgetSeat, allSeats, setRaceName, S, byName } from "./core.js";
import { openFinal, exportButton } from "./final.js";

let onEnter = () => {};
export function initLobby(enter) {
  onEnter = enter;
  $("refreshLobby").addEventListener("click", showLobby);
  $("newGameBtn").addEventListener("click", openNewGame);
  for (const b of document.querySelectorAll("dialog [data-close]")) b.addEventListener("click", () => b.closest("dialog").close());
  const f = $("newGameForm");
  buildSizePicker();
  f.elements.humans.addEventListener("input", sizeHint);
  f.addEventListener("change", e => { if (e.target.name === "size") sizeHint(); if (e.target.name === "mode" || e.target.name === "host_same") modeHint(); });
  f.addEventListener("submit", async ev => {
    ev.preventDefault();
    $("newGameErr").textContent = "";
    const hostOnly = f.elements.mode.value === "host";
    const body = { name: f.elements.name.value.trim(), player: f.elements.player.value.trim(), humans: Number(f.elements.humans.value),
      size: chosenSize(), chatter: f.elements.chatter.value, host_only: hostOnly };
    const pw = f.elements.password.value, hpw = f.elements.host_password.value;
    const same = !hostOnly && f.elements.host_same.checked;
    if (!hostOnly) {
      if (pw.length < 4) { $("newGameErr").textContent = "Choose a password of at least 4 characters for your race."; return; }
      if (pw !== f.elements.password2.value) { $("newGameErr").textContent = "The two passwords are not the same."; return; }
      body.password = pw;
      if (f.elements.race.value.trim()) body.race = f.elements.race.value.trim();
    }
    // the host password is required in both modes (Dave 2026-11-15); it may be the race password
    if (same) body.host_password = pw;
    else {
      if (hpw.length < 4) { $("newGameErr").textContent = "Choose a host password of at least 4 characters."; return; }
      if (hpw !== f.elements.host_password2.value) { $("newGameErr").textContent = "The two host passwords are not the same."; return; }
      body.host_password = hpw;
    }
    try {
      const r = await api("/api/games", { body });
      if (hostOnly) keepSeat(r.id, 0, r.token, body.player, "Host");
      else keepSeat(r.id, r.seat, r.token, body.player, r.game.seats[0].race);
      localStorage.setItem("mhgcName", body.player);
      // remember a host password typed here (never the race password) for the next New game,
      // in this browser's localStorage only
      if (!same) { if (f.elements.host_remember.checked) localStorage.setItem(HOST_PW_KEY, hpw); else localStorage.removeItem(HOST_PW_KEY); }
      $("newGameDlg").close();
      onEnter(r.id);
    } catch (e) { $("newGameErr").textContent = e.message; }
  });
  $("joinForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const fj = $("joinForm");
    const gid = $("gameDlg").dataset.gid;
    const seat = Number((fj.querySelector("input[name=seat]:checked") || {}).value);
    const player = fj.elements.player.value.trim();
    $("joinErr").textContent = "";
    if (!seat) { $("joinErr").textContent = "Pick a seat."; return; }
    if (fj.elements.password.value.length < 4) { $("joinErr").textContent = "Choose a password of at least 4 characters."; return; }
    if (fj.elements.password.value !== fj.elements.password2.value) { $("joinErr").textContent = "The two passwords are not the same."; return; }
    const body = { seat, player, password: fj.elements.password.value };
    if (fj.elements.race.value.trim() && !$("joinRaceLabel").hidden) body.race = fj.elements.race.value.trim();
    try {
      const r = await api(`/api/games/${gid}/join`, { body });
      const race = (r.game.seats.find(x => x.seat === r.seat) || {}).race;
      keepSeat(gid, r.seat, r.token, player, race);
      localStorage.setItem("mhgcName", player);
      $("gameDlg").close();
      toast(`You play the ${race} (seat ${r.seat}). Log in with your password from any other browser.`, "good", 7000);
      onEnter(gid, r.seat);
    } catch (e) { $("joinErr").textContent = e.status === 409 && /seat/i.test(e.message) ? "Someone just took that seat. Pick another." : e.message; }
  });
  $("loginForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const fl = $("loginForm");
    const gid = $("gameDlg").dataset.gid;
    const seat = Number(fl.elements.seat.value);
    $("loginErr").textContent = "";
    if (!seat) { $("loginErr").textContent = "Pick your race."; return; }
    try {
      const r = await api(`/api/games/${gid}/login`, { body: { seat, password: fl.elements.password.value } });
      keepSeat(gid, r.seat, r.token, r.player, r.race);
      fl.elements.password.value = "";
      $("gameDlg").close();
      onEnter(gid, r.seat);
    } catch (e) { $("loginErr").textContent = e.message; fl.elements.password.select(); }
  });
  $("hostLoginForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const fh = $("hostLoginForm");
    const gid = $("gameDlg").dataset.gid;
    $("hostLoginErr").textContent = "";
    try {
      const r = await api(`/api/games/${gid}/host/login`, { body: { password: fh.elements.password.value } });
      keepSeat(gid, 0, r.token, localStorage.getItem("mhgcName") || "", "Host");
      fh.elements.password.value = "";
      $("gameDlg").close();
      onEnter(gid, 0);
    } catch (e) { $("hostLoginErr").textContent = e.message; fh.elements.password.select(); }
  });
}

// Game sizes (DECISIONS W-13, W-26, G-30): bins per side and the empty bins ("bx,by", as
// constants.GAME_SIZES; no home empire; open territory).
export const GAME_SIZES = [
  { size: 4, side: 2, empty: [], note: "four quadrants, a close-quarters galaxy" },
  { size: 8, side: 3, empty: ["1,1"], note: "the centre square is open territory" },
  { size: 9, side: 3, empty: [], note: "nine squares, nine empires" },
  { size: 12, side: 4, empty: ["1,1", "1,2", "2,1", "2,2"], note: "the four centre squares are open territory" },
  { size: 16, side: 4, empty: [], note: "the classic map" },
  { size: 20, side: 5, empty: ["0,0", "2,1", "4,2", "1,3", "3,4"], note: "five open squares a knight's move apart: every empire has two open squares beside it" },
  { size: 25, side: 5, empty: [], note: "the largest galaxy, twenty-five empires" },
];
export function binDiagram(side, empty, cls = "bins") {
  const box = el("span", { class: cls, "aria-hidden": "true", style: { gridTemplateColumns: `repeat(${side}, 1fr)` } });
  for (let by = side - 1; by >= 0; by--) for (let bx = 0; bx < side; bx++) {
    box.append(el("span", { class: empty.includes(`${bx},${by}`) ? "bin empty" : "bin" }));
  }
  return box;
}
function buildSizePicker() {
  clear($("sizeOpts"), GAME_SIZES.map(z => el("label", { class: "size-opt", title: `${z.size} empires (${z.side}×${z.side}) on a ${z.side * 25}×${z.side * 25} board: ${z.note}` },
    el("input", { type: "radio", name: "size", value: z.size, checked: z.size === 8 }),
    binDiagram(z.side, z.empty),
    el("span", { class: "size-txt" }, el("b", {}, `${z.size}`), ` empires`, el("br"), el("span", { class: "dim" }, `${z.side}×${z.side}, ${z.side * 25}×${z.side * 25}`), z.size === 8 ? el("span", { class: "dim" }, el("br"), "default") : null))));
}
function chosenSize() {
  const r = $("newGameForm").querySelector("input[name=size]:checked");
  return r ? Number(r.value) : 8;
}
function sizeHint() {
  const f = $("newGameForm"), size = chosenSize(), z = GAME_SIZES.find(q => q.size === size);
  f.elements.humans.max = size;
  if (Number(f.elements.humans.value) > size) f.elements.humans.value = size;
  const host = f.elements.mode && f.elements.mode.value === "host";
  const n = Math.min(size, Number(f.elements.humans.value) || (host ? 0 : 1));
  $("newGameHint").textContent = `${size} empires (${z.side}×${z.side}) on a ${z.side * 25}×${z.side * 25} board (${z.note}). The other ${Math.max(0, size - n)} are computer empires. The first race to ${(S.ref && S.ref.victory_points) || 100} victory points wins.`;
}

const HOST_PW_KEY = "mhgcHostPw";
function modeHint() {
  const f = $("newGameForm"), host = f.elements.mode.value === "host";
  $("newGamePlay").hidden = host;
  f.elements.humans.min = host ? 0 : 1;
  $("hostSameLabel").hidden = host;
  $("hostPwFields").hidden = !host && f.elements.host_same.checked;
  sizeHint();
}

function openNewGame() {
  const f = $("newGameForm");
  f.reset();
  const def = f.querySelector("input[name=size][value='8']");
  if (def) def.checked = true;
  // prefill the host password this browser remembers (the same one for every game is fine)
  const remembered = localStorage.getItem(HOST_PW_KEY) || "";
  f.elements.host_same.checked = !remembered;
  f.elements.host_password.value = f.elements.host_password2.value = remembered;
  modeHint();
  f.elements.player.value = localStorage.getItem("mhgcName") || "";
  $("newGameErr").textContent = "";
  $("newGameDlg").showModal();
  (f.elements.player.value ? f.elements.name : f.elements.player).focus();
}

// The game dialog: play an existing race (password), take an open seat, or log in as the host.
export async function openGame(gOrId, focus) {
  let g = gOrId;
  if (typeof g === "string") { try { g = await api(`/api/games/${g}`); } catch (e) { toast(e.message, "error"); return; } }
  const dlg = $("gameDlg");
  dlg.dataset.gid = g.id;
  $("gameDlgH").textContent = g.name;
  $("gameDlgInfo").textContent = `${g.finished ? `Finished: the ${g.winner} won` : `Turn ${g.turn}`} · ${g.size} empires: ${g.humans} human seat${g.humans === 1 ? "" : "s"}, ${g.computers} computer${g.vp_to_win ? ` · first to ${g.vp_to_win} VP wins` : ""}${g.host_only ? " · hosted without a race" : ""}`;
  const held = new Set(racesFor(g.id).map(r => r.seat));
  // play an existing race: the claimed human seats
  const claimed = g.seats.filter(s => !s.open && !s.computer);
  const lf = $("loginForm");
  lf.hidden = !claimed.length;
  clear($("loginRace"), byName(claimed, s => s.race).map(s => el("option", { value: s.seat, disabled: !s.password, selected: false },
    `${s.race} (${s.player})${s.password ? "" : " - no password yet"}${held.has(s.seat) ? " - logged in here" : ""}`)));
  const first = claimed.find(s => s.password && !held.has(s.seat)) || claimed.find(s => s.password);
  if (first) $("loginRace").value = String(first.seat);
  lf.elements.password.value = "";
  $("loginErr").textContent = claimed.length && !claimed.some(s => s.password) ? "None of these races has a password yet. Its player sets one on the next visit, or the host resets it." : "";
  // take an open seat
  const open = g.seats.filter(s => s.open);
  const fj = $("joinForm");
  fj.hidden = !open.length || g.finished;
  clear($("joinSeats"), open.map((s, i) => el("label", {}, el("input", { type: "radio", name: "seat", value: s.seat, checked: i === 0 }), `Seat ${s.seat}${g.turn > 0 ? ` (${s.race})` : ""}`)));
  $("joinRaceLabel").hidden = g.turn > 0;
  $("joinHint").textContent = g.turn > 0 ? `The game is at turn ${g.turn}: you take over that seat's race as it stands, with its name.` : "Pick a race name now; it can't be changed after the first turn (except once with a rename order). You may hold more than one race.";
  fj.elements.player.value = localStorage.getItem("mhgcName") || "";
  fj.elements.race.value = "";
  fj.elements.password.value = ""; fj.elements.password2.value = "";
  $("joinErr").textContent = "";
  // host login
  $("hostLoginBox").hidden = !g.host_password;
  $("hostLoginBox").open = focus === "host" || (!claimed.length && !open.length);
  $("hostLoginForm").elements.password.value = "";
  $("hostLoginErr").textContent = "";
  if (!dlg.open) dlg.showModal();
  if (focus === "host" && g.host_password) $("hostLoginForm").elements.password.focus();
  else if (focus === "join" && open.length) fj.elements.player.focus();
  else if (first) lf.elements.password.focus();
  else if (open.length) fj.elements.player.focus();
}
// kept for older callers
export const openJoin = g => openGame(g, "join");

function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export async function showLobby() {
  $("lobby").hidden = false; $("game").hidden = true;
  $("skipLink").setAttribute("href", "#lobbyMain");
  document.title = "Mega Hyper Galactic Conquest";
  const list = $("gameList");
  let rows;
  try { rows = await api("/api/games"); } catch (e) { clear(list, el("li", { class: "err" }, e.message)); return; }
  // forget logins in games that no longer exist
  const ids = new Set(rows.map(r => r.id));
  for (const gid of Object.keys(allSeats())) if (!ids.has(gid)) forgetSeat(gid);
  clear(list);
  if (!rows.length) list.append(el("li", { class: "hint" }, "No games yet. Start one with New game, then send your friends this page's address."));
  rows.sort((a, b) => (racesFor(b.id).length > 0) - (racesFor(a.id).length > 0));
  for (const g of rows) {
    // the server's summary is authoritative: a race shown as open or computer is no longer held
    const held = racesFor(g.id).filter(r => r.seat === 0 ? g.host_password || g.host_only : g.seats.some(s => s.seat === r.seat && !s.open && !s.computer));
    for (const r of held) { const s = g.seats.find(x => x.seat === r.seat); if (s) setRaceName(g.id, r.seat, s.race); }
    const heldSeats = new Set(held.map(r => r.seat));
    const status = g.finished ? `finished: the ${g.winner} won` : `turn ${g.turn}`;
    const wait = g.finished ? "" : g.host_runs ? `waiting for the host to run turn ${g.turn + 1}` : g.waiting_for.length ? `waiting for ${g.waiting_for.map(n => { const s = g.seats.find(x => x.seat === n); return s.open ? `seat ${n} (open)` : `${s.player} (${s.race})`; }).join(", ")}` : "";
    const seats = el("div", { class: "seat-list", "aria-label": "Seats" }, g.seats.map(s => el("span", {
      class: `seat${s.open ? " open" : ""}${!s.open && !s.computer && !g.finished ? (s.submitted ? " done" : s.needs_orders ? " waiting" : "") : ""}${heldSeats.has(s.seat) ? " you" : ""}`,
      title: s.open ? "open seat" : s.computer ? "handed to the computer" : s.submitted ? "submitted" : s.needs_orders ? "not submitted yet" : "out of the game" },
      `${s.seat}. ${s.open ? `open${g.turn > 0 ? ` · ${s.race}` : ""}` : s.computer ? `computer · ${s.race}` : `${s.player} · ${s.race}`}${s.host ? " ★" : ""}${s.submitted ? " ✓" : ""}`)),
      g.host_only ? el("span", { class: "seat host-chip", title: "The host plays no race" }, "★ host only") : null);
    const actions = el("div", { class: "game-actions" });
    for (const r of held) actions.append(el("button", { type: "button", class: "primary", onclick: () => onEnter(g.id, r.seat) }, r.seat === 0 ? "Host view" : held.length > 1 ? `Play the ${r.race || "seat " + r.seat}` : "Play"));
    actions.append(el("button", { type: "button", class: held.length ? "ghost" : "primary", onclick: () => openGame(g), title: "Log in to a race with its password, take an open seat, or log in as the host" }, held.length ? "Log in…" : g.open_seats.length && !g.finished ? "Open / join" : "Open"));
    if (g.finished) actions.append(el("button", { type: "button", class: "ghost", onclick: () => openFinal(g.id) }, "Final standings"));
    if (g.finished && held.some(r => r.seat > 0)) actions.append(exportButton(g.id, "Export"));
    const one = held.length === 1 && held[0].seat > 0 ? held[0] : null;
    if (one) actions.append(el("button", { type: "button", class: "ghost", onclick: async () => {
      if (!(await confirmBox("Leave this seat?", `Seat ${one.seat} (the ${one.race}) becomes open for someone else to take, with the empire as it stands. Its password is cleared.`, "Leave seat", true))) return;
      try { await api(`/api/games/${g.id}/leave`, { method: "POST", gid: g.id }); forgetSeat(g.id, one.seat); toast("You left the seat."); } catch (e) { toast(e.message, "error"); }
      showLobby();
    } }, "Leave"));
    const anySeated = g.seats.some(s => !s.open && !s.computer);
    if (held.length || !anySeated) actions.append(el("button", { type: "button", class: "ghost danger", onclick: async () => {
      if (!(await confirmBox(`Drop "${g.name}"?`, "This deletes the game for good, for everyone in it.", "Drop game", true))) return;
      try { await api(`/api/games/${g.id}`, { method: "DELETE", gid: g.id }); forgetSeat(g.id); toast("Game dropped."); } catch (e) { toast(e.message, "error"); }
      showLobby();
    } }, "Drop"));
    list.append(el("li", { class: `game-row${held.length ? " mine" : ""}` },
      el("div", {}, el("h3", {}, el("button", { type: "button", class: "link game-title", onclick: () => openGame(g) }, g.name)),
        el("div", { class: "game-meta" }, binDiagram(g.bins || 4, (g.empty_bins || []).map(b => b.join(",")), "bins mini"),
          `${status} · ${g.size || g.humans + g.computers} empires (${g.board || 100}×${g.board || 100}): ${g.humans} human${g.humans === 1 ? "" : "s"}, ${g.computers} computer · updated ${ago(g.updated)}`),
        wait ? el("div", { class: "game-meta warnc" }, wait) : null),
      actions, seats));
  }
}
