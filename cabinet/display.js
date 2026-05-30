/* =====================================================================
   display.js — clock, carousel, page rendering, hero rotation, boot.
   ===================================================================== */

const { FEED_CONFIG, STATES, STATE_GLYPH, parseTasks, parseStateBuffers, parseSchedule, parseVoices, parseEvents, fetchFeed } = window.FeedKit;

/* embedded fallbacks mirror the deployed feeds/ files so the screen is
   never blank if the app hasn't written them yet. */
const FALLBACK = {
  tasks: `## Active
- **Reply to Dana about the lease** (high) — due 2026-05-29 16:00
- **Call pharmacy for the refill** (high) — due 2026-05-29 17:30
- **Submit the reimbursement form** (med) — due 2026-05-29 18:00
- **Draft the Q2 retro notes** (med) — due 2026-05-30 10:00
- **Water the plants** (low) — due 2026-05-29 20:00
## Completed today
- **Morning pages** — 09:12
- **Stand-up sync** — 10:05
- **Sort inbox to zero** — 11:40
## Blocked
- **File the taxes** — waiting on W-2
- **Book the dentist** — need insurance card`,
  state: `## Cognitive state: focus
## Buffers
- **Energy**: 4/10 (low)
- **Focus**: 7/10
- **Social**: 5/10
- **Nourishment**: 3/10 (low)
- **Movement**: 6/10
- **Calm**: 8/10`,
  schedule: `## Check-in schedule
- **Morning meds** — target 08:30 — taken
- **Hydrate** — target 10:30 — done
- **Lunch + meds** — target 12:30 — upcoming
- **Afternoon reset** — target 15:00 — upcoming
- **Movement break** — target 16:30 — upcoming
- **Evening wind-down** — target 21:00 — upcoming
- **Night meds** — target 22:30 — upcoming`,
};

const DATA = { tasks: { active: [], completed: [], blocked: [] }, state: 'baseline', buffers: [], schedule: [] };

/* ----------------------------- CLOCK ----------------------------- */
const DOW = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function tickClock() {
  const n = new Date();
  const p = (x) => String(x).padStart(2, '0');
  document.getElementById('t-hm').textContent = `${p(n.getHours())}:${p(n.getMinutes())}`;
  document.getElementById('t-s').textContent = p(n.getSeconds());
  document.getElementById('t-date').textContent = `${DOW[n.getDay()]} · ${n.getDate()} ${MON[n.getMonth()]}`;
}

/* --------------------------- RENDERING --------------------------- */
const PRIO_CLASS = { high: 'prio--high', med: 'prio--med', medium: 'prio--med', low: 'prio--low' };

function fmtDue(due) {
  if (!due) return '';
  const today = new Date();
  const sameDay = due.date === today.toISOString().slice(0, 10);
  const label = sameDay ? 'today' : due.date.slice(5).replace('-', '/');
  return due.time ? `${label} · ${due.time}` : label;
}

/* split a string into per-word / per-char spans for the rise animation */
function staggerize(text) {
  const words = text.split(' ');
  let i = 0;
  return words.map((w) => {
    const chars = [...w].map((c) => {
      const sp = `<span class="c" style="animation-delay:${(i * 28)}ms">${c}</span>`;
      i++; return sp;
    }).join('');
    return `<span class="w">${chars}</span>`;
  }).join('<span class="c" style="opacity:1">&nbsp;</span>');
}

