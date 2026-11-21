// In-game chat: a game-wide channel plus private threads with contacted human races (W-07).
"use strict";
import { S, api, el, clear, emit, toast, techName, isHistory } from "./core.js";

const C = { msgs: [], last: 0, recipients: [], thread: "all", unread: {}, box: null, loaded: false };
export const chatState = C;

const threadOf = m => (m.to === null || m.to === undefined ? "all" : String(m.from === S.view?.empire.id ? m.to : m.from));

export function resetChat() { C.msgs = []; C.last = 0; C.recipients = []; C.thread = "all"; C.unread = {}; C.loaded = false; }

export async function fetchChat(markUnread = true) {
  if (!S.gid) return;
  const r = await api(`/api/games/${S.gid}/chat?since=${C.last}`, { gid: S.gid });
  C.recipients = r.recipients;
  const mine = S.view ? S.view.empire.id : null;
  for (const m of r.messages) {
    if (C.msgs.some(x => x.id === m.id)) continue;
    C.msgs.push(m);
    const t = threadOf(m);
    if (markUnread && C.loaded && m.from !== mine && !(C.visible && C.thread === t)) C.unread[t] = (C.unread[t] || 0) + 1;
  }
  C.last = Math.max(C.last, r.last);
  C.loaded = true;
  emit("chatUpdated");
}
export const unreadTotal = () => Object.values(C.unread).reduce((a, b) => a + b, 0);

export function openThread(id) { C.thread = String(id); C.unread[C.thread] = 0; emit("showTab", "chat"); emit("chatUpdated"); }

export function renderChat(box) {
  C.box = box;
  const v = S.view;
  const prevInput = box.querySelector("#chatText");
  const draftText = prevInput ? prevInput.value : "";
  const hadFocus = prevInput && document.activeElement === prevInput;
  clear(box);
  C.unread[C.thread] = 0;
  const threads = [["all", "Everyone"], ...C.recipients.map(r => [String(r.empire), `${r.race}${r.player ? ` (${r.player})` : " (open seat)"}`])];
  // keep threads for past private messages even if contact was lost
  for (const m of C.msgs) { const t = threadOf(m); if (t !== "all" && !threads.some(x => x[0] === t)) threads.push([t, m.from === v.empire.id ? m.to_name : m.from_name]); }
  const panel = el("div", { class: "chat-panel" });
  panel.append(el("h2", {}, "Chat"));
  // the computer empires' boasts (DECISIONS W-14): the host sets how chatty they are
  const level = (S.summary && S.summary.chatter) || "normal";
  if (v.seat && v.seat.host) {
    const sel = el("select", { "aria-label": "Computer chatter", onchange: async e => {
      try { S.summary = await api(`/api/games/${S.gid}/settings`, { gid: S.gid, body: { chatter: e.target.value } }); toast(`Computer chatter is now ${e.target.value}.`, "good"); await fetchChat(false); }
      catch (er) { toast(er.message, "error"); }
    } }, [["normal", "normal"], ["quiet", "quiet"], ["off", "off"]].map(([val, label]) => el("option", { value: val, selected: val === level }, label)));
    panel.append(el("label", { class: "chatter-set" }, "Computer chatter ", sel, el("span", { class: "dim" }, " (host; from the next turn)")));
  } else panel.append(el("p", { class: "hint chatter-set" }, `Computer chatter: ${level}`));
  panel.append(el("div", { class: "chat-threads", role: "tablist", "aria-label": "Conversations" }, threads.map(([id, label]) =>
    el("button", { type: "button", role: "tab", "aria-selected": C.thread === id ? "true" : "false", class: `chip-btn ${C.thread === id ? "on" : "ghost"}`, onclick: () => { C.thread = id; renderChat(box); } },
      label, C.unread[id] ? el("span", { class: "badge warn" }, String(C.unread[id])) : null))));
  if (C.thread === "all" && !C.recipients.length) panel.append(el("p", { class: "hint" }, "Private chat opens up with each human race once you have made contact."));
  const log = el("ul", { class: "chat-log", "aria-live": "polite", "aria-label": "Messages" });
  const list = C.msgs.filter(m => threadOf(m) === C.thread);
  for (const m of list) {
    const time = new Date(m.time * 1000);
    const when = `T${m.turn} ${time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    if (m.system) { log.append(el("li", { class: "sys" }, el("span", { class: "body" }, m.text), el("span", { class: "when" }, when))); continue; }
    log.append(el("li", { class: `${m.to !== null && m.to !== undefined ? "priv " : ""}${m.from === v.empire.id ? "me" : ""}${m.bot ? "bot" : ""}` },
      el("span", { class: "who" }, m.from === v.empire.id ? "You" : `${m.from_name}${m.player ? ` (${m.player})` : ""}`),
      m.bot ? el("span", { class: "badge bot-badge", title: "A computer empire" }, "computer") : null,
      el("span", { class: "when" }, when), el("div", { class: "body" }, m.text), m.offer ? offerButtons(m, v) : null));
  }
  if (!list.length) log.append(el("li", { class: "sys" }, "No messages yet."));
  panel.append(log);
  if (v.seat && v.seat.view_as) {        // the host viewing as a race: read-only (W-23)
    panel.append(el("p", { class: "hint" }, `You are viewing as the ${v.empire.name}: this is their chat, read-only. The host can't write as them.`));
    box.append(panel);
    log.scrollTop = log.scrollHeight;
    return;
  }
  const ta = el("textarea", { id: "chatText", maxlength: 2000, placeholder: C.thread === "all" ? "Message everyone…" : "Private message…", "aria-label": "Message" }, draftText);
  const form = el("form", { class: "chat-form", onsubmit: async e => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) return;
    try {
      await api(`/api/games/${S.gid}/chat`, { gid: S.gid, body: { text, ...(C.thread === "all" ? {} : { to: Number(C.thread) }) } });
      ta.value = "";
      await fetchChat(false);
      const t = box.querySelector("#chatText"); if (t) t.focus();
    } catch (er) { toast(er.message, "error"); }
  } }, ta, el("button", { type: "submit", class: "primary" }, "Send"));
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  panel.append(form, el("p", { class: "hint" }, "Enter sends, Shift+Enter for a new line. Computer empires don't read chat (use a MESSAGE order for them), but they may offer you technology trades here."));
  box.append(panel);
  log.scrollTop = log.scrollHeight;
  if (hadFocus) ta.focus();
}

