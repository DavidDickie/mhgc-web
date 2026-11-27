// Races, passwords and the host, in the game screen (DECISIONS W-21..W-24): the top-bar race
// switcher, the host's "View as" picker, the menu (change password, log out, leave, host
// controls, export), the set-a-password dialog and the host controls dialog.
// A page plays exactly one race (or the host login); switching loads the page afresh, so nothing
// of one race's view is ever kept while showing another.
"use strict";
import { S, api, el, clear, $, toast, confirmBox, seatFor, racesFor, forgetSeat, byName } from "./core.js";
import { exportGame } from "./final.js";
import { openGame } from "./lobby.js";

export const gameUrl = (gid, seat, as) => `/?game=${gid}${seat !== undefined && seat !== null ? `&seat=${seat}` : ""}${as !== undefined && as !== null ? `&as=${as}` : ""}`;
export const switchTo = (gid, seat, as) => location.assign(gameUrl(gid, seat, as));

export function initAccount() {
  // the app version, shown at the foot of the menu (so Dave can tell which build he played)
  fetch("/api/health").then(r => r.json()).then(h => { S.appVersion = h.version ? `MHGC v${h.version}${h.version_date ? ` (${h.version_date})` : ""}` : ""; renderVersion(); }).catch(() => {});
  const menu = $("raceMenu");
  document.addEventListener("click", e => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  menu.addEventListener("keydown", e => { if (e.key === "Escape") { menu.open = false; menu.querySelector("summary").focus(); } });
  $("raceSwitch").addEventListener("change", e => {
    const v = e.target.value;
    if (v === "+") { e.target.value = String(seatFor(S.gid).seat); openGame(S.gid); return; }
    switchTo(S.gid, Number(v));
  });
  $("viewAsPick").addEventListener("change", e => switchTo(S.gid, 0, Number(e.target.value)));
  $("pwCancel").addEventListener("click", () => { $("pwDlg").close(); });
  $("pwDlg").addEventListener("cancel", e => { if (["must", "hostmust"].includes($("pwDlg").dataset.mode)) e.preventDefault(); });
  $("resetCancel").addEventListener("click", () => { $("resetForm").hidden = true; });
  $("resetForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = $("resetForm"), seat = Number(f.dataset.seat);
    $("resetErr").textContent = "";
    try {
      await api(`/api/games/${S.gid}/seats/${seat}/reset-password`, { gid: S.gid, body: { password: f.elements.password.value } });
      toast(`Password reset. Tell the player the temporary password; they choose a new one at their next login.`, "good", 8000);
      f.hidden = true;
      await openHostControls();
    } catch (e) { $("resetErr").textContent = e.message; }
  });
}

// ---------------------------------------------------------------- the set-a-password dialog
// mode "must": the race must set a password before it can play (a seat from before passwords,
// or after a host reset); "change": change your own; "host": set or change the host password;
// "hostmust": the host of a game from before host passwords were required must set one now.
export function openPassword(mode, opts = {}) {
  return new Promise(resolve => {
    const dlg = $("pwDlg"), f = $("pwForm");
    f.reset();
    dlg.dataset.mode = mode;
    const race = opts.race || "your race";
    const hostMode = mode === "host" || mode === "hostmust";
    $("pwH").textContent = mode === "hostmust" ? "Set a host password" : mode === "host" ? (opts.hasHostPassword ? "Change the host password" : "Set a host password") : mode === "must" ? `Set a password for the ${race}` : `Change the password of the ${race}`;
    $("pwHint").textContent = mode === "must"
      ? (opts.reset ? `The host reset this race's password. Choose a new one to play on.` : `Races have passwords now. Choose one for the ${race}: you will need it to log in from another browser or device. This browser stays logged in.`)
      : mode === "hostmust" ? "Every game has a host password now. Choose one for this game: it logs you in as the host from any browser (host controls and View as). It may be the same as your race password, and you can use the same host password for all your games."
      : mode === "host" ? "The host password logs you in as the host from any browser (host controls and View as). You can use the same host password for all your games. Other host logins are logged out when it changes."
      : "Every other browser logged in to this race is logged out; this one stays in.";
    const needCur = mode === "change" || (mode === "host" && opts.hasHostPassword);
    $("pwCurLabel").hidden = !needCur;
    f.elements.current.required = needCur;
    $("pwCancel").textContent = mode === "must" || mode === "hostmust" ? "Back to the game list" : "Cancel";
    $("pwErr").textContent = "";
    f.onsubmit = async ev => {
      ev.preventDefault();
      $("pwErr").textContent = "";
      if (f.elements.new.value.length < 4) { $("pwErr").textContent = "A password needs at least 4 characters."; return; }
      if (f.elements.new.value !== f.elements.new2.value) { $("pwErr").textContent = "The two passwords are not the same."; return; }
      const body = { new: f.elements.new.value, ...(needCur ? { current: f.elements.current.value } : {}) };
      try {
        await api(`/api/games/${S.gid || opts.gid}/${hostMode ? "host/password" : "password"}`, { gid: S.gid || opts.gid, body });
        dlg.close();
        toast(hostMode ? "Host password saved." : "Password saved.", "good");
        resolve(true);
      } catch (e) { $("pwErr").textContent = e.message; }
    };
    dlg.onclose = () => resolve(false);
    dlg.showModal();
    (needCur ? f.elements.current : f.elements.new).focus();
  });
}