/* ---- PAGE 0: tasks ---- */
let heroIdx = 0; let heroTimer = null;
function renderTasks() {
  const t = DATA.tasks;
  // ledger
  const item = (task, cls, glyph) =>
    `<div class="ledger__item ${cls}"><span class="gl">${glyph}</span>
       <span class="tx">${task.title}${task.hint ? ` <span class="hint">· ${task.hint}</span>` : ''}</span></div>`;

  const activeHtml = t.active.map((x, i) => `<div class="ledger__item ${i === heroIdx ? 'is-current' : ''}"><span class="gl">◆</span><span class="tx">${x.title}</span></div>`).join('');
  const doneHtml = t.completed.map((x) => item(x, 'done', '✓')).join('');
  const blockedHtml = t.blocked.map((x) => item(x, 'blocked', '⊘')).join('');

  document.getElementById('ledger').innerHTML = `
    <div class="ledger__col ledger__col--wide">
      <div class="ledger__h">Active <span class="n">${t.active.length}</span></div>
      ${activeHtml || '<div class="ledger__item"><span class="tx" style="color:var(--ink-faint)">— nothing pressing —</span></div>'}
    </div>
    <div class="ledger__col">
      <div class="ledger__h">Done Today <span class="n">${t.completed.length}</span></div>
      ${doneHtml || '<div class="ledger__item"><span class="tx" style="color:var(--ink-faint)">—</span></div>'}
    </div>
    <div class="ledger__col">
      <div class="ledger__h">Blocked <span class="n">${t.blocked.length}</span></div>
      ${blockedHtml || '<div class="ledger__item"><span class="tx" style="color:var(--ink-faint)">—</span></div>'}
    </div>`;

  // hero count pips
  const pips = t.active.map((_, i) => `<i class="${i === heroIdx ? 'on' : ''}"></i>`).join('');
  document.getElementById('hero-count').innerHTML = pips;

  renderHero();
}

function renderHero(animate = true) {
  const t = DATA.tasks;
  const hero = document.getElementById('hero');
  if (!t.active.length) {
    document.getElementById('hero-title').textContent = 'All clear';
    document.getElementById('hero-meta').innerHTML = '';
    return;
  }
  if (heroIdx >= t.active.length) heroIdx = 0;
  const task = t.active[heroIdx];

  const paint = () => {
    document.getElementById('hero-title').innerHTML = staggerize(task.title);
    const prioCls = PRIO_CLASS[task.prio] || 'prio--med';
    const prioLabel = task.prio ? task.prio.toUpperCase() : '';
    document.getElementById('hero-meta').innerHTML =
      (prioLabel ? `<span class="prio ${prioCls}"><span class="prio__dot"></span>${prioLabel}</span>` : '') +
      (task.due ? `<span class="hero__due">due <b>${fmtDue(task.due)}</b></span>` : '');
    hero.classList.remove('is-leaving'); hero.classList.add('is-entering');
    // refresh ledger highlight + pips
    document.querySelectorAll('#ledger .ledger__col--wide .ledger__item').forEach((el, i) => el.classList.toggle('is-current', i === heroIdx));
    document.querySelectorAll('#hero-count i').forEach((el, i) => el.classList.toggle('on', i === heroIdx));
    setTimeout(() => { hero.classList.remove('is-entering'); hero.classList.add('settled'); }, 1100);
  };

  if (animate) {
    hero.classList.remove('is-entering', 'settled'); hero.classList.add('is-leaving');
    setTimeout(paint, 600);
  } else { paint(); }
}

function startHeroRotation() {
  clearInterval(heroTimer);
  heroTimer = setInterval(() => {
    if (currentPage !== 0) return;            // only advance while visible
    if (DATA.tasks.active.length < 2) return;
    heroIdx = (heroIdx + 1) % DATA.tasks.active.length;
    renderHero(true);
  }, 6800);
}

/* ---- PAGE 1: state + buffers ---- */
const BUF_COLORS = ['#8ab4f8', '#70ffb2', '#e6c781', '#ff9f70', '#b07cd6', '#9fb3c8', '#7fd6c0', '#d68fb0'];
function renderState() {
  const st = STATES[DATA.state] || STATES.baseline;
  const root = document.getElementById('weather');
  root.style.setProperty('--state-c', st.color);
  document.getElementById('state-glyph').innerHTML = STATE_GLYPH[DATA.state] || STATE_GLYPH.baseline;
  document.getElementById('state-name').textContent = st.word;
  document.getElementById('state-desc').textContent = st.desc;
  document.getElementById('state-key').textContent = DATA.state;

  const wrap = document.getElementById('buffers');
  wrap.innerHTML = DATA.buffers.map((b, i) => {
    const c = b.low ? 'var(--empathy)' : BUF_COLORS[i % BUF_COLORS.length];
    const pct = Math.max(0, Math.min(100, (b.level / b.cap) * 100));
    const pips = Array.from({ length: b.cap }, () => '<i></i>').join('');
    return `<div class="buffer" style="--buf-c:${c}">
      <div class="buffer__row">
        <div class="buffer__name">${b.name}${b.low ? '<span class="buffer__tag">low</span>' : ''}</div>
        <div class="buffer__val"><b>${b.level}</b> / ${b.cap}</div>
      </div>
      <div class="buffer__track">
        <div class="buffer__fill" style="width:${pct}%"></div>
        <div class="buffer__pips">${pips}</div>
      </div>
    </div>`;
  }).join('');
}

