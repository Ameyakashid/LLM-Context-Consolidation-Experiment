/* =====================================================================
   fx.js — skill voices, webhook overlays, occult calendar.
   ===================================================================== */

/* ------------------------------------------------------------------ */
/*  SKILL VOICES — Volition / Empathy / Logic                          */
/*  Ambient inner-voice interjections built from live data. Display    */
/*  flavor only — the backend does not drive these.                    */
/* ------------------------------------------------------------------ */

const VOICE_COLORS = {
  LOGIC:    'var(--logic)',
  EMPATHY:  'var(--empathy)',
  VOLITION: 'var(--volition)',
};

function minutesUntil(hhmm) {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(':').map(Number);
  const now = new Date();
  let d = (h * 60 + m) - (now.getHours() * 60 + now.getMinutes());
  return d;
}

function buildVoiceLines(data) {
  const lines = [];
  const t = data.tasks || {}; const active = (t.active || []).length;
  const done = (t.completed || []).length;
  const low = (data.buffers || []).filter((b) => b.low);
  const next = (data.schedule || []).find((c) => minutesUntil(c.time) >= 0 && !/done|taken|kept/i.test(c.status));
  const hero = (t.active || [])[0];

  // LOGIC — cold arithmetic of the day
  if (active) lines.push(['LOGIC', `${active} ${active === 1 ? 'obligation remains' : 'obligations remain'}. A finite number. Finite numbers end.`]);
  if (next) { const m = minutesUntil(next.time); if (m != null) lines.push(['LOGIC', `${next.time} is ${m <= 0 ? 'now' : 'in ' + m + ' minutes'}. This is timing, not fate.`]); }
  if (done) lines.push(['LOGIC', `${done} ${done === 1 ? 'thing is' : 'things are'} already done today. The ledger is not empty.`]);

  // EMPATHY — warm, forgiving
  if (low.length) lines.push(['EMPATHY', `${low[0].name} is running low. The body is asking, not accusing.`]);
  if (done) lines.push(['EMPATHY', `You finished ${done} today. Let at least one of them count.`]);
  lines.push(['EMPATHY', `Whatever this hour holds, you needn't hold it gracefully.`]);

  // VOLITION — resolve
  if (hero) lines.push(['VOLITION', `Hold the line. The one in large letters. Then we breathe.`]);
  if (next) lines.push(['VOLITION', `You can meet ${next.name.toLowerCase()}. Decide it now, while it's easy.`]);
  lines.push(['VOLITION', `Stand. Pick the thing. Begin badly if you must — just begin.`]);

  return lines;
}

/* Optional backend override. When the app supplies its own lines (via
   feeds/voices.md or window.MM.setVoices([...])), they REPLACE the
   generated ones. Set to null/[] to fall back to the built-in generator. */
let _voiceOverride = null;
let _reshuffleVoices = null;   // assigned by startVoices so setVoices can re-pull

/* Accepts an array of { who, line } OR [who, line] OR plain strings.
   `who` is matched case-insensitively to LOGIC / EMPATHY / VOLITION;
   anything else still shows, tinted gilt. */
function setVoices(lines) {
  if (!Array.isArray(lines) || !lines.length) { _voiceOverride = null; }
  else {
    _voiceOverride = lines.map((v) => {
      if (Array.isArray(v)) return { who: String(v[0] || '').toUpperCase(), line: String(v[1] || '') };
      if (typeof v === 'string') return { who: 'VOLITION', line: v };
      return { who: String(v.who || 'VOLITION').toUpperCase(), line: String(v.line || v.text || '') };
    }).filter((v) => v.line);
  }
  if (_reshuffleVoices) _reshuffleVoices();
}

let _voiceTimer = null;
function startVoices(getData) {
  const el = document.getElementById('voice');
  const whoEl = el.querySelector('.voice__who');
  const lineEl = el.querySelector('.voice__line');
  let pool = []; let idx = 0;

  function reshuffle() {
    const src = (_voiceOverride && _voiceOverride.length)
      ? _voiceOverride.map((v) => [v.who, v.line])
      : buildVoiceLines(getData());
    pool = src.slice();
    for (let i = pool.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; [pool[i], pool[j]] = [pool[j], pool[i]]; }
    idx = 0;
  }
  _reshuffleVoices = reshuffle;
  function speak() {
    if (document.querySelector('.overlay.show')) { schedule(8000); return; } // yield to alerts
    if (idx >= pool.length || !pool.length) reshuffle();
    const [who, line] = pool[idx++] || ['VOLITION', 'Begin.'];
    el.style.setProperty('--voice-c', VOICE_COLORS[who] || 'var(--gilt)');
    whoEl.textContent = who;
    lineEl.textContent = line;
    el.classList.remove('hide'); el.classList.add('show');
    setTimeout(() => { el.classList.remove('show'); el.classList.add('hide'); }, 6400);
    schedule();
  }
  function schedule(ms) { clearTimeout(_voiceTimer); _voiceTimer = setTimeout(speak, ms || (16000 + Math.random() * 12000)); }
  reshuffle();
  schedule(6000);
}