// ---------------------------------------------------------------- top bar: switcher and menu
export function renderAccount() {
  const v = S.view, g = S.summary, me = seatFor(S.gid);
  if (!v || !g || !me) return;
  const host = me.seat === 0;
  const races = racesFor(S.gid);
  const sw = $("raceSwitch");
  clear(sw, [...races.filter(r => r.seat === 0), ...byName(races.filter(r => r.seat !== 0), r => r.race || `seat ${r.seat}`)].map(r => el("option", { value: r.seat, selected: r.seat === me.seat }, r.seat === 0 ? "Host (no race)" : `The ${r.race || `seat ${r.seat}`}`)),
    el("option", { value: "+" }, "Log in to another race…"));
  sw.hidden = races.length < 2;
  const va = $("viewAsPick");
  va.hidden = !host || !S.hostRaces;
  if (host && S.hostRaces) clear(va, byName(S.hostRaces, r => r.race).map(r => el("option", { value: r.id, selected: r.id === S.viewAs }, `View as the ${r.race}${r.human ? (r.player ? ` (${r.player})` : " (open seat)") : " (computer)"}`)));
  const b = $("viewAsBanner");
  b.hidden = !host;
  if (host) {
    const r = (S.hostRaces || []).find(x => x.id === S.viewAs);
    clear(b, el("strong", {}, `Viewing as the ${v.empire.name} (host)`), el("span", {}, `${r && !r.human ? "A computer empire. " : ""}Read-only: you can't give orders, submit or chat for them.`));
  }
  // the menu
  const items = [];
  const item = (label, fn, attrs = {}) => el("button", { type: "button", role: "menuitem", ...attrs, onclick: () => { $("raceMenu").open = false; fn(); } }, label);
  if (!host) {
    items.push(el("div", { class: "menu-head" }, `The ${v.empire.name}`));
    items.push(item("Change password…", () => openPassword("change", { race: v.empire.name })));
    items.push(item("Log out of this race", logout));
    items.push(item("Log out everywhere", () => logout(true), { title: "Every browser logged in to this race is logged out" }));
    items.push(item("Leave this seat…", leave));
  }
  items.push(el("div", { class: "menu-head" }, "Races"));
  items.push(item("Log in to another race or take a seat…", () => openGame(S.gid)));
  if (host || v.seat.host) {
    items.push(el("div", { class: "menu-head" }, "Host"));
    items.push(item("Host controls…", openHostControls));
    items.push(item(g.host_password ? "Change the host password…" : "Set a host password…", () => openPassword("host", { hasHostPassword: g.host_password })));
    if (!host && g.host_password) items.push(item("Log in as host (View as)…", () => openGame(S.gid, "host")));
    items.push(item("Export for analysis", () => exportGame(S.gid)));
    if (host) items.push(item("Log out of the host login", logout));
  }
  clear($("raceMenuItems"), items);
  renderVersion();
}

function renderVersion() {
  const box = $("raceMenuItems");
  if (!box || !S.appVersion) return;
  box.querySelector(".menu-version")?.remove();
  box.append(el("div", { class: "menu-version", title: "The version of the game software" }, S.appVersion));
}