/* ---- PAGE 2: schedule ---- */
function nowMinutes() { const n = new Date(); return n.getHours() * 60 + n.getMinutes(); }
function toMin(hhmm) { const [h, m] = (hhmm || '0:0').split(':').map(Number); return h * 60 + m; }
function renderSchedule() {
  const list = DATA.schedule;
  const wrap = document.getElementById('hours');
  const nm = nowMinutes();
  const nextIdx = list.findIndex((c) => toMin(c.time) >= nm && !/done|taken|kept/i.test(c.status));

  wrap.innerHTML = list.map((c, i) => {
      const past = toMin(c.time) < nm;
      let cls = '';
      if (/done|taken|kept/i.test(c.status)) cls = 'done';
      else if (i === nextIdx) cls = 'next';
      else if (past) cls = 'missed';
      const hint = c.hint && c.hint.toLowerCase() !== c.time
        ? `<span class="vigil__hint">${c.hint}</span>` : '';
      return `<div class="vigil ${cls}" data-min="${toMin(c.time)}">
        <div class="vigil__node"><div class="vigil__dot"></div></div>
        <div class="vigil__body">
          <div class="vigil__text"><div class="vigil__name">${c.name}</div>${hint}</div>
          <div class="vigil__when">${c.time}</div>
        </div></div>`;
    }).join('');
}

/* --------------------------- CAROUSEL ---------------------------- */
let currentPage = 0; let carouselTimer = null; let tickRAF = null; let tickStart = 0;
const PAGE_MS = 20000;          // audit: 20s per page
const NPAGES = 3;

function showPage(i, fromUser) {
  currentPage = ((i % NPAGES) + NPAGES) % NPAGES;
  document.querySelectorAll('.leaf').forEach((el, idx) => el.classList.toggle('is-active', idx === currentPage));
  document.querySelectorAll('.dot').forEach((el, idx) => el.classList.toggle('is-active', idx === currentPage));
  if (currentPage === 0) { renderHero(true); }
  if (currentPage === 1) renderState();
  if (currentPage === 2) renderSchedule();
  restartTick();
  if (fromUser) restartCarousel();
}
function restartCarousel() {
  clearInterval(carouselTimer);
  carouselTimer = setInterval(() => showPage(currentPage + 1), PAGE_MS);
}
function restartTick() {
  cancelAnimationFrame(tickRAF);
  tickStart = performance.now();
  const bar = document.getElementById('tick-bar');
  const step = (now) => {
    const f = Math.min(1, (now - tickStart) / PAGE_MS);
    bar.style.width = (f * 100) + '%';
    if (f < 1) tickRAF = requestAnimationFrame(step);
  };
  tickRAF = requestAnimationFrame(step);
}

/* ------------------------- DATA REFRESH -------------------------- */
function applyData(tasksMd, stateMd, schedMd) {
  DATA.tasks = parseTasks(tasksMd);
  const sb = parseStateBuffers(stateMd);
  DATA.state = sb.state; DATA.buffers = sb.buffers;
  DATA.schedule = parseSchedule(schedMd);
  if (heroIdx >= DATA.tasks.active.length) heroIdx = 0;
  renderTasks();
  if (currentPage === 1) renderState();
  if (currentPage === 2) renderSchedule();
}
async function refresh() {
  const [tk, sb, sc, vo, ev] = await Promise.all([
    fetchFeed(FEED_CONFIG.tasks), fetchFeed(FEED_CONFIG.state), fetchFeed(FEED_CONFIG.schedule),
    fetchFeed(FEED_CONFIG.voices), fetchFeed(FEED_CONFIG.calendar),
  ]);
  applyData(tk || FALLBACK.tasks, sb || FALLBACK.state, sc || FALLBACK.schedule);
  // OPTIONAL feeds: only override the built-ins when the app actually serves them.
  if (vo) window.FX.setVoices(parseVoices(vo));
  if (ev) window.FX.setEvents(parseEvents(ev));
}

