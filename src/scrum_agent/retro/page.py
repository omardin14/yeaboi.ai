"""The self-contained browser board page served to teammates.

``build_board_html()`` returns ONE HTML string with inline CSS + JS and no
external requests (no CDN, no third-party iframe) so it works on any LAN device —
and over the Cloudflare tunnel — without the app installed, fully offline.

The page is **token-free**: ``GET /`` is unauthenticated, so baking the access
token into the HTML would leak it to any LAN peer. Instead the client reads the
token from its own URL (``?token=``) or obtains it by typing the short **join
code** into the code-entry gate (``POST /api/join``).

Features: four grids; **drag** cards to reorder / move between grids;
**edit/delete** your own cards (author-only, enforced server-side); emoji
**reactions**; a **who's-here** presence row + per-grid **typing indicators**; a
shared **countdown timer** with a **confetti + alarm** finish; a join modal with
an **avatar picker** + 🎲 **random names** (editable later); a **theme switcher**;
**Web-Audio** background music (ambient/lofi/focus/hip-hop/jazz) with a live
**visualizer**; and an **invite** popover with a scannable **QR**.

The big CSS/JS blocks are plain (non-f-string) module constants with
``__PLACEHOLDER__`` markers filled by :func:`build_board_html` via ``str.replace``
— this avoids f-string ``{{ }}`` brace-escaping. Untrusted strings (card text,
names) are rendered via ``textContent`` (``esc()``), never raw ``innerHTML``.

# See README: "Guardrails" — output validation / escaping
"""

from __future__ import annotations

import json

from scrum_agent.retro.board import AVATARS, REACTION_EMOJIS, RETRO_GRID_LABELS, RETRO_GRIDS

# Grid (key, label) pairs for the client, kept in server order.
_GRID_JS = [[k, RETRO_GRID_LABELS[k]] for k in RETRO_GRIDS]

# Fun random-name word lists (cosmetic, client-only). Kept tasteful-but-silly.
_ADJECTIVES = [
    "Sexy",
    "Ghost",
    "Cosmic",
    "Sneaky",
    "Turbo",
    "Feral",
    "Velvet",
    "Rogue",
    "Disco",
    "Thunder",
    "Silent",
    "Funky",
    "Midnight",
    "Wild",
    "Neon",
    "Grumpy",
    "Cyber",
    "Lonesome",
    "Radical",
    "Mystic",
    "Spicy",
    "Chrome",
    "Groovy",
    "Danger",
]
_NOUNS = [
    "Cowboy",
    "Dude",
    "Llama",
    "Wizard",
    "Raccoon",
    "Pirate",
    "Ninja",
    "Yeti",
    "Goblin",
    "Falcon",
    "Panda",
    "Viking",
    "Phantom",
    "Otter",
    "Bandit",
    "Comet",
    "Walrus",
    "Samurai",
    "Gecko",
    "Nomad",
    "Badger",
    "Wombat",
    "Sphinx",
    "Hologram",
]