async function logout(everywhere = false) {
  const me = seatFor(S.gid);
  if (!me) return;
  try {
    if (me.seat === 0) await api(`/api/games/${S.gid}/host/logout`, { method: "POST", gid: S.gid });
    else await api(`/api/games/${S.gid}/logout`, { gid: S.gid, body: { everywhere } });
  } catch (e) { if (e.status !== 401) { toast(e.message, "error"); return; } }
  forgetSeat(S.gid, me.seat);
  toast(me.seat === 0 ? "Logged out of the host login." : `Logged out of the ${me.race || "race"}${everywhere ? " in every browser" : ""}.`, "good");
  location.assign("/");
}

async function leave() {
  const me = seatFor(S.gid);
  if (!(await confirmBox("Leave this seat?", `Seat ${me.seat} (the ${me.race}) becomes open for someone else to take, with the empire as it stands. Its password is cleared and every browser logged in to it is logged out.`, "Leave seat", true))) return;
  try { await api(`/api/games/${S.gid}/leave`, { method: "POST", gid: S.gid }); } catch (e) { toast(e.message, "error"); return; }
  forgetSeat(S.gid, me.seat);
  toast("You left the seat.");
  location.assign("/");
}

// ---------------------------------------------------------------- host controls
export async function openHostControls() {
  const dlg = $("hostDlg");
  let races;
  try { races = (await api(`/api/games/${S.gid}/host/races`, { gid: S.gid })).races; } catch (e) { toast(e.message, "error"); return; }
  const g = S.summary;
  const me = seatFor(S.gid);
  const mySeat = me && me.seat > 0 ? me.seat : null;
  const rows = races.map(r => {
    const mine = r.id === mySeat || r.id === g.host_seat;
    const acts = [];
    if (r.human && !r.open && !mine) acts.push(el("button", { type: "button", class: "small ghost", onclick: () => askReset(r) }, "Reset password"));
    if (r.human && r.kind === "human" && !mine && !g.finished) acts.push(el("button", { type: "button", class: "small ghost danger", onclick: () => toComputer(r) }, "Hand to the computer"));
    if (!r.human && r.kind === "npr" && !g.finished) acts.push(el("button", { type: "button", class: "small ghost", onclick: () => toHuman(r) }, "Open for a human"));
    if (me && me.seat === 0) acts.push(el("button", { type: "button", class: "small ghost", onclick: () => switchTo(S.gid, 0, r.id) }, "View as"));
    return el("div", { class: "host-race" }, el("span", { class: "who" }, el("b", {}, r.race), ` · ${r.kind === "dead" ? "out of the game" : r.human ? (r.open ? "open human seat" : `${r.player}${mine ? " (you)" : ""}`) : "computer"}`), acts);
  });
  clear($("hostRaces"), rows);
  $("resetForm").hidden = true;
  if (!dlg.open) dlg.showModal();
}

function askReset(r) {
  const f = $("resetForm");
  f.dataset.seat = r.id;
  f.reset();
  $("resetH").textContent = `Reset the password of the ${r.race}`;
  $("resetErr").textContent = "";
  f.hidden = false;
  f.elements.password.focus();
}

async function toComputer(r) {
  if (!(await confirmBox(`Hand the ${r.race} to the computer?`, `The ${r.race}${r.player ? ` (${r.player})` : ""} become a computer empire, played by the bot from its own view; their victory points and ranking carry on. Their password, logins, draft and submission are dropped, and the turn stops waiting for them. Everyone sees a notice.`, `Hand ${r.race} to the computer`, true))) return;
  try {
    const res = await api(`/api/games/${S.gid}/seats/${r.id}/computer`, { method: "POST", gid: S.gid });
    toast(`The ${r.race} are a computer empire now.${res.turn_ran ? ` Turn ${res.turn} has run.` : ""}`, "good", 7000);
  } catch (e) { toast(e.message, "error"); return; }
  await openHostControls();
}

async function toHuman(r) {
  if (!(await confirmBox(`Open the ${r.race} for a human player?`, `The ${r.race} become an open human seat, keeping their name, empire and victory points. A new player takes the seat with a password. Until someone does, the open seat holds up the automatic turn: you may want to force turns meanwhile. Everyone sees a notice.`, `Open ${r.race} for a human player`))) return;
  try { await api(`/api/games/${S.gid}/seats/${r.id}/human`, { method: "POST", gid: S.gid }); toast(`Seat ${r.id} (the ${r.race}) is open to join.`, "good", 7000); }
  catch (e) { toast(e.message, "error"); return; }
  await openHostControls();
}