/* ------------------------------------------------------------------ */
/*  WEBHOOK OVERLAYS — state_change / buffer_alert / missed_checkin    */
/*  Exact spec colors + durations + fade speeds.                       */
/* ------------------------------------------------------------------ */

const OVERLAY_TYPES = {
  state_change: {
    bg: '#101418', text: '#e6ebf0', border: '#2b3138', title: '#8ab4f8',
    dur: 20000, fade: 800, kicker: 'A shift in the weather',
    defaultTitle: 'State Change', foot: 'The display will return shortly.',
    sigil: `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
      <circle cx="50" cy="50" r="40"/>
      <path d="M50 14 A36 36 0 0 1 50 86 Z" fill="currentColor" stroke="none" opacity="0.85"/>
      <circle cx="50" cy="32" r="4" fill="#101418" stroke="none"/>
      <circle cx="50" cy="68" r="4" fill="currentColor" stroke="none"/></svg>`,
  },
  buffer_alert: {
    bg: '#1a0f0f', text: '#ffd7c7', border: '#5c2a1a', title: '#ff9f70',
    dur: 60000, fade: 1000, kicker: 'A buffer runs low',
    defaultTitle: 'Buffer Low', foot: 'High priority — tend to it when you can.',
    sigil: `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M50 10 L84 76 H16 Z"/>
      <path d="M50 38 V60" stroke-width="3" stroke-linecap="round"/>
      <circle cx="50" cy="70" r="2.6" fill="currentColor" stroke="none"/></svg>`,
  },
  missed_checkin: {
    bg: '#0f1a14', text: '#c7ffe0', border: '#1a5c3a', title: '#70ffb2',
    dur: 45000, fade: 800, kicker: 'An hour passed unkept',
    defaultTitle: 'Missed Check-in', foot: 'There is still time to make it right.',
    sigil: `<svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1.4">
      <circle cx="50" cy="50" r="38"/>
      <path d="M50 26 V52 L68 62" stroke-width="2" stroke-linecap="round"/>
      <path d="M50 12 L50 4 M50 96 L50 88" stroke-linecap="round"/></svg>`,
  },
};

const _ovQueue = [];
let _ovActive = false;

function renderOverlay(type, opts) {
  const cfg = OVERLAY_TYPES[type] || OVERLAY_TYPES.state_change;
  const ov = document.getElementById('overlay');
  ov.style.setProperty('--ov-bg', cfg.bg);
  ov.style.setProperty('--ov-text', cfg.text);
  ov.style.setProperty('--ov-border', cfg.border);
  ov.style.setProperty('--ov-title', cfg.title);
  ov.style.setProperty('--ov-fade', cfg.fade + 'ms');

  ov.querySelector('.overlay__sigil').innerHTML = cfg.sigil;
  ov.querySelector('.overlay__kicker').textContent = opts.kicker || cfg.kicker;
  ov.querySelector('.overlay__title').textContent = (opts.title || cfg.defaultTitle).toString();
  ov.querySelector('.overlay__msg').innerHTML = opts.message || '';
  ov.querySelector('.overlay__foot').textContent = opts.foot || cfg.foot;

  // countdown ring
  const ring = ov.querySelector('.overlay__ring .fg');
  const C = 2 * Math.PI * 15;
  ring.style.strokeDasharray = C;
  ring.style.strokeDashoffset = '0';
  ring.style.transition = 'none';
  // force reflow then animate
  void ring.getBoundingClientRect();
  ring.style.transition = `stroke-dashoffset ${cfg.dur}ms linear`;
  ring.style.strokeDashoffset = C;

  ov.classList.add('show');
  _ovActive = true;
  setTimeout(() => {
    ov.classList.remove('show');
    setTimeout(() => { _ovActive = false; pumpQueue(); }, cfg.fade + 50);
  }, cfg.dur);
}