_CSS = """
:root, [data-theme="midnight"] {
  --bg:#0d1117; --panel:#161b22; --line:#30363d; --text:#c9d1d9;
  --muted:#8b949e; --accent:#50bebe; --accent2:#a371f7; --card:#0d1117; --ink:#04211f;
}
[data-theme="light"] {
  --bg:#f6f8fa; --panel:#ffffff; --line:#d0d7de; --text:#1f2328;
  --muted:#656d76; --accent:#0969da; --accent2:#8250df; --card:#f6f8fa; --ink:#ffffff;
}
[data-theme="solarized"] {
  --bg:#002b36; --panel:#073642; --line:#0a4b59; --text:#eee8d5;
  --muted:#93a1a1; --accent:#2aa198; --accent2:#d33682; --card:#002b36; --ink:#002b36;
}
[data-theme="synthwave"] {
  --bg:#1a1033; --panel:#241847; --line:#3d2a6b; --text:#f5e6ff;
  --muted:#a48fd0; --accent:#ff5edb; --accent2:#36e0ff; --card:#150c29; --ink:#1a1033;
}
[data-theme="forest"] {
  --bg:#0c1a12; --panel:#12261b; --line:#1f3a2a; --text:#d7e8dc;
  --muted:#89a894; --accent:#4cc38a; --accent2:#d9c26a; --card:#0a160f; --ink:#04211a;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
/* ── Header / toolbar ─────────────────────────────────────────── */
header { padding:11px 18px; border-bottom:1px solid var(--line);
         display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.brand { display:flex; align-items:baseline; gap:8px; }
.brand .title { color:var(--accent); font-size:17px; font-weight:700; letter-spacing:.01em; }
.brand .count { color:var(--muted); font-size:12.5px; }
header .spacer { flex:1; }

/* Presence: a distinct "you" chip + an overlapping stack of teammates */
.presence { display:flex; align-items:center; gap:10px; }
.me-chip { display:flex; align-items:center; gap:6px; background:var(--panel);
           border:1px solid var(--line); border-radius:999px; padding:3px 6px 3px 8px;
           cursor:pointer; font:inherit; font-size:13px; color:var(--text); }
.me-chip:hover { border-color:var(--accent); }
.me-chip .pen { color:var(--muted); font-size:12px; }
.avatars { display:flex; align-items:center; }
.avatars .av-dot { width:26px; height:26px; border-radius:50%; background:var(--panel);
                   border:2px solid var(--bg); box-shadow:0 0 0 1px var(--line); margin-left:-8px;
                   display:flex; align-items:center; justify-content:center; font-size:14px; }
.avatars .av-dot:first-child { margin-left:0; }
.avatars .more { font-size:12px; color:var(--muted); margin-left:6px; }
.room-btn { display:flex; align-items:center; gap:5px; background:var(--panel); border:1px solid var(--line);
            border-radius:999px; padding:3px 10px; cursor:pointer; font:inherit; font-size:13px; color:var(--text); }
.room-btn:hover, .room-btn.open { border-color:var(--accent); }
.roster { display:flex; flex-direction:column; gap:8px; min-width:190px; max-height:280px; overflow:auto; }
.roster .r { display:flex; align-items:center; gap:8px; font-size:13.5px; }
.roster .r .nm { flex:1; }
.roster .r .tag { font-size:11px; }
.roster .r .tag.you { color:var(--accent); }
.roster .r .tag.typing { color:var(--accent2); font-style:italic; }
.roster .empty { color:var(--muted); font-size:13px; }

/* Compact icon toolbar */
.toolbar { display:flex; align-items:center; gap:8px; }
#viz { width:34px; height:22px; opacity:0; transition:opacity .2s; }
#viz.on { opacity:1; }
.tbtn { display:flex; align-items:center; gap:6px; height:34px; padding:0 11px;
        background:var(--panel); border:1px solid var(--line); border-radius:9px;
        color:var(--text); cursor:pointer; font:inherit; font-size:14px; line-height:1; }
.tbtn:hover { border-color:var(--accent); }
.tbtn.open { border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.tbtn.primary { background:var(--accent); color:var(--ink); border-color:transparent; font-weight:600; }
.tbtn.primary:hover { filter:brightness(1.08); }
.tbtn .ico { font-size:15px; }
.tbtn.playing { border-color:var(--accent); animation:pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow:0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent); } }
#timer-btn .rd { font-variant-numeric:tabular-nums; font-weight:700; color:var(--accent);
                 min-width:42px; text-align:right; }
#timer-btn .rd:empty { display:none; }  /* collapse the readout when no timer runs */
#timer-btn.running { border-color:var(--accent); }
#timer-btn.done .rd { color:#f85149; animation:blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity:.3; } }

/* Popovers — one control panel per toolbar button */
.pop { position:fixed; top:56px; right:16px; z-index:25; width:auto;
       background:var(--panel); border:1px solid var(--line); border-radius:12px;
       box-shadow:0 12px 32px rgba(0,0,0,.35); padding:14px; animation:popin .14s ease-out; }
.pop.left { left:16px; right:auto; }
@keyframes popin { from { opacity:0; transform:translateY(-6px); } }
.pop .row { display:flex; align-items:center; gap:10px; }
.pop label { font-size:12px; color:var(--muted); display:block; margin:0 0 6px; }
.pop select, .pop input[type=number] { background:var(--card); color:var(--text);
        border:1px solid var(--line); border-radius:8px; padding:6px 8px; font:inherit; }
.pop input[type=number] { width:64px; }
.pop input[type=range] { accent-color:var(--accent); width:120px; }
.playbtn { display:flex; align-items:center; justify-content:center; width:34px; height:34px;
           background:var(--accent); color:var(--ink); border:0; border-radius:9px; cursor:pointer; font-size:15px; }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:9px; overflow:hidden; }
.seg .preset { background:transparent; border:0; border-right:1px solid var(--line); color:var(--text);
               padding:6px 12px; cursor:pointer; font:inherit; font-size:13px; }
.seg .preset:last-child { border-right:0; }
.seg .preset:hover { background:color-mix(in srgb, var(--accent) 16%, transparent); }
.swatches { display:flex; gap:8px; }
.swatch { width:34px; height:34px; border-radius:9px; border:2px solid transparent; cursor:pointer;
          padding:0; position:relative; overflow:hidden; }
.swatch.sel { border-color:var(--accent); }
.swatch .dot { position:absolute; right:4px; bottom:4px; width:9px; height:9px; border-radius:50%; }

.grids { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; padding:18px; }
@media (max-width:900px) { .grids { grid-template-columns:1fr 1fr; } }
@media (max-width:560px) { .grids { grid-template-columns:1fr; } }
.col { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px;
       display:flex; flex-direction:column; }
.col h2 { font-size:14px; margin:0 0 10px; color:var(--accent); letter-spacing:.02em; }
.cards { flex:1; min-height:44px; }
.cards.drop-target { outline:2px dashed var(--accent); outline-offset:3px; border-radius:8px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:9px 10px; margin:0 0 8px; cursor:grab; }
.card.dragging { opacity:.4; }
.card .body { white-space:pre-wrap; word-break:break-word; }
.card.ai { border-color:var(--accent); background:rgba(80,190,190,.06); }
.card .who { color:var(--muted); font-size:12px; margin-top:5px; display:flex; align-items:center; gap:8px; }
.card .who .spacer { flex:1; }
.act { background:transparent; border:0; color:var(--muted); cursor:pointer; font-size:13px; padding:0 2px; }
.act:hover { color:var(--accent); }
.act.danger:hover { color:#f85149; }
.editbox { width:100%; background:var(--card); color:var(--text); border:1px solid var(--accent);
           border-radius:6px; padding:6px; font:inherit; resize:vertical; }
.rx { display:flex; flex-wrap:wrap; gap:4px; margin-top:7px; }
.chip { background:transparent; border:1px solid var(--line); border-radius:999px;
        padding:1px 7px; cursor:pointer; font:inherit; font-size:13px; line-height:1.5; color:var(--text); }
.chip:hover { border-color:var(--accent); }
.chip.mine { background:rgba(80,190,190,.18); border-color:var(--accent); }
.chip span { color:var(--muted); font-size:12px; margin-left:3px; }
.typing { color:var(--accent2); font-size:12px; min-height:16px; margin-top:6px; font-style:italic; }
.add { margin-top:6px; }
textarea { width:100%; background:var(--card); color:var(--text); border:1px solid var(--line);
           border-radius:8px; padding:8px; resize:vertical; font:inherit; }
.addbtn { margin-top:6px; background:var(--accent); color:var(--ink); border:0; border-radius:8px;
          padding:7px 14px; font:inherit; font-weight:600; cursor:pointer; }
.addbtn:hover { filter:brightness(1.1); }

.overlay { position:fixed; inset:0; background:rgba(0,0,0,.75); display:flex;
           align-items:center; justify-content:center; padding:16px; z-index:20; }
.overlay .box { background:var(--panel); border:1px solid var(--line); border-radius:14px;
                padding:20px; width:100%; max-width:420px; }
.overlay h2 { margin:0 0 12px; color:var(--accent); }
.namerow { display:flex; gap:8px; }
.field { flex:1; background:var(--card); color:var(--text); border:1px solid var(--line);
         border-radius:8px; padding:9px; font:inherit; }
.dice { background:var(--panel); border:1px solid var(--line); border-radius:8px;
        padding:0 12px; cursor:pointer; font-size:18px; }
.avatars { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; }
.av { font-size:22px; background:var(--card); border:1px solid var(--line); border-radius:10px;
      width:40px; height:40px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.av.sel { border-color:var(--accent); background:rgba(80,190,190,.18); }
.primary { width:100%; margin-top:6px; background:var(--accent); color:var(--ink); border:0;
           border-radius:8px; padding:10px; font:inherit; font-weight:700; cursor:pointer; }
.qrwrap { background:#fff; border-radius:10px; padding:10px; display:flex; justify-content:center; }
.qrwrap img { width:220px; height:220px; }
.hidden { display:none !important; }
#confetti { position:fixed; inset:0; pointer-events:none; z-index:30; }
"""


