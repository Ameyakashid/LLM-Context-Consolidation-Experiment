/* =====================================================================
   feeds.js — production feed config, fetch, and markdown parsing.
   The ADHD app writes these .md files atomically; we poll + render them.
   No backend here: only reading what the app already produces.
   ===================================================================== */
(function () {

const FEED_CONFIG = {
  tasks:    'feeds/tasks.md',
  state:    'feeds/state_buffers.md',
  schedule: 'feeds/schedule.md',
  voices:   'feeds/voices.md',     // OPTIONAL — backend-supplied inner-voice lines
  calendar: 'feeds/calendar.md',   // OPTIONAL — backend-supplied dated events
  alerts:   'feeds/alerts.json',   // OPTIONAL — polled overlay-alert queue
  pollMs:      30000,  // audit: feed check interval = 30s
  alertPollMs: 5000,   // alert queue checked every 5s for snappy overlays
};

/* ---- cognitive state lore (the 6 verified StateName literals) ---- */
const STATES = {
  baseline:   { color: '#9fb3c8', word: 'Even Keel',
                desc: 'The water is flat. Nothing pulls harder than anything else.' },
  focus:      { color: '#e6c781', word: 'Locked In',
                desc: 'The lens has found its subject. Stay while it holds.' },
  hyperfocus: { color: '#ff7a3c', word: 'Ablaze',
                desc: 'Time has gone liquid. The body still needs tending.' },
  avoidance:  { color: '#8f86b8', word: 'Turned Away',
                desc: 'The task is in the room. You keep finding the door.' },
  overwhelm:  { color: '#e0564a', word: 'Too Much At Once',
                desc: 'Every channel is open. Close all but one.' },
  rsd:        { color: '#b07cd6', word: 'Tender',
                desc: 'A small slight echoes loud — louder than it is true.' },
};

/* state sigils — line-art, currentColor */
const STATE_GLYPH = {
  baseline:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
       <circle cx="50" cy="50" r="40"/><path d="M22 50 H78"/>
       <circle cx="50" cy="50" r="6" fill="currentColor" stroke="none"/></svg>`,
  focus:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
       <path d="M10 50 C30 28 70 28 90 50 C70 72 30 72 10 50 Z"/>
       <circle cx="50" cy="50" r="13"/><circle cx="50" cy="50" r="4" fill="currentColor" stroke="none"/></svg>`,
  hyperfocus:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
       <path d="M50 12 C66 32 64 44 56 54 C72 50 70 30 70 30 C84 50 80 76 50 88 C22 78 16 54 30 36 C30 50 38 54 44 52 C36 40 40 24 50 12 Z"/></svg>`,
  avoidance:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
       <path d="M50 12 A38 38 0 1 1 18 66" stroke-dasharray="4 7"/>
       <path d="M40 44 L62 56 M62 44 L40 56"/></svg>`,
  overwhelm:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.3">
       <g stroke-linecap="round">
       <path d="M50 6 V26 M50 74 V94 M6 50 H26 M74 50 H94"/>
       <path d="M20 20 L34 34 M80 20 L66 34 M20 80 L34 66 M80 80 L66 66"/></g>
       <circle cx="50" cy="50" r="13"/></svg>`,
  rsd:
    `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
       <path d="M50 80 C18 58 22 30 40 30 C48 30 50 38 50 42 C50 38 52 30 60 30 C78 30 82 58 50 80 Z"/>
       <path d="M50 42 L44 56 L54 60 L48 74" stroke-width="1.1"/></svg>`,
};

/* ---- parsing helpers ---- */
const DASH = /\s*[—–-]\s*/; // em / en / hyphen tolerant

function splitSections(md) {
  // returns { headingLower: [lines...] }
  const out = {};
  let cur = null;
  (md || '').split(/\r?\n/).forEach((raw) => {
    const line = raw.trimEnd();
    const h = line.match(/^##\s+(.*)$/);
    if (h) { cur = h[1].trim(); out[cur] = out[cur] || []; return; }
    if (cur && line.trim().startsWith('-')) out[cur].push(line.trim().replace(/^-\s*/, ''));
  });
  return out;
}

function sectionByKeyword(sections, kw) {
  const key = Object.keys(sections).find((k) => k.toLowerCase().includes(kw));
  return key ? sections[key] : [];
}

function stripBold(s) { return s.replace(/\*\*(.+?)\*\*/g, '$1'); }

/* parse: - **Title** (priority) — due 2026-05-29 16:00 */
function parseTask(line) {
  const t = { title: '', prio: null, due: null, hint: null };
  const titleM = line.match(/\*\*(.+?)\*\*/);
  t.title = titleM ? titleM[1].trim() : stripBold(line).split(DASH)[0].trim();
  let rest = line.replace(/\*\*.+?\*\*/, '').trim();
  const prioM = rest.match(/\(([^)]+)\)/);
  if (prioM) { t.prio = prioM[1].trim().toLowerCase(); rest = rest.replace(/\([^)]+\)/, '').trim(); }
  rest = rest.replace(/^[—–-]\s*/, '').trim();
  const dueM = rest.match(/due\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?/i);
  if (dueM) { t.due = { date: dueM[1], time: dueM[2] || null }; }
  else if (rest) { t.hint = rest.replace(/^(waiting on|blocked:?\s*|need)\s*/i, '').trim() || rest; }
  return t;
}

/* parse: - **Energy**: 4/10 (low) */
function parseBuffer(line) {
  const nameM = line.match(/\*\*(.+?)\*\*/);
  const numM = line.match(/(\d+)\s*\/\s*(\d+)/);
  return {
    name: nameM ? nameM[1].trim() : line.split(':')[0].trim(),
    level: numM ? +numM[1] : 0,
    cap: numM ? +numM[2] : 10,
    low: /\(low\)/i.test(line),
  };
}

/* parse: - **Morning meds** — target 08:30 — taken */
function parseCheckin(line) {
  const nameM = line.match(/\*\*(.+?)\*\*/);
  const timeM = line.match(/(\d{1,2}:\d{2})/);
  const parts = stripBold(line).split(DASH).map((s) => s.trim()).filter(Boolean);
  const hint = parts.length ? parts[parts.length - 1].replace(/target\s*\d{1,2}:\d{2}/i, '').trim() : '';
  return {
    name: nameM ? nameM[1].trim() : (parts[0] || ''),
    time: timeM ? timeM[1].padStart(5, '0') : '',
    status: (hint || '').toLowerCase(),
    hint: hint,
  };
}

function parseTasks(md) {
  const s = splitSections(md);
  const cap = (arr, n, fn) => (arr || []).slice(0, n).map(fn);
  return {
    active:    cap(sectionByKeyword(s, 'active'), 6, parseTask),
    completed: cap(sectionByKeyword(s, 'complete'), 3, parseTask),
    blocked:   cap(sectionByKeyword(s, 'block'), 3, parseTask),
  };
}

function parseStateBuffers(md) {
  const sections = Object.keys(splitSections(md));
  // state lives in the heading itself: "## Cognitive state: focus"
  let state = 'baseline';
  const sm = (md || '').match(/cognitive state:\s*([a-z]+)/i);
  if (sm && STATES[sm[1].toLowerCase()]) state = sm[1].toLowerCase();
  const s = splitSections(md);
  const buffers = sectionByKeyword(s, 'buffer').slice(0, 8).map(parseBuffer);
  return { state, buffers, _sections: sections };
}

/* parse voices feed. Lines: "- LOGIC — 3 obligations remain."
   The token before the first dash is the speaker (LOGIC/EMPATHY/VOLITION). */
function parseVoices(md) {
  const s = splitSections(md);
  const lines = sectionByKeyword(s, 'voice').length
    ? sectionByKeyword(s, 'voice')
    : Object.values(s).flat();
  return lines.map((raw) => {
    const parts = stripBold(raw).split(DASH);
    if (parts.length >= 2) {
      return { who: parts[0].trim().toUpperCase(), line: parts.slice(1).join(' — ').trim() };
    }
    return { who: 'VOLITION', line: stripBold(raw).trim() };
  }).filter((v) => v.line);
}

/* parse calendar feed. Lines: "- 2026-05-29 16:00 — Reply to Dana"
   (time optional). Returns { date:'YYYY-MM-DD', time:'HH:MM'|null, title }. */
function parseEvents(md) {
  const s = splitSections(md);
  const lines = sectionByKeyword(s, 'event').length
    ? sectionByKeyword(s, 'event')
    : Object.values(s).flat();
  return lines.map((raw) => {
    const txt = stripBold(raw);
    const dM = txt.match(/(\d{4}-\d{2}-\d{2})/);
    if (!dM) return null;
    const tM = txt.match(/\b(\d{1,2}:\d{2})\b/);
    const title = txt.replace(dM[0], '').replace(tM ? tM[0] : '', '').replace(DASH, ' ').replace(/^[\s—–-]+/, '').trim();
    return { date: dM[1], time: tM ? tM[1].padStart(5, '0') : null, title };
  }).filter(Boolean);
}

function parseSchedule(md) {
  const s = splitSections(md);
  const list = (sectionByKeyword(s, 'schedule').length
      ? sectionByKeyword(s, 'schedule')
      : sectionByKeyword(s, 'check')
    ).slice(0, 8).map(parseCheckin);
  list.sort((a, b) => (a.time || '').localeCompare(b.time || ''));
  return list;
}

/* fetch a feed; on failure (e.g. files not deployed yet) return null so
   the caller can fall back to its last-known / embedded content. */
async function fetchFeed(path) {
  try {
    const r = await fetch(path + '?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) return null;
    return await r.text();
  } catch (e) { return null; }
}

window.FeedKit = {
  FEED_CONFIG, STATES, STATE_GLYPH,
  parseTasks, parseStateBuffers, parseSchedule, parseVoices, parseEvents, fetchFeed,
};

})();