// A computer empire's trade offer (DECISIONS A-08): one Accept per alternative, only for the race
// it was made to, on the current turn and not when the host views as that race.  It expires once
// the turn it names has run, or when a newer offer from the same empire replaces it.
function offerState(m, v) {
  const newer = C.msgs.some(x => x.offer && x.id > m.id && x.from === m.from && x.to === m.to);
  if (newer) return "superseded";
  if (v.current_turn >= m.offer.until) return "expired";
  return "open";
}
function offerButtons(m, v) {
  if (m.to !== v.empire.id || (v.seat && v.seat.view_as)) return null;
  const st = offerState(m, v);
  const box = el("div", { class: "offer-actions" });
  // an ANY offer (DECISIONS G-23), "for any 1000 EU technology of yours", has one alternative
  const any = m.offer.any;
  const alts = any ? [null] : m.offer.wants;
  const what = w => w === null ? `any ${any} EU tech of yours` : `your ${techName(w)}`;
  const order = w => `TTNPR ${w === null ? `ANY ${any}` : w} ${m.offer.give} ${m.from_name}`;
  if (st !== "open" || isHistory()) {
    box.append(...alts.map(w => el("button", { type: "button", class: "ghost small", disabled: true },
      `Accept: ${what(w)} for their ${techName(m.offer.give)}`)),
      el("span", { class: "dim offer-state" }, st === "open" ? " (go to the current turn to accept)" : st === "expired" ? " Expired" : " Expired (replaced by a newer offer)"));
    return box;
  }
  const inDraft = w => (S.draft || []).some(d => d.code === "TTNPR" && Number(d.want) === m.offer.give && String(d.race).toLowerCase() === String(m.from_name).toLowerCase()
    && (w === null ? d.give === undefined && Number(d.give_any_cost) === any : Number(d.give) === w));
  alts.forEach((w, i) => {
    const has = inDraft(w);
    box.append(el("button", { type: "button", class: has ? "ghost small" : "primary small", "data-offer": m.id, "data-alt": i, title: order(w),
      onclick: async () => {
        try {
          const r = await api(`/api/games/${S.gid}/chat/${m.id}/accept`, { gid: S.gid, body: { alt: i } });
          const was = S.submitted;
          S.draft = r.orders; S.submitted = r.submitted; S.checks = null;
          emit("draft");
          toast(r.added ? `Order added: ${r.order.text}. The trade happens when the turn runs.` : `${r.order.text} is already in your orders.`, "good", 6000);
          for (const wn of r.warnings || []) toast(wn, "info", 6000);
          if (was && r.withdrawn) toast("Your submission was withdrawn because the orders changed. Submit again when ready.", "info", 6000);
          renderChat(C.box);
        } catch (er) { toast(er.message, "error"); }
      } }, has ? `In your orders: ${what(w).replace(/^your /, "")} for ${techName(m.offer.give)}` : `Accept: ${what(w)} for their ${techName(m.offer.give)}`));
  });
  return box;
}