_JS = r"""
const GRIDS = __GRIDS__;
const EMOJIS = __EMOJIS__;
const AVATARS = __AVATARS__;
const ADJS = __ADJS__;
const NOUNS = __NOUNS__;

let TOKEN = new URLSearchParams(location.search).get("token") || "";
let PID = localStorage.getItem("retro_pid");
if (!PID) { PID = (self.crypto && crypto.randomUUID) ? crypto.randomUUID() : "p" + Math.random().toString(36).slice(2); localStorage.setItem("retro_pid", PID); }
let NAME = localStorage.getItem("retro_name") || "";
let AVATAR = localStorage.getItem("retro_avatar") || AVATARS[0];
let THEME = localStorage.getItem("retro_theme") || "midnight";
let JOINED = false, LOOPING = false;
let TYPING_GRID = "", typingTimer = null;
let TIMER = { running: false }, OFFSET = 0, firedFor = null;
let EDITING = null;                          // card id being edited inline
const MY_REACTIONS = {};                     // card_id -> Set(emoji) I reacted with
let DRAG_ID = null;

function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
function api(path) { return path + (path.indexOf("?") < 0 ? "?" : "&") + "token=" + encodeURIComponent(TOKEN); }
function postJSON(path, body) {
  return fetch(api(path), { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ pid: PID }, body || {})) });
}
function randomName() { return ADJS[Math.floor(Math.random()*ADJS.length)] + " " + NOUNS[Math.floor(Math.random()*NOUNS.length)]; }
function applyTheme(t) { THEME = t; document.documentElement.setAttribute("data-theme", t); localStorage.setItem("retro_theme", t); }

/* ── Join code gate ─────────────────────────────────────────── */
async function submitCode() {
  const code = (document.getElementById("code-in").value || "").trim();
  if (!code) return;
  const err = document.getElementById("code-err"); err.textContent = "";
  try {
    const r = await fetch("/api/join", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
    if (!r.ok) { err.textContent = "That code didn't work — check the host's screen."; return; }
    const d = await r.json();
    TOKEN = d.token;
    history.replaceState(null, "", "/?token=" + encodeURIComponent(TOKEN));
    document.getElementById("code-modal").classList.add("hidden");
    afterToken();
  } catch (e) { err.textContent = "Could not reach the retro."; }
}

/* ── Profile (name + avatar), also used to rename later ─────── */
function buildAvatars() {
  const wrap = document.getElementById("avatars");
  wrap.innerHTML = AVATARS.map(a => '<button class="av" data-av="' + a + '">' + a + '</button>').join("");
  wrap.querySelectorAll(".av").forEach(b => b.addEventListener("click", () => {
    AVATAR = b.getAttribute("data-av");
    wrap.querySelectorAll(".av").forEach(x => x.classList.toggle("sel", x === b));
  }));
  markAvatar();
}
function markAvatar() { document.querySelectorAll(".av").forEach(x => x.classList.toggle("sel", x.getAttribute("data-av") === AVATAR)); }
function openProfile() { document.getElementById("name-in").value = NAME; markAvatar(); document.getElementById("modal").classList.remove("hidden"); document.getElementById("name-in").focus(); }
function saveProfile() {
  const v = (document.getElementById("name-in").value || "").trim();
  NAME = v || randomName();
  localStorage.setItem("retro_name", NAME);
  localStorage.setItem("retro_avatar", AVATAR);
  document.getElementById("modal").classList.add("hidden");
  JOINED = true;
  paintMe();
  startLoop();
}
function paintMe() { document.getElementById("me").innerHTML = (AVATAR || "🙂") + " " + esc(NAME) + ' <span class="pen">✎</span>'; }

/* ── Grids + cards ──────────────────────────────────────────── */
function buildCols() {
  const g = document.getElementById("grids");
  g.innerHTML = GRIDS.map(([k, label]) =>
    '<div class="col"><h2>' + esc(label) + '</h2>' +
    '<div class="cards" id="cards-' + k + '" data-grid="' + k + '"></div>' +
    '<div class="typing" id="typing-' + k + '"></div>' +
    '<div class="add"><textarea rows="2" id="in-' + k + '" placeholder="Add a card…"></textarea>' +
    '<button class="addbtn" data-grid="' + k + '">Add</button></div></div>'
  ).join("");
  g.querySelectorAll("button.addbtn").forEach(b => b.addEventListener("click", () => addCard(b.getAttribute("data-grid"))));
  g.querySelectorAll("textarea").forEach(t => {
    const grid = t.id.slice(3);
    t.addEventListener("input", () => onType(grid));
    t.addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addCard(grid); });
  });
  g.querySelectorAll(".cards").forEach(box => {
    box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("drop-target"); });
    box.addEventListener("dragleave", () => box.classList.remove("drop-target"));
    box.addEventListener("drop", e => onDrop(e, box));
  });
}
function onType(grid) { TYPING_GRID = grid; clearTimeout(typingTimer); typingTimer = setTimeout(() => { TYPING_GRID = ""; }, 2500); }

function reactionBar(card) {
  const mine = MY_REACTIONS[card.id] || new Set();
  const rx = card.reactions || {};
  return '<div class="rx">' + EMOJIS.map(e => {
    const n = rx[e] || 0;
    return '<button class="chip' + (mine.has(e) ? " mine" : "") + '" data-card="' + card.id + '" data-emoji="' + e + '">' +
           e + (n ? '<span>' + n + '</span>' : "") + '</button>';
  }).join("") + '</div>';
}
function cardHTML(card, avatarByName) {
  const isAI = card.origin === "ai";
  const badge = isAI ? "🤖 AI" : ((avatarByName[card.author] || "") + " " + esc(card.author)).trim();
  let actions = '<span class="spacer"></span>';
  if (card.mine && !isAI) {
    actions += '<button class="act" data-edit="' + card.id + '" title="Edit">✎</button>' +
               '<button class="act danger" data-del="' + card.id + '" title="Delete">✕</button>';
  }
  const body = EDITING === card.id
    ? '<textarea class="editbox" id="edit-' + card.id + '" rows="2">' + esc(card.text) + '</textarea>' +
      '<button class="act" data-save="' + card.id + '">Save</button><button class="act" data-cancel="1">Cancel</button>'
    : '<div class="body">' + esc(card.text) + '</div>';
  return '<div class="card ' + (isAI ? "ai" : "") + '" draggable="true" data-id="' + card.id + '">' +
         body + '<div class="who">' + badge + actions + '</div>' + reactionBar(card) + '</div>';
}

async function addCard(grid) {
  const el = document.getElementById("in-" + grid);
  const text = (el.value || "").trim();
  if (!text) return;
  el.value = ""; TYPING_GRID = "";
  try { const r = await postJSON("/api/cards", { grid, text, author: NAME }); if (r.ok) render((await r.json()).state); } catch (e) {}
}
async function react(cardId, emoji) {
  try {
    const r = await postJSON("/api/react", { card_id: cardId, emoji });
    if (!r.ok) return;
    const d = await r.json();
    const set = MY_REACTIONS[cardId] || (MY_REACTIONS[cardId] = new Set());
    if (d.reacted) set.add(emoji); else set.delete(emoji);
    render(d.state);
  } catch (e) {}
}
async function saveEdit(cardId) {
  const box = document.getElementById("edit-" + cardId);
  const text = box ? (box.value || "").trim() : "";
  EDITING = null;
  if (text) { try { const r = await postJSON("/api/card/edit", { card_id: cardId, text }); if (r.ok) return render((await r.json()).state); } catch (e) {} }
  tick();
}
async function deleteCard(cardId) {
  try { const r = await postJSON("/api/card/delete", { card_id: cardId }); if (r.ok) render((await r.json()).state); } catch (e) {}
}

/* ── Drag & drop ────────────────────────────────────────────── */
function onDrop(e, box) {
  e.preventDefault();
  box.classList.remove("drop-target");
  if (!DRAG_ID) return;
  const grid = box.getAttribute("data-grid");
  const cards = Array.prototype.slice.call(box.querySelectorAll(".card"));
  let index = cards.length;
  for (let i = 0; i < cards.length; i++) {
    const r = cards[i].getBoundingClientRect();
    if (e.clientY < r.top + r.height / 2) { index = i; break; }
  }
  moveCard(DRAG_ID, grid, index);
  DRAG_ID = null;
}
async function moveCard(cardId, grid, index) {
  try { const r = await postJSON("/api/card/move", { card_id: cardId, grid, index }); if (r.ok) render((await r.json()).state); } catch (e) {}
}

/* ── Timer ──────────────────────────────────────────────────── */
async function startTimer(secs) { try { const r = await postJSON("/api/timer", { action: "start", duration: secs }); if (r.ok) render((await r.json()).state); } catch (e) {} }
async function stopTimer() { try { const r = await postJSON("/api/timer", { action: "stop" }); if (r.ok) render((await r.json()).state); } catch (e) {} }
function customTimer() { const m = parseInt(document.getElementById("custom-min").value || "0", 10); if (m > 0) startTimer(m * 60); }
function paintTimer() {
  const el = document.getElementById("timer-readout");
  const btn = document.getElementById("timer-btn");
  if (!TIMER.running || !TIMER.end_epoch) { el.textContent = ""; btn.classList.remove("running", "done"); return; }
  const rem = Math.max(0, Math.round(TIMER.end_epoch - (Date.now() / 1000 + OFFSET)));
  const m = Math.floor(rem / 60), s = rem % 60;
  el.textContent = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  btn.classList.add("running");
  btn.classList.toggle("done", rem === 0);
  if (rem === 0 && firedFor !== TIMER.end_epoch) { firedFor = TIMER.end_epoch; celebrate(); }
}
setInterval(paintTimer, 250);

/* ── Render live state ──────────────────────────────────────── */
function render(state) {
  if (!state) return;
  if (state.timer) { TIMER = state.timer; OFFSET = state.timer.now_epoch - Date.now() / 1000; }
  const avatarByName = {};
  (state.presence || []).forEach(p => { if (p.avatar) avatarByName[p.name] = p.avatar; });

  const byGrid = {}; GRIDS.forEach(([k]) => byGrid[k] = []);
  (state.cards || []).forEach(c => { (byGrid[c.grid] || (byGrid[c.grid] = [])).push(c); });
  const typingByGrid = {}; (state.typing || []).forEach(t => { (typingByGrid[t.grid] || (typingByGrid[t.grid] = [])).push(t.name); });

  GRIDS.forEach(([k]) => {
    const box = document.getElementById("cards-" + k);
    if (box) box.innerHTML = (byGrid[k] || []).map(c => cardHTML(c, avatarByName)).join("");
    const tl = document.getElementById("typing-" + k);
    if (tl) { const names = (typingByGrid[k] || []).filter(n => n !== NAME); tl.textContent = names.length ? (names.join(", ") + (names.length > 1 ? " are" : " is") + " typing…") : ""; }
  });
  wireCards();

  const pr = document.getElementById("presence");
  if (pr) {
    // Others only — you are already shown by the #me chip (avoids the duplicate).
    const others = (state.presence || []).filter(p => p.name !== NAME);
    const shown = others.slice(0, 5);
    pr.innerHTML = shown.map(p => '<span class="av-dot" title="' + esc(p.name) + '">' + (p.avatar || "🙂") + "</span>").join("") +
      (others.length > shown.length ? '<span class="more">+' + (others.length - shown.length) + "</span>" : "");
  }
  // Room count = everyone present (you + teammates); the roster lists them by name.
  document.getElementById("roomcount").textContent = Math.max(1, (state.presence || []).length);
  renderRoom(state);
  const n = (state.cards || []).length;
  document.getElementById("count").textContent = "· " + n + " card" + (n === 1 ? "" : "s");
}
function renderRoom(state) {
  const list = document.getElementById("room-list");
  if (!list) return;
  const typing = new Set((state.typing || []).map(t => t.name));
  const people = state.presence || [];
  list.innerHTML = people.length
    ? people.map(p => {
        const you = p.name === NAME;
        const tag = you ? '<span class="tag you">you</span>'
          : (typing.has(p.name) ? '<span class="tag typing">typing…</span>' : "");
        return '<div class="r"><span>' + (p.avatar || "🙂") + '</span><span class="nm">' + esc(p.name) + "</span>" + tag + "</div>";
      }).join("")
    : '<div class="empty">Just you so far — share the code to invite the team.</div>';
}
function wireCards() {
  document.querySelectorAll(".chip").forEach(ch => ch.onclick = () => react(ch.getAttribute("data-card"), ch.getAttribute("data-emoji")));
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => { EDITING = b.getAttribute("data-edit"); tick(); });
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = () => deleteCard(b.getAttribute("data-del")));
  document.querySelectorAll("[data-save]").forEach(b => b.onclick = () => saveEdit(b.getAttribute("data-save")));
  document.querySelectorAll("[data-cancel]").forEach(b => b.onclick = () => { EDITING = null; tick(); });
  document.querySelectorAll(".card").forEach(c => {
    c.addEventListener("dragstart", () => { DRAG_ID = c.getAttribute("data-id"); c.classList.add("dragging"); });
    c.addEventListener("dragend", () => c.classList.remove("dragging"));
  });
}

/* ── Poll loop ──────────────────────────────────────────────── */
async function tick() {
  if (!TOKEN) return;
  try {
    let state;
    if (JOINED) {
      const r = await postJSON("/api/presence", { name: NAME, avatar: AVATAR, typing_grid: TYPING_GRID });
      if (r.ok) state = await r.json();
    } else {
      const r = await fetch(api("/api/state") + "&pid=" + encodeURIComponent(PID));
      if (r.ok) state = await r.json();
    }
    if (state) render(state);
  } catch (e) {}
}
function startLoop() { if (LOOPING) return; LOOPING = true; tick(); setInterval(tick, 1200); }

/* ── Invite QR popover ──────────────────────────────────────── */
function toggleInvite() {
  const m = document.getElementById("invite-modal");
  if (m.classList.contains("hidden")) {
    document.getElementById("invite-img").src = api("/api/qr");
    m.classList.remove("hidden");
  } else { m.classList.add("hidden"); }
}

/* ── Toolbar popovers (one open at a time) ──────────────────── */
const POPS = { "music-pop": "music-btn", "timer-pop": "timer-btn", "theme-pop": "theme-btn", "room-pop": "room-btn" };
function closePops() {
  Object.keys(POPS).forEach(id => {
    document.getElementById(id).classList.add("hidden");
    document.getElementById(POPS[id]).classList.remove("open");
  });
}
function togglePop(popId) {
  const open = !document.getElementById(popId).classList.contains("hidden");
  closePops();
  if (!open) {
    document.getElementById(popId).classList.remove("hidden");
    document.getElementById(POPS[popId]).classList.add("open");
  }
}
document.addEventListener("click", e => {
  if (e.target.closest(".pop") || e.target.closest(".tbtn") || e.target.closest(".room-btn")) return;
  closePops();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closePops(); });

/* ── Theme swatches ─────────────────────────────────────────── */
const THEMES = ["midnight", "light", "solarized", "synthwave", "forest"];
function buildSwatches() {
  const wrap = document.getElementById("swatches");
  wrap.innerHTML = THEMES.map(t =>
    '<button class="swatch" data-set-theme="' + t + '" title="' + t + '"></button>'
  ).join("");
  // Paint each swatch with its theme's bg + accent by momentarily reading the vars.
  wrap.querySelectorAll(".swatch").forEach(b => {
    const t = b.getAttribute("data-set-theme");
    const probe = document.createElement("div"); probe.setAttribute("data-theme", t);
    probe.style.display = "none"; document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    b.style.background = cs.getPropertyValue("--bg") || "#0d1117";
    b.insertAdjacentHTML("beforeend", '<span class="dot" style="background:' + (cs.getPropertyValue("--accent") || "#50bebe") + '"></span>');
    document.body.removeChild(probe);
    b.addEventListener("click", () => { applyTheme(t); markSwatch(); closePops(); });
  });
  markSwatch();
}
function markSwatch() { document.querySelectorAll(".swatch").forEach(s => s.classList.toggle("sel", s.getAttribute("data-set-theme") === THEME)); }

/* ── Web-Audio music (offline, generated) + visualizer ──────── */
const Music = (function () {
  let ctx = null, master = null, analyser = null, nodes = [], loop = null, playing = false;
  const NOTE = { C2:65.41, E2:82.41, G2:98, A2:110, D3:146.83, F3:174.61, G3:196, A3:220, C4:261.63, D4:293.66, E4:329.63, F4:349.23, G4:392, A4:440, B4:493.88, "C#4":277.18 };
  const MOODS = {
    calm:  { pad: [220, 277.18, 329.63], bpm: 0 },
    lofi:  { pad: [220, 261.63, 329.63, 392], bpm: 72, beat: "lofi" },
    focus: { pad: [261.63, 329.63, 392], bpm: 66, beat: "soft" },
    hiphop:{ pad: [110, 164.81], bpm: 86, beat: "boombap", bass: [65.41, 65.41, 98, 82.41] },
    jazz:  { pad: [261.63, 329.63, 392, 493.88], bpm: 120, beat: "swing", bass: [130.81, 146.83, 164.81, 196] },
  };
  let mood = "calm", volume = 0.35, step = 0;
  function ensure() {
    if (!ctx) { const AC = window.AudioContext || window.webkitAudioContext; ctx = new AC();
      master = ctx.createGain(); master.gain.value = volume;
      analyser = ctx.createAnalyser(); analyser.fftSize = 64;
      master.connect(analyser); analyser.connect(ctx.destination); }
  }
  function tone(freq, t, dur, type, peak) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type || "sine"; o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak || 0.3, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.05);
  }
  function noise(t, dur, peak) {
    const n = ctx.createBufferSource(), buf = ctx.createBuffer(1, ctx.sampleRate * dur, ctx.sampleRate);
    const data = buf.getChannelData(0); for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    n.buffer = buf; const g = ctx.createGain(), hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 6000;
    g.gain.setValueAtTime(peak || 0.2, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    n.connect(hp); hp.connect(g); g.connect(master); n.start(t); n.stop(t + dur);
  }
  function kick(t) { const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.setValueAtTime(150, t); o.frequency.exponentialRampToValueAtTime(50, t + 0.12);
    g.gain.setValueAtTime(0.6, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16); o.connect(g); g.connect(master); o.start(t); o.stop(t + 0.2); }
  function snare(t) { noise(t, 0.18, 0.35); tone(180, t, 0.12, "triangle", 0.15); }
  function tickStep() {
    if (!playing) return;
    const cfg = MOODS[mood]; const t = ctx.currentTime + 0.02; const beat = step % 4;
    if (cfg.beat === "boombap") { if (beat === 0 || beat === 2) kick(t); if (beat === 1 || beat === 3) snare(t); noise(t, 0.05, 0.08); }
    else if (cfg.beat === "swing") { noise(t, 0.04, 0.06); if (beat % 2 === 0) noise(t + (60 / cfg.bpm) * 0.66, 0.04, 0.05); if (beat === 0) kick(t); if (beat === 2) snare(t); }
    else if (cfg.beat === "lofi") { if (beat === 0 || beat === 2) kick(t); if (beat === 2) snare(t); noise(t, 0.04, 0.05); }
    else if (cfg.beat === "soft") { if (beat === 0) kick(t); }
    if (cfg.bass) { tone(cfg.bass[step % cfg.bass.length], t, (60 / cfg.bpm) * 0.9, "sawtooth", 0.18); }
    step++;
  }
  function startPad() {
    const cfg = MOODS[mood];
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 1100; lp.connect(master);
    const pad = ctx.createGain(); pad.gain.value = 0.14; pad.connect(lp);
    cfg.pad.forEach((f, i) => { const o = ctx.createOscillator(); o.type = i % 2 ? "sine" : "triangle"; o.frequency.value = f; o.detune.value = (i - 1) * 4; o.connect(pad); o.start(); nodes.push(o); });
    const lfo = ctx.createOscillator(), lg = ctx.createGain(); lfo.frequency.value = 0.08; lg.gain.value = 0.05; lfo.connect(lg); lg.connect(pad.gain); lfo.start(); nodes.push(lfo);
    nodes.push(pad, lp, lg);
  }
  function play() {
    ensure(); if (ctx.state === "suspended") ctx.resume();
    stopNodes(); step = 0; playing = true; startPad();
    const cfg = MOODS[mood];
    if (cfg.bpm > 0) loop = setInterval(tickStep, 60000 / cfg.bpm);
    document.getElementById("music-play").textContent = "⏸";
    document.getElementById("music-btn").classList.add("playing");
    document.getElementById("viz").classList.add("on");
    drawViz();
  }
  function stopNodes() { if (loop) { clearInterval(loop); loop = null; } nodes.forEach(n => { try { n.stop && n.stop(); n.disconnect && n.disconnect(); } catch (e) {} }); nodes = []; }
  function stop() {
    playing = false; stopNodes();
    document.getElementById("music-play").textContent = "▶";
    document.getElementById("music-btn").classList.remove("playing");
    document.getElementById("viz").classList.remove("on");
  }
  function drawViz() {
    const cv = document.getElementById("viz"); if (!cv || !analyser) return;
    const cx = cv.getContext("2d"), buf = new Uint8Array(analyser.frequencyBinCount);
    function frame() {
      if (!playing) { cx.clearRect(0, 0, cv.width, cv.height); return; }
      analyser.getByteFrequencyData(buf);
      cx.clearRect(0, 0, cv.width, cv.height);
      const bars = 16, w = cv.width / bars;
      const col = getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#50bebe";
      cx.fillStyle = col.trim() || "#50bebe";
      for (let i = 0; i < bars; i++) { const v = buf[i] / 255; const h = Math.max(2, v * cv.height); cx.fillRect(i * w, cv.height - h, w - 1, h); }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  return {
    toggle() { playing ? stop() : play(); },
    setVolume(v) { volume = v; if (master) master.gain.value = v; },
    setMood(m) { mood = m; if (playing) play(); },
    ctx() { ensure(); return ctx; }, out() { ensure(); return master; },
  };
})();

/* ── Timer finish: confetti + alarm ─────────────────────────── */
function celebrate() { confetti(); alarm(); }
function confetti() {
  const cv = document.getElementById("confetti"); cv.width = innerWidth; cv.height = innerHeight;
  const cx = cv.getContext("2d"); const N = 140, cols = ["#50bebe", "#a371f7", "#ff5edb", "#4cc38a", "#ffcf5e", "#ff5e5e"];
  const parts = []; for (let i = 0; i < N; i++) parts.push({ x: innerWidth / 2, y: innerHeight / 3, vx: (Math.random() - 0.5) * 14, vy: Math.random() * -12 - 4, c: cols[i % cols.length], r: 3 + Math.random() * 4, a: 1 });
  let frames = 0;
  (function step() {
    cx.clearRect(0, 0, cv.width, cv.height); frames++;
    parts.forEach(p => { p.vy += 0.35; p.x += p.vx; p.y += p.vy; p.a -= 0.008; cx.globalAlpha = Math.max(0, p.a); cx.fillStyle = p.c; cx.fillRect(p.x, p.y, p.r, p.r * 1.6); });
    cx.globalAlpha = 1;
    if (frames < 160) requestAnimationFrame(step); else cx.clearRect(0, 0, cv.width, cv.height);
  })();
}
function alarm() {
  try {
    const ctx = Music.ctx(), out = Music.out(); const t0 = ctx.currentTime;
    for (let k = 0; k < 4; k++) {
      [880, 1175].forEach(f => { const o = ctx.createOscillator(), g = ctx.createGain(); o.type = "square"; o.frequency.value = f;
        const t = t0 + k * 0.4; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
        o.connect(g); g.connect(out); o.start(t); o.stop(t + 0.32); });
    }
  } catch (e) {}
}

/* ── Wire up + start ────────────────────────────────────────── */
applyTheme(THEME);
buildCols();
buildAvatars();
buildSwatches();
paintTimer();
document.getElementById("dice").addEventListener("click", () => { document.getElementById("name-in").value = randomName(); });
document.getElementById("name-in").addEventListener("keydown", e => { if (e.key === "Enter") saveProfile(); });
document.getElementById("save-profile").addEventListener("click", saveProfile);
document.getElementById("me").addEventListener("click", openProfile);
document.getElementById("code-in").addEventListener("keydown", e => { if (e.key === "Enter") submitCode(); });
document.getElementById("code-join").addEventListener("click", submitCode);
// Toolbar: icon buttons toggle their popovers; controls live inside.
document.getElementById("music-btn").addEventListener("click", () => togglePop("music-pop"));
document.getElementById("timer-btn").addEventListener("click", () => togglePop("timer-pop"));
document.getElementById("theme-btn").addEventListener("click", () => togglePop("theme-pop"));
document.getElementById("room-btn").addEventListener("click", () => togglePop("room-pop"));
document.getElementById("music-play").addEventListener("click", () => Music.toggle());
document.getElementById("music-vol").addEventListener("input", e => Music.setVolume(parseFloat(e.target.value)));
document.getElementById("music-mood").addEventListener("change", e => Music.setMood(e.target.value));
document.querySelectorAll(".preset").forEach(b => b.addEventListener("click", () => { startTimer(parseInt(b.getAttribute("data-secs"), 10)); closePops(); }));
document.getElementById("custom-go").addEventListener("click", () => { customTimer(); closePops(); });
document.getElementById("timer-stop").addEventListener("click", () => { stopTimer(); closePops(); });
document.getElementById("invite-btn").addEventListener("click", toggleInvite);
document.getElementById("invite-close").addEventListener("click", toggleInvite);

function afterToken() {
  // Token known: go straight in if we have a saved profile, else prompt for it.
  paintMe();
  if (NAME && localStorage.getItem("retro_avatar")) { JOINED = true; document.getElementById("modal").classList.add("hidden"); startLoop(); }
  else { openProfile(); }
}
if (TOKEN) { document.getElementById("code-modal").classList.add("hidden"); afterToken(); }
else { document.getElementById("code-modal").classList.remove("hidden"); document.getElementById("code-in").focus(); }
"""