/* ---- polled alert queue (feeds/alerts.json) ----
   The Cabinet is static, so the backend can't push: it appends overlay
   envelopes {id, type, payload} to alerts.json and we poll, firing each new
   id once. On the first poll we seed _lastAlertId to the current max WITHOUT
   firing, so a page reload never replays the stored backlog. */
let _lastAlertId = null;
async function pollAlerts() {
  const txt = await fetchFeed(FEED_CONFIG.alerts);
  if (!txt) return;
  let data;
  try { data = JSON.parse(txt); } catch (e) { return; }
  const alerts = (data && data.alerts) || [];
  if (_lastAlertId === null) {            // seed, don't replay backlog on load
    _lastAlertId = alerts.reduce((m, a) => Math.max(m, a.id || 0), 0);
    return;
  }
  alerts.filter((a) => (a.id || 0) > _lastAlertId)
    .sort((a, b) => a.id - b.id)
    .forEach((a) => {
      window.FX.fireAlert(a.type, a.payload || {});
      if (a.id > _lastAlertId) _lastAlertId = a.id;
    });
}

/* ----------------------------- SCALE ----------------------------- */
function fitStage() {
  const stage = document.getElementById('stage');
  const sw = window.innerWidth / 1280, sh = window.innerHeight / 800;
  stage.style.transform = `scale(${Math.min(sw, sh)})`;
}

/* ------------------------------ BOOT ----------------------------- */
function boot() {
  fitStage(); window.addEventListener('resize', fitStage);
  tickClock(); setInterval(tickClock, 1000);

  // dots
  document.querySelectorAll('.dot').forEach((d) => d.addEventListener('click', () => showPage(+d.dataset.p, true)));
  // calendar
  document.getElementById('invoke').addEventListener('click', window.FX.openCalendar);
  document.getElementById('cal-close').addEventListener('click', window.FX.closeCalendar);
  document.getElementById('cal').addEventListener('click', (e) => { if (e.target.id === 'cal') window.FX.closeCalendar(); });

  refresh().then(() => {
    showPage(0);
    startHeroRotation();
    restartCarousel();
    window.FX.startVoices(() => DATA);
  });
  setInterval(refresh, FEED_CONFIG.pollMs);
  setInterval(() => { if (currentPage === 2) renderSchedule(); }, 60000); // keep 'now' fresh
  pollAlerts();                                       // seed _lastAlertId (no replay)
  setInterval(pollAlerts, FEED_CONFIG.alertPollMs);   // then fire new overlays

  /* ---- public API: window.MM.fireAlert(type, {title, message, foot}) ---- */
  window.MM = {
    fireAlert: window.FX.fireAlert,
    setVoices: window.FX.setVoices,
    setEvents: window.FX.setEvents,
    refresh,
    goTo: (i) => showPage(i, true),
  };
  // also accept alerts via postMessage (LAN bridge convenience)
  window.addEventListener('message', (e) => {
    const d = e.data || {};
    if (d && d.mmAlert && d.type) window.FX.fireAlert(d.type, d.payload || {});
  });

  /* ---- preview-only conveniences (no effect in production webhook path) ---- */
  window.addEventListener('keydown', (e) => {
    if (e.key === '1') window.FX.demoAlert('state_change', DATA);
    if (e.key === '2') window.FX.demoAlert('buffer_alert', DATA);
    if (e.key === '3') window.FX.demoAlert('missed_checkin', DATA);
    if (e.key.toLowerCase() === 'c') window.FX.openCalendar();
    if (e.key === 'ArrowRight') showPage(currentPage + 1, true);
    if (e.key === 'ArrowLeft') showPage(currentPage - 1, true);
  });
}

document.addEventListener('DOMContentLoaded', boot);