function pumpQueue() {
  if (_ovActive || !_ovQueue.length) return;
  const next = _ovQueue.shift();
  renderOverlay(next.type, next.opts);
}

/* PUBLIC API for MMM-WebHookAlerts to call.
   window.MM.fireAlert('buffer_alert', { title, message, foot, kicker }) */
function fireAlert(type, opts = {}) {
  if (!OVERLAY_TYPES[type]) { console.warn('[MM] unknown alert type:', type); return; }
  _ovQueue.push({ type, opts });
  pumpQueue();
}

/* sensible demo defaults so each overlay can be previewed without a payload */
function demoAlert(type, data) {
  const d = data || {};
  if (type === 'state_change') {
    const to = (d.buffers && d.state) ? d.state : 'overwhelm';
    return fireAlert(type, {
      title: 'State Change',
      message: `from <span class="em">focus</span> to <span class="em">${to}</span>`,
    });
  }
  if (type === 'buffer_alert') {
    const low = (d.buffers || []).find((b) => b.low) || { name: 'Nourishment', level: 3, cap: 10 };
    return fireAlert(type, {
      title: 'Buffer Low',
      message: `<span class="em">${low.name}</span> at ${low.level}/${low.cap}. The body is asking.`,
    });
  }
  if (type === 'missed_checkin') {
    const c = (d.schedule || []).find((x) => /upcoming|missed/i.test(x.status)) || { name: 'Lunch + meds', time: '12:30' };
    return fireAlert(type, {
      title: 'Missed Check-in',
      message: `<span class="em">${c.name}</span> — target ${c.time}. Still time to keep it.`,
    });
  }
}

/* ------------------------------------------------------------------ */
/*  CALENDAR — occult month-leaf (real current date, no fake events)   */
/* ------------------------------------------------------------------ */

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

/* Optional backend-supplied events. Array of { date:'YYYY-MM-DD', time?:'HH:MM', title }.
   Populate via feeds/calendar.md or window.MM.setEvents([...]). Days with
   events get a marker dot; the panel lists this month's events in order. */
let _calEvents = [];
function setEvents(list) {
  _calEvents = Array.isArray(list) ? list.filter((e) => e && e.date) : [];
  if (document.getElementById('cal').classList.contains('show')) buildCalendar();
}

function buildCalendar() {
  const grid = document.getElementById('cal-grid');
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth(), today = now.getDate();
  document.getElementById('cal-month').textContent = MONTHS[m];
  document.getElementById('cal-year').textContent = y;

  const mPrefix = `${y}-${String(m + 1).padStart(2, '0')}-`;
  const dayHas = (d) => _calEvents.some((e) => e.date === mPrefix + String(d).padStart(2, '0'));

  grid.innerHTML = '';
  ['S','M','T','W','T','F','S'].forEach((d) => {
    const el = document.createElement('div'); el.className = 'cal__dow'; el.textContent = d; grid.appendChild(el);
  });
  const first = new Date(y, m, 1).getDay();
  const days = new Date(y, m + 1, 0).getDate();
  for (let i = 0; i < first; i++) { const el = document.createElement('div'); el.className = 'cal__day pad'; grid.appendChild(el); }
  for (let d = 1; d <= days; d++) {
    const el = document.createElement('div');
    el.className = 'cal__day' + (d === today ? ' today' : (d < today ? ' past' : '')) + (dayHas(d) ? ' has-event' : '');
    el.innerHTML = `${d}<span class="cal__mk"></span>`;
    grid.appendChild(el);
  }

  // this month's events, in chronological order
  const listEl = document.getElementById('cal-events');
  if (listEl) {
    const mine = _calEvents
      .filter((e) => e.date.startsWith(mPrefix))
      .sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || '')));
    listEl.innerHTML = mine.length ? mine.map((e) => {
      const dd = e.date.slice(8).replace(/^0/, '');
      return `<div class="cal__evt"><span class="cal__evt-d">${dd}</span>
        <span class="cal__evt-t">${e.title || ''}</span>
        ${e.time ? `<span class="cal__evt-h">${e.time}</span>` : ''}</div>`;
    }).join('') : '<div class="cal__evt cal__evt--none">No marked days this month.</div>';
  }
}

function openCalendar() { buildCalendar(); document.getElementById('cal').classList.add('show'); }
function closeCalendar() { document.getElementById('cal').classList.remove('show'); }

window.FX = { startVoices, setVoices, fireAlert, demoAlert, openCalendar, closeCalendar, setEvents };
