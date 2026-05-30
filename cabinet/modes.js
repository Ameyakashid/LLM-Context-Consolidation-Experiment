/* =====================================================================
   modes.js — full-screen mode switching + News, Wallpaper, Flashcards.
   Each rail button swaps the entire screen. Dashboard lives in display.js.
   ===================================================================== */
(function () {
  const fetchFeed = window.FeedKit.fetchFeed;

  /* --------------------------- MODE SWITCHER --------------------------- */
  const MODES = ['dashboard', 'news', 'wallpaper', 'flashcards'];
  const CREST = { dashboard: 'The Cabinet', news: 'The Gazette', wallpaper: 'The Cabinet', flashcards: 'The Codex' };
  let activeMode = 'dashboard';

  function setMode(name) {
    if (!MODES.includes(name)) return;
    activeMode = name;
    MODES.forEach((m) => {
      document.getElementById('mode-' + m).classList.toggle('is-active', m === name);
    });
    document.querySelectorAll('.rail__btn').forEach((b) => b.classList.toggle('is-active', b.dataset.mode === name));
    const crest = document.getElementById('crest-label'); if (crest) crest.textContent = CREST[name];

    // lifecycle
    News.setActive(name === 'news');
    Wall.setActive(name === 'wallpaper');
    if (name === 'flashcards') Cards.ensure();
  }

  /* ============================ NEWS ============================ */
  const News = (() => {
    let loaded = false, scroller = null, autoId = null, dir = 1;

    function parse(md) {
      return (md || '').split(/\n(?=##\s)/).map((b) => {
        const m = b.match(/^##\s+(.+)/); if (!m) return null;
        const head = m[1].trim();
        const rest = b.slice(b.indexOf('\n') + 1);
        const metaM = rest.match(/\*(.+?)\*/);
        const meta = metaM ? metaM[1].trim() : '';
        const body = rest.replace(/^\s*\*.+?\*\s*$/m, '').replace(/\s*\n\s*/g, ' ').trim();
        return { head, meta, body };
      }).filter(Boolean);
    }

    function render(items) {
      const wrap = document.getElementById('news-scroll');
      wrap.innerHTML = items.map((a, i) => `
        <article class="article ${i === 0 ? 'article--lead' : ''}">
          ${a.meta ? `<div class="article__kicker">${a.meta}</div>` : ''}
          <div class="article__head">${a.head}</div>
          <div class="article__body">${a.body}</div>
        </article>`).join('') || '<div class="article__body">No dispatches at this hour.</div>';
      scroller = wrap;
    }

    async function load() {
      const md = await fetchFeed('feeds/news.md');
      render(parse(md || FALLBACK_NEWS));
      loaded = true;
    }

    function tick() {
      if (!scroller) return;
      const max = scroller.scrollHeight - scroller.clientHeight;
      if (max <= 2) return;
      scroller.scrollTop += 0.4 * dir;
      if (scroller.scrollTop >= max - 0.5) dir = -1;
      else if (scroller.scrollTop <= 0.5) dir = 1;
    }

    function setActive(on) {
      if (on) {
        if (!loaded) load();
        clearInterval(autoId);
        autoId = setInterval(tick, 32);
      } else {
        clearInterval(autoId); autoId = null;
      }
    }
    return { setActive };
  })();

  /* ============================ WALLPAPER ============================ */
  const Wall = (() => {
    let list = [], layers = [], idx = 0, slot = 0, rotId = null, loaded = false, intervalMs = 30000;

    async function load() {
      let data = null;
      try {
        const r = await fetch('wallpapers/manifest.json?t=' + Date.now(), { cache: 'no-store' });
        if (r.ok) data = await r.json();
      } catch (e) { /* fall through */ }
      list = (data && data.wallpapers) ? data.wallpapers.slice() : FALLBACK_WALLS;
      if (data && data.intervalMs) intervalMs = data.intervalMs;

      const wall = document.getElementById('wall');
      wall.innerHTML = '';
      layers = [document.createElement('div'), document.createElement('div')];
      layers.forEach((l) => { l.className = 'wall__layer'; wall.appendChild(l); });

      // dots
      document.getElementById('wall-dots').innerHTML = list.map(() => '<i></i>').join('');
      loaded = true;
      show(0, true);
    }

    function path(w) { return 'wallpapers/' + w.file; }

    function show(i, instant) {
      if (!list.length) return;
      idx = ((i % list.length) + list.length) % list.length;
      const w = list[idx];
      const next = layers[slot ^ 1], cur = layers[slot];
      if (w.css) { next.style.background = w.css; next.style.backgroundImage = ''; }
      else { next.style.backgroundImage = `url("${path(w)}")`; }
      requestAnimationFrame(() => {
        next.classList.add('is-on');
        cur.classList.remove('is-on');
        slot ^= 1;
      });
      document.getElementById('wall-title').textContent = w.title || '';
      document.querySelectorAll('#wall-dots i').forEach((d, k) => d.classList.toggle('on', k === idx));
    }

    function setActive(on) {
      if (on) {
        if (!loaded) load();
        clearInterval(rotId);
        rotId = setInterval(() => show(idx + 1), intervalMs);
      } else {
        clearInterval(rotId); rotId = null;
      }
    }
    return { setActive };
  })();

  /* ============================ FLASHCARDS ============================ */
  const Cards = (() => {
    let built = false, filter = 'All', pool = [], i = 0;
    let all = window.FLASHCARDS || [];          // replaced by backend pool on refresh
    const SAMPLE_N = 40;                          // cards drawn per "new set"

    function shuffle(arr) {
      const a = arr.slice();
      for (let k = a.length - 1; k > 0; k--) { const j = (Math.random() * (k + 1)) | 0; [a[k], a[j]] = [a[j], a[k]]; }
      return a;
    }

    /* Draw a fresh random ~SAMPLE_N from the backend pool (feeds/flashcards.json),
       falling back to the built-in static deck. Read-only-safe: the sampling is
       all client-side; the backend just keeps the pool fresh. */
    async function resampleDeck() {
      const txt = await fetchFeed('feeds/flashcards.json');
      let source = null;
      if (txt) { try { const d = JSON.parse(txt); if (d && Array.isArray(d.cards) && d.cards.length) source = d.cards; } catch (e) { /* keep deck */ } }
      if (!source) source = window.FLASHCARDS || all;
      if (source && source.length) all = shuffle(source).slice(0, SAMPLE_N);
      applyFilter('All');
    }

    function cats() {
      const seen = []; all.forEach((c) => { if (!seen.includes(c.cat)) seen.push(c.cat); });
      return ['All', ...seen];
    }
    function applyFilter(f) {
      filter = f;
      pool = (f === 'All') ? all.slice() : all.filter((c) => c.cat === f);
      i = 0; paint(); paintCats();
    }
    function paintCats() {
      document.getElementById('cards-cats').innerHTML = cats().map((c) =>
        `<button class="cat-chip ${c === filter ? 'is-active' : ''}" data-cat="${c}">${c}</button>`).join('');
    }
    function paint() {
      const card = pool[i] || { cat: '—', front: 'No cards', back: '—' };
      document.getElementById('flip').classList.remove('is-flipped');
      // delay back content swap until flip resets, so it doesn't flash
      const front = document.getElementById('card-front');
      const back = document.getElementById('card-back');
      front.innerHTML = `<div class="card__cat">${card.cat}</div><div class="card__q">${card.front}</div><div class="card__hint">turn to reveal</div>`;
      back.innerHTML = `<div class="card__cat">${card.cat}</div><div class="card__a">${card.back}</div><div class="card__hint">turn back</div>`;
      document.getElementById('cards-counter').textContent = `${pool.length ? i + 1 : 0} / ${pool.length}`;
    }
    function flip() { document.getElementById('flip').classList.toggle('is-flipped'); }
    function go(d) { if (!pool.length) return; i = (i + d + pool.length) % pool.length; paint(); }

    function ensure() {
      if (built) return;
      applyFilter('All');          // show the static deck immediately…
      resampleDeck();              // …then swap in a fresh pool sample (async)
      document.getElementById('flip').addEventListener('click', flip);
      document.getElementById('card-prev').addEventListener('click', (e) => { e.stopPropagation(); go(-1); });
      document.getElementById('card-next').addEventListener('click', (e) => { e.stopPropagation(); go(1); });
      document.getElementById('cards-cats').addEventListener('click', (e) => {
        const b = e.target.closest('.cat-chip'); if (b) applyFilter(b.dataset.cat);
      });
      const refresh = document.getElementById('cards-refresh');
      if (refresh) refresh.addEventListener('click', resampleDeck);
      built = true;
    }
    return { ensure, flip, go: (d) => go(d), refresh: resampleDeck };
  })();

  /* ============================ FALLBACKS ============================ */
  /* Painterly CSS wallpapers — shown when the wallpapers/ folder is empty
     or unreachable. On the device, manifest.json + real image files win. */
  const FALLBACK_WALLS = [
    { title: 'Nightfall over the Observatory', css:
      'radial-gradient(80% 70% at 28% 24%, #16384a 0%, transparent 55%),' +
      'radial-gradient(90% 80% at 78% 82%, #1b1a3a 0%, transparent 60%),' +
      'radial-gradient(50% 40% at 84% 16%, rgba(230,199,129,0.45) 0%, transparent 60%),' +
      'linear-gradient(160deg, #0a1622, #05080c)' },
    { title: 'Emberfall', css:
      'radial-gradient(80% 80% at 40% 88%, #3a1d10 0%, transparent 58%),' +
      'radial-gradient(70% 60% at 72% 26%, #5c2a14 0%, transparent 55%),' +
      'radial-gradient(40% 30% at 50% 96%, rgba(255,159,112,0.28) 0%, transparent 60%),' +
      'linear-gradient(160deg, #160d0a, #070403)' },
    { title: 'The Verdant Hour', css:
      'radial-gradient(80% 70% at 32% 44%, #0f3324 0%, transparent 56%),' +
      'radial-gradient(80% 70% at 78% 78%, #0c2a1c 0%, transparent 60%),' +
      'radial-gradient(40% 30% at 58% 56%, rgba(112,255,178,0.16) 0%, transparent 60%),' +
      'linear-gradient(160deg, #08160f, #040806)' },
    { title: 'Vellum & Sigil', css:
      'radial-gradient(70% 70% at 50% 50%, #2a2212 0%, transparent 60%),' +
      'radial-gradient(60% 50% at 24% 80%, #1a160c 0%, transparent 60%),' +
      'linear-gradient(160deg, #14110a, #080705)' },
  ];
  const FALLBACK_NEWS = `## Local observatory reopens after a decade dark
*The Cabinet Gazette · Science · 2h ago*
The hillside observatory has admitted its first visitors in ten years following a quiet restoration of its century-old refractor. Volunteers spent three winters regrinding the lens by hand. Evening viewing slots are released at dusk and fill within the hour.

## Transit authority trials a slower, kinder timetable
*City Desk · 4h ago*
A pilot on the eastern line adds ninety seconds of dwell time at major stops, a change planners say reduces the cascade of missed connections. Early riders report calmer platforms.

## Archivists finish digitising the harbour ledgers
*Culture · 6h ago*
Two hundred years of shipping records are now searchable online, from cargo manifests to the weather notes captains scribbled in the margins. Historians expect the marginalia to draw the most attention.

## A quiet record for the city's community gardens
*Environment · yesterday*
Plot registrations passed four thousand this spring, the highest on record. Coordinators credit a seed-library scheme that lets growers borrow and return varieties season to season.

## Library extends its late hours through winter
*City Desk · yesterday*
Responding to steady evening demand, the central library will stay open until ten on weeknights. The reading room's green lamps stay lit for those who want somewhere warm and silent.

## Tideline cleanup recovers more glass than plastic
*Environment · 2 days ago*
This month's shoreline survey logged an unusual haul: sea-worn glass outnumbered plastic fragments for the first time in the count's history.`;

  /* ============================ WIRE-UP ============================ */
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.rail__btn').forEach((b) =>
      b.addEventListener('click', () => setMode(b.dataset.mode)));
    document.querySelector('.rail__btn[data-mode="dashboard"]').classList.add('is-active');

    // expose for integration + preview
    window.MM = window.MM || {};
    window.MM.setMode = setMode;

    window.addEventListener('keydown', (e) => {
      const k = e.key.toLowerCase();
      if (k === 'd') setMode('dashboard');
      if (k === 'n') setMode('news');
      if (k === 'w') setMode('wallpaper');
      if (k === 'f') setMode('flashcards');
      if (activeMode === 'flashcards') {
        if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); Cards.flip(); }
        if (e.key === 'ArrowRight') Cards.go(1);
        if (e.key === 'ArrowLeft') Cards.go(-1);
      }
    });
  });
})();