def build_board_html() -> str:
    """Return the complete self-contained retro board page (token-free)."""

    def _lit(v: object) -> str:
        # ensure_ascii=False keeps emojis literal (page is UTF-8); still escapes quotes.
        return json.dumps(v, ensure_ascii=False)

    js = (
        _JS.replace("__GRIDS__", _lit(_GRID_JS))
        .replace("__EMOJIS__", _lit(list(REACTION_EMOJIS)))
        .replace("__AVATARS__", _lit(list(AVATARS)))
        .replace("__ADJS__", _lit(_ADJECTIVES))
        .replace("__NOUNS__", _lit(_NOUNS))
    )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Sprint Retro</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        "<header>\n"
        '  <div class="brand"><span class="title">Sprint Retro</span>'
        '<span class="count" id="count"></span></div>\n'
        '  <div class="presence"><button class="me-chip" id="me"></button>'
        '<div class="avatars" id="presence"></div>'
        '<button class="room-btn" id="room-btn" title="Who\'s in the room">'
        '👥 <span id="roomcount">1</span></button></div>\n'
        '  <span class="spacer"></span>\n'
        '  <div class="toolbar">\n'
        '    <canvas id="viz" width="34" height="22" title="Now playing"></canvas>\n'
        '    <button class="tbtn" id="music-btn" title="Music"><span class="ico">♪</span></button>\n'
        '    <button class="tbtn" id="timer-btn" title="Timer"><span class="ico">⏱</span>'
        '<span class="rd" id="timer-readout"></span></button>\n'
        '    <button class="tbtn" id="theme-btn" title="Theme"><span class="ico">◑</span></button>\n'
        '    <button class="tbtn primary" id="invite-btn">Invite</button>\n'
        "  </div>\n"
        "</header>\n"
        # Music popover
        '<div id="music-pop" class="pop hidden"><div class="row">\n'
        '  <button class="playbtn" id="music-play">▶</button>\n'
        '  <input type="range" id="music-vol" min="0" max="1" step="0.05" value="0.35" title="Volume">\n'
        '  <select id="music-mood" title="Mood"><option value="calm">Ambient</option>'
        '<option value="lofi">Lo-fi</option><option value="focus">Focus</option>'
        '<option value="hiphop">Hip-hop</option><option value="jazz">Jazz</option></select>\n'
        "</div></div>\n"
        # Timer popover
        '<div id="timer-pop" class="pop hidden">\n'
        "  <label>Countdown</label>\n"
        '  <div class="row"><div class="seg">'
        '<button class="preset" data-secs="60">1m</button>'
        '<button class="preset" data-secs="120">2m</button>'
        '<button class="preset" data-secs="180">3m</button>'
        '<button class="preset" data-secs="300">5m</button></div></div>\n'
        '  <div class="row" style="margin-top:10px">'
        '<input type="number" id="custom-min" min="1" max="60" placeholder="min">'
        '<button class="tbtn" id="custom-go">Start</button>'
        '<button class="tbtn" id="timer-stop">Stop</button></div>\n'
        "</div>\n"
        # Theme popover
        '<div id="theme-pop" class="pop hidden">\n'
        "  <label>Theme</label>\n"
        '  <div class="swatches" id="swatches"></div>\n'
        "</div>\n"
        # Room roster popover (who's here) — left-anchored under the presence cluster
        '<div id="room-pop" class="pop left hidden">\n'
        "  <label>In the room</label>\n"
        '  <div class="roster" id="room-list"></div>\n'
        "</div>\n"
        '<div class="grids" id="grids"></div>\n'
        '<canvas id="confetti"></canvas>\n'
        # Code-entry gate (shown when the URL has no token)
        '<div id="code-modal" class="overlay hidden"><div class="box">\n'
        "  <h2>Join a retro</h2>\n"
        '  <p class="muted">Enter the share code shown on the host\'s screen.</p>\n'
        '  <div class="namerow"><input id="code-in" class="field" placeholder="e.g. A3F9-1B2C" autofocus>'
        '<button class="dice" id="code-join">Join</button></div>\n'
        '  <p class="muted" id="code-err" style="color:#f85149"></p>\n'
        "</div></div>\n"
        # Profile modal (name + avatar; reused for rename)
        '<div id="modal" class="overlay hidden"><div class="box">\n'
        "  <h2>Your name &amp; avatar</h2>\n"
        '  <div class="namerow"><input id="name-in" class="field" placeholder="Your name (or roll the dice →)">'
        '<button class="dice" id="dice" title="Random name">🎲</button></div>\n'
        '  <div class="avatars" id="avatars"></div>\n'
        '  <button class="primary" id="save-profile">Save</button>\n'
        "</div></div>\n"
        # Invite popover (QR)
        '<div id="invite-modal" class="overlay hidden"><div class="box">\n'
        "  <h2>Invite the team</h2>\n"
        '  <p class="muted">Scan to join instantly, or share the code from the host.</p>\n'
        '  <div class="qrwrap"><img id="invite-img" alt="join QR"></div>\n'
        '  <button class="primary" id="invite-close">Close</button>\n'
        "</div></div>\n"
        f"<script>{js}</script>\n</body>\n</html>"
    )
