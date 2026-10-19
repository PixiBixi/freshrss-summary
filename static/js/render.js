// ── Icons (inline SVG on a 16px grid, no emoji) ────────────────────────
const ICONS = {
  tri: '<path d="M2 4h12M4 8h8M6 12h4"/>',
  bm: '<path d="M4 2h8v12l-4-3-4 3z"/>',
  bmf: '<path d="M4 2h8v12l-4-3-4 3z" fill="currentColor"/>',
  sn: '<circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 2"/>',
  ok: '<path d="M3 8.5l3 3 7-7"/>',
  undo: '<path d="M5 6H10a3 3 0 010 6H7M5 6l2.5-2.5M5 6l2.5 2.5"/>',
  side: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M6 3v10"/>',
  pane: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M9.5 3v10"/>',
  more: '<circle cx="3.5" cy="8" r="1" fill="currentColor"/><circle cx="8" cy="8" r="1" fill="currentColor"/><circle cx="12.5" cy="8" r="1" fill="currentColor"/>',
  sync: '<path d="M13 8a5 5 0 01-8.6 3.5M3 8a5 5 0 018.6-3.5M12 2v3h-3M4 14v-3h3"/>',
  search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>',
  x: '<path d="M4 4l8 8M12 4l-8 8"/>',
  up: '<path d="M4 10l4-4 4 4"/>',
  down: '<path d="M4 6l4 4 4-4"/>',
  ext: '<path d="M9 3h4v4M13 3L7 9M11 9v4H3V5h4"/>',
  cmd: '<path d="M6 4a2 2 0 10-2 2h8a2 2 0 10-2-2v8a2 2 0 102-2H4a2 2 0 102 2z"/>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  key: '<circle cx="5.5" cy="10.5" r="2.5"/><path d="M7.5 8.5L13 3M11 5l1.5 1.5"/>',
  out: '<path d="M6 3H3v10h3M10 5l3 3-3 3M13 8H6"/>',
  sliders: '<path d="M3 4h10M3 8h10M3 12h10"/><circle cx="6" cy="4" r="1.5" fill="var(--surface)"/><circle cx="10" cy="8" r="1.5" fill="var(--surface)"/><circle cx="5" cy="12" r="1.5" fill="var(--surface)"/>',
  redo: '<path d="M3 8a5 5 0 109-3M12 2v3h-3"/>',
  kb: '<rect x="1.5" y="4" width="13" height="8" rx="1.5"/><path d="M4 7h1M7 7h1M10 7h2M4 9.5h8"/>',
};

function ic(name, cls = '') {
  return `<svg class="i ${cls}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

function byId(id) { return document.getElementById(id); }

function rowEl(id) { return document.querySelector(`.row[data-id="${CSS.escape(id)}"]`); }

// ── Formatting ─────────────────────────────────────────────────────────
const SEV_LABEL = { crit: 'P1', warn: 'P2', ok: 'P3' };

function sevOf(score) { return score >= SEV_P1_MIN ? 'crit' : score >= SEV_P2_MIN ? 'warn' : 'ok'; }

// Two decimals under 1x: most real scores sit well below one burn unit.
function burn(score) {
  const v = (score || 0) / BURN_DIVISOR;
  return (v > 0 && v < 1 ? v.toFixed(2) : v.toFixed(1)) + '×';
}

function _locale() { return LANGS.find(l => l.code === state.lang)?.locale || 'fr-FR'; }

function fmtAgo(ts) {
  if (!ts) return '';
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60)    return t('time.now');
  if (diff < 3600)  return t('time.min', { n: Math.floor(diff / 60) });
  if (diff < 86400) return t('time.h',   { n: Math.floor(diff / 3600) });
  return t('time.d', { n: Math.floor(diff / 86400) });
}

function fmtAge(ts) {
  if (!ts) return '';
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 3600)  return diff < 60 ? t('age.now') : t('age.m', { n: Math.floor(diff / 60) });
  if (diff < 86400) return t('age.h', { n: Math.floor(diff / 3600) });
  return t('age.d', { n: Math.floor(diff / 86400) });
}

function fmtWhen(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString(_locale(), { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function dayKey(ts) { const d = new Date((ts || 0) * 1000); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; }

function dayLabel(ts) {
  const now = new Date();
  const k = dayKey(ts);
  if (k === dayKey(now / 1000)) return t('date.today');
  if (k === dayKey(now / 1000 - 86400)) return t('date.yesterday');
  return new Date((ts || 0) * 1000).toLocaleDateString(_locale(), { weekday: 'long', day: 'numeric', month: 'long' });
}

// ── Views and filters ──────────────────────────────────────────────────
function isAcked(a) { return !!a._read || _markedIds.has(a.id); }

function inView(a, v = state.view) {
  if (v === 'triage') return (!isAcked(a) || state.keep.has(a.id)) && !state.snoozes.has(a.id);
  if (v === 'bm') return !!a.bookmarked;
  if (v === 'read') return isAcked(a) && !state.keep.has(a.id);
  return false;
}

// Snoozed articles that left the cache (read upstream) still list, from the snooze row.
function snoozedArticles() {
  const byIdMap = new Map(state.articles.map(a => [a.id, a]));
  return [...state.snoozes.values()].map(s => byIdMap.get(s.article_id) || {
    id: s.article_id, title: s.title || s.article_id, url: s.url, feed_title: '', published: 0, score: 0,
    matched_topics: {}, matched_keywords: [], top_topic: null, summary: '', _stub: true,
  });
}

function topTopic(a) {
  if (a.top_topic) return a.top_topic;
  const e = Object.entries(a.matched_topics || {});
  return e.length ? e.reduce((m, x) => (x[1] > m[1] ? x : m))[0] : '';
}

function _searchText(a) {
  if (a._q === undefined) {
    a._q = [a.title, a.feed_title, (a.matched_keywords || []).join(' '), topTopic(a)].join(' ').toLowerCase();
  }
  return a._q;
}

const SORTS = {
  burn: a => a.score,
  title: a => (a.title || '').toLowerCase(),
  topic: a => topTopic(a).toLowerCase(),
  feed: a => (a.feed_title || '').toLowerCase(),
  age: a => a.published || 0,
};

function isFiltered() { return !!(state.topic || state.search || state.minScore || state.sev); }

// Recomputed once per render: `base` ignores the severity filter (summary counts).
const _view = { base: [], list: [] };

function recompute() {
  const src = state.view === 'sn' ? snoozedArticles() : state.articles.filter(a => inView(a));
  const q = state.search.toLowerCase();
  const key = SORTS[state.sortKey] || SORTS.burn, dir = state.sortDir;
  _view.base = src.filter(a =>
    (!state.topic || state.topic in (a.matched_topics || {}))
    && a.score >= state.minScore
    && (!q || _searchText(a).includes(q)))
    .sort((x, y) => { const a = key(x), b = key(y); if (a < b) return -dir; if (a > b) return dir; return y.score - x.score; });
  _view.list = state.sev ? _view.base.filter(a => sevOf(a.score) === state.sev) : _view.base;
  const n = Math.min(state.shown, _view.list.length);
  if (state.sel >= n) state.sel = Math.max(0, n - 1);
}

function visibleList() { return _view.list.slice(0, state.shown); }

function currentArticle() { const l = visibleList(); return l[Math.min(state.sel, l.length - 1)] || null; }

function topicCounts() {
  const m = new Map();
  for (const name of state.allTopics) m.set(name, 0);
  for (const a of state.articles) {
    if (!inView(a, 'triage') || state.keep.has(a.id)) continue;
    for (const k of Object.keys(a.matched_topics || {})) m.set(k, (m.get(k) || 0) + 1);
  }
  return [...m.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]));
}

function navCount(v) {
  if (!state.everLoaded) return '';
  if (v === 'sn') return state.snoozes.size;
  if (v === 'read' && state.view !== 'read') return '';
  let n = 0;
  for (const a of state.articles) if (inView(a, v)) n++;
  return v === 'triage' ? n - [...state.keep].filter(id => !state.snoozes.has(id)).length : n;
}

const VIEW_LABEL = { triage: 'nav.triage', bm: 'nav.bookmarks', sn: 'nav.snoozed', read: 'nav.read' };

// ── Sidebar ────────────────────────────────────────────────────────────
function renderSidebar() {
  const nav = [['triage', 'tri'], ['bm', 'bm'], ['sn', 'sn'], ['read', 'ok']];
  const items = state.authenticated ? nav : [nav[0], nav[3]];
  byId('nav').innerHTML = items.map(([v, i]) => {
    const dis = !state.authenticated && v === 'read';
    return `<button type="button" data-view="${v}"${state.view === v ? ' aria-current="page"' : ''}${dis ? ` disabled title="${esc(t('nav.loginRequired'))}"` : ''}>`
      + `${ic(i)}<span>${esc(t(VIEW_LABEL[v]))}</span><span class="cnt">${dis ? '' : navCount(v)}</span></button>`;
  }).join('');

  byId('topic-list').innerHTML = topicCounts().map(([name, n]) =>
    `<button type="button" data-topic="${esc(name)}" aria-pressed="${state.topic === name}"><span class="sw" aria-hidden="true"></span><span class="nm">${esc(name)}</span><span class="cnt">${state.everLoaded ? n : ''}</span></button>`
  ).join('');

  const slider = byId('min-score');
  if (document.activeElement !== slider) slider.value = state.minScore;
  byId('min-val').textContent = burn(state.minScore);
  document.querySelectorAll('#days-seg [data-days]').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.days === state.days)));

  byId('user-block').innerHTML = state.authenticated
    ? `<span class="av" aria-hidden="true">${esc((window._USER || '?').slice(0, 1).toUpperCase())}</span><span class="un">${esc(window._USER || '')}</span>`
    : `<span class="av" aria-hidden="true">?</span><span class="un">${esc(t('user.anon'))}</span><span class="ro">${esc(t('user.readonly'))}</span>`;
}

// ── Toolbar ────────────────────────────────────────────────────────────
function renderToolbar() {
  const l = _view.list;
  byId('view-title').textContent = state.view === 'triage' ? (state.topic || t('nav.triage')) : t(VIEW_LABEL[state.view]);
  byId('view-count').textContent = state.everLoaded ? l.length : '';

  const ack = byId('ack-visible');
  const showAck = state.authenticated && state.view === 'triage' && isFiltered() && l.length > 0;
  ack.hidden = !showAck;
  if (showAck) ack.innerHTML = ic('ok') + esc(t('btn.ackN', { n: Math.min(l.length, state.shown) }));

  const q = byId('q');
  if (document.activeElement !== q && q.value !== state.search) q.value = state.search;
  byId('q-clear').hidden = !state.search;
  byId('q-kbd').hidden = !!state.search;

  const dens = document.documentElement.dataset.density;
  document.querySelectorAll('[data-dens]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.dens === dens)));
  byId('pin-btn').setAttribute('aria-pressed', String(state.pin));
  byId('collapse-btn').setAttribute('aria-pressed', String(!state.collapse));

  const sync = byId('sync-btn');
  sync.disabled = state.syncing;
  sync.innerHTML = state.syncing
    ? `<span class="spin" aria-hidden="true"></span>${esc(t('btn.syncing'))}`
    : `${ic('sync')}${esc(t('btn.sync'))} <kbd class="kbd-t">r</kbd>`;
}

// ── Summary bar ────────────────────────────────────────────────────────
function renderSummary() {
  const c = { crit: 0, warn: 0, ok: 0 };
  for (const a of _view.base) c[sevOf(a.score)]++;
  const tot = c.crit + c.warn + c.ok || 1, all = _view.list.length;
  const sb = k => `<button type="button" class="sevf" data-sev="${k}" aria-pressed="${state.sev === k}"><b class="${k}">${c[k]}</b> ${SEV_LABEL[k]}</button>`;
  const sg = k => `<button type="button" data-sev="${k}" aria-label="${esc(t('sum.filterSev', { p: SEV_LABEL[k] }))}" class="${state.sev && state.sev !== k ? 'dim' : ''}" style="flex:${c[k] / tot};background:var(--${k === 'ok' ? 'line' : k})"></button>`;

  const chips = [];
  if (state.topic) chips.push(['topic', state.topic]);
  if (state.minScore) chips.push(['min', '≥ ' + burn(state.minScore)]);
  if (state.search) chips.push(['q', '"' + state.search + '"']);

  const stale = state.lastRefresh && Date.now() / 1000 - state.lastRefresh > 10800;
  const sync = state.lastRefresh
    ? `<span class="${stale ? 'warn' : ''}"${stale ? ` title="${esc(t('stale.title'))}"` : ''}>${esc(t('sum.synced', { ago: fmtAgo(state.lastRefresh) }))}</span>`
    : '';

  byId('sum').innerHTML = sb('crit') + sb('warn') + sb('ok')
    + `<span class="budget">${sg('crit')}${sg('warn')}${sg('ok')}</span>`
    + chips.map(([k, v]) => `<span class="chip">${esc(v)}<button type="button" data-clear="${k}" aria-label="${esc(t('sum.removeFilter', { f: v }))}">${ic('x')}</button></span>`).join('')
    + (isFiltered() ? `<button type="button" class="link" data-cmd="reset">${esc(t('sum.reset'))}</button>` : '')
    + (_readQueue.size ? _rqHtml() : '')
    + `<span class="meta">${esc(t('sum.shown', { n: Math.min(state.shown, all), total: all }))}${sync ? ' · ' : ''}${sync}</span>`;

  const banner = byId('err-banner');
  const err = state.loadError || state.syncError;
  banner.hidden = !err;
  if (err) {
    const retry = state.loadError ? 'reload' : 'sync';
    banner.innerHTML = `<b>${esc(t(state.loadError ? 'err.load' : 'err.sync'))}</b><span>${esc(err)}</span>`
      + (state.loadError || state.authenticated ? `<button type="button" class="btn" data-cmd="${retry}">${ic('redo')}${esc(t('err.retry'))}</button>` : '');
  }
}

function _rqHtml() {
  return `<span class="rq" id="rq"><span class="spin" aria-hidden="true"></span>${esc(t('sum.readQueue', { n: _readQueue.size }))}</span>`;
}

function updateReadQueueBadge() {
  const sum = byId('sum');
  let rq = byId('rq');
  if (!_readQueue.size) { rq?.remove(); return; }
  if (!rq) { sum.querySelector('.meta')?.insertAdjacentHTML('beforebegin', _rqHtml()); return; }
  rq.outerHTML = _rqHtml();
}

function onScrollReadFlushed(ids) {
  for (const id of ids) { const r = rowEl(id); if (r) { r.classList.remove('queued'); r.classList.add('read'); } }
  updateReadQueueBadge();
  const cnt = document.querySelector('#nav [data-view="triage"] .cnt');
  if (cnt) cnt.textContent = navCount('triage');
  state.lastAck = ids;
  toast(t('toast.scrollRead', { n: ids.length }), { action: undoAck, label: t('toast.undoKey') });
}

// ── List ───────────────────────────────────────────────────────────────
function _th(k, labelKey, cls = '') {
  const on = state.sortKey === k;
  const sort = on ? (state.sortDir < 0 ? 'descending' : 'ascending') : 'none';
  return `<button type="button" class="th ${cls}" data-sort="${k}" aria-sort="${sort}">${esc(t(labelKey))}<span class="ar" aria-hidden="true">${on ? (state.sortDir < 0 ? '↓' : '↑') : ''}</span></button>`;
}

function _rowActs(a) {
  if (!state.authenticated || a._stub && state.view !== 'sn') return '';
  let acts;
  if (state.view === 'read') acts = `<button type="button" data-act="unack" data-id="${esc(a.id)}" aria-label="${esc(t('act.unack'))}" title="${esc(t('act.unack'))}">${ic('undo')}</button>`;
  else if (state.view === 'sn') acts = `<button type="button" data-act="wake" data-id="${esc(a.id)}" aria-label="${esc(t('act.wake'))}" title="${esc(t('act.wake'))}">${ic('undo')}</button>`;
  else acts = `<button type="button" data-act="ack" data-id="${esc(a.id)}" aria-label="${esc(t('act.ack'))}" title="${esc(t('act.ack'))} (m)">${ic('ok')}</button>`
    + `<button type="button" data-act="sn" data-id="${esc(a.id)}" aria-label="${esc(t('act.snooze'))}" title="${esc(t('act.snooze'))} (s)">${ic('sn')}</button>`;
  const bm = a._stub ? '' : `<button type="button" data-act="bm" data-id="${esc(a.id)}" aria-pressed="${!!a.bookmarked}" aria-label="${esc(t('act.bookmark'))}" title="${esc(t('act.bookmark'))} (b)">${ic(a.bookmarked ? 'bmf' : 'bm')}</button>`;
  return `<span class="acts">${bm}${acts}</span>`;
}

function _row(a, i, sel) {
  const s = sevOf(a.score);
  const rd = state.view === 'read' || state.keep.has(a.id) ? ' read' : _readQueue.has(a.id) ? ' queued' : '';
  const sn = state.snoozes.get(a.id);
  const ag = state.view === 'sn' && sn
    ? `<span class="ag" title="${esc(t('reader.snoozedUntil', { when: fmtWhen(sn.snooze_until) }))}">${esc(fmtWhen(sn.snooze_until))}</span>`
    : `<span class="ag">${esc(fmtAge(a.published))}</span>`;
  return `<div class="row${rd}" role="option" tabindex="-1" data-i="${i}" data-id="${esc(a.id)}" aria-selected="${!!sel && sel.id === a.id}">`
    + `<span class="sv ${s}" data-lu="${esc(t('label.read'))}"><span class="d" aria-hidden="true"></span>${burn(a.score)}</span>`
    + `<div class="tc"><div class="t">${a.bookmarked ? `<svg class="bmk" viewBox="0 0 16 16" role="img" aria-label="${esc(t('act.bookmarked'))}"><path d="M4 2h8v12l-4-3-4 3z" fill="currentColor"/></svg>` : ''}${esc(a.title)}</div>`
    + `${a.summary ? `<p class="s">${esc(a.summary)}</p>` : ''}</div>`
    + `<span class="tp">${esc(topTopic(a))}</span><span class="fd">${esc(a.feed_title || '')}</span>${ag}${_rowActs(a)}</div>`;
}

function _skeleton() {
  let h = `<span class="sr" role="status">${esc(t('list.loading'))}</span>`;
  for (let k = 0; k < 12; k++) {
    h += `<div class="row skel" aria-hidden="true"><span class="bar-s" style="width:44px"></span><span class="bar-s" style="width:${45 + (k * 37) % 45}%"></span>`
      + `<span class="bar-s" style="width:70px"></span><span class="bar-s fd" style="width:60px"></span><span class="bar-s" style="width:24px;justify-self:end"></span></div>`;
  }
  return h;
}

function _stateBlock(title, text, btns = '', ring = false) {
  return `<div class="state">${ring ? `<div class="ring">${ic('ok')}</div>` : ''}<h2>${esc(title)}</h2>${text ? `<p>${esc(text)}</p>` : ''}${btns ? `<div class="btns">${btns}</div>` : ''}</div>`;
}

function _listBody(sel) {
  const l = _view.list;
  if (!state.everLoaded) return _skeleton();
  const syncBtn = state.authenticated ? `<button type="button" class="btn primary" data-cmd="sync">${ic('sync')}${esc(t('btn.firstSync'))}</button>` : '';
  if (!state.articles.length && !state.lastRefresh && state.view !== 'sn') return _stateBlock(t('empty.title'), t('empty.hint'), syncBtn);
  if (!l.length) {
    if (isFiltered()) return _stateBlock(t('empty.filtered'), t('empty.filteredHint'), `<button type="button" class="btn" data-cmd="reset">${esc(t('empty.reset'))}</button>`);
    if (state.view === 'triage') {
      const btns = state.authenticated
        ? `<button type="button" class="btn" data-view="read">${esc(t('empty.seeRead'))}</button><button type="button" class="btn" data-cmd="sync">${ic('sync')}${esc(t('btn.sync'))}</button>`
        : '';
      return _stateBlock(t('allread.title'), t('allread.sub') + (state.lastRefresh ? ' ' + t('sum.synced', { ago: fmtAgo(state.lastRefresh) }) + '.' : ''), btns, true);
    }
    return _stateBlock(t(`empty.${state.view}.title`), t(`empty.${state.view}.hint`));
  }

  const vis = l.slice(0, state.shown);
  const counts = new Map();
  if (state.sortKey === 'age') for (const a of vis) { const k = dayKey(a.published); counts.set(k, (counts.get(k) || 0) + 1); }
  let h = '', lastDay = null;
  vis.forEach((a, i) => {
    if (state.sortKey === 'age') {
      const k = dayKey(a.published);
      if (k !== lastDay) {
        const ackDay = state.authenticated && state.view === 'triage'
          ? `<button type="button" data-day="${k}" data-dact="ack">${esc(t('btn.dayRead'))}</button>` : '';
        h += `<div class="day"><span class="dl">${esc(dayLabel(a.published))}</span><span class="n">${counts.get(k)}</span>`
          + `<span class="acts"><button type="button" data-day="${k}" data-dact="open">${esc(t('btn.dayOpen'))}</button>${ackDay}</span></div>`;
        lastDay = k;
      }
    }
    h += _row(a, i, sel);
  });
  h += l.length > state.shown
    ? `<div class="more"><button type="button" class="btn" data-cmd="more">${esc(t('btn.loadMore'))} <span class="kbd">${esc(t('btn.remaining', { n: l.length - state.shown }))}</span></button></div>`
    : '<div class="more"></div>';
  return h;
}

function renderList() {
  const el = byId('list');
  const keepTop = el.scrollTop;
  const empty = state.everLoaded && !state.articles.length && !state.lastRefresh && state.view !== 'sn';
  const head = empty ? '' : `<div class="head" role="presentation">${_th('burn', 'col.burn')}${_th('title', 'col.title')}${_th('topic', 'col.topic')}${_th('feed', 'col.feed', 'fd')}${_th('age', state.view === 'sn' ? 'col.reminder' : 'col.age', 'r')}</div>`;
  el.innerHTML = head + _listBody(currentArticle());
  if (keepTop) { el.scrollTop = keepTop; _lastListTop = el.scrollTop; }
  _observeMore(el);
}

// Infinite scroll: the "load more" button doubles as the sentinel, kept as a fallback.
let _moreObserver = null;
function _observeMore(el) {
  _moreObserver?.disconnect();
  const btn = el.querySelector('[data-cmd="more"]');
  if (!btn) return;
  _moreObserver = new IntersectionObserver((entries) => {
    if (!entries.some(e => e.isIntersecting)) return;
    _moreObserver.disconnect();
    state.shown += PAGE_SIZE; renderMain();
  }, { root: el, rootMargin: '0px 0px 400px 0px' });
  _moreObserver.observe(btn);
}

// ── Reader panel ───────────────────────────────────────────────────────
function _signal(a) {
  const e = Object.entries(a.matched_topics || {}).sort((x, y) => y[1] - x[1]).slice(0, 5);
  const max = e.length ? e[0][1] || 1 : 1;
  const fw = a.feed_weight && Math.abs(a.feed_weight - 1) > 0.001 ? a.feed_weight : null;
  if (!e.length) return `<p class="sig-note">${esc(t('reader.noSignal'))}</p>`;
  return '<div class="sig">' + e.map(([k, v], i) =>
    `<span>${esc(k)}</span><span class="bar2${i === 0 ? ' top' : ''}"><i style="width:${Math.max(2, v / max * 100)}%"></i></span><span class="v">${v.toFixed(1)}</span>`
  ).join('') + '</div>'
    + (fw ? `<p class="sig-note">${esc(t('reader.feedWeight', { feed: a.feed_title, w: fw.toFixed(2) }))}</p>` : '');
}

function _readerHtml(a, l) {
  const close = `<button type="button" class="btn ghost" data-close>${esc(t('reader.close'))} <kbd>esc</kbd></button>`;
  if (!a) return `<div class="ph"><span></span>${close}</div><div class="state"><p>${esc(t('reader.empty'))}</p></div>`;
  const s = sevOf(a.score), idx = l.indexOf(a);
  const url = safeUrl(a.url);
  let acts = url !== '#'
    ? `<a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener">${ic('ext')}${esc(t('reader.open'))} <kbd>o</kbd></a>` : '';
  if (state.authenticated) {
    if (state.view === 'read') acts += `<button type="button" class="btn" data-act="unack" data-id="${esc(a.id)}">${ic('undo')}${esc(t('act.unack'))}</button>`;
    else if (state.view === 'sn') acts += `<button type="button" class="btn" data-act="wake" data-id="${esc(a.id)}">${ic('undo')}${esc(t('act.wake'))}</button>`;
    else acts += `<button type="button" class="btn" data-act="ack" data-id="${esc(a.id)}">${ic('ok')}${esc(t('act.ack'))} <kbd>m</kbd></button>`
      + `<button type="button" class="btn" data-act="sn" data-id="${esc(a.id)}">${ic('sn')}${esc(t('act.snooze'))} <kbd>s</kbd></button>`;
    if (!a._stub) acts += `<button type="button" class="btn" data-act="bm" data-id="${esc(a.id)}" aria-pressed="${!!a.bookmarked}">${ic(a.bookmarked ? 'bmf' : 'bm')}${esc(t(a.bookmarked ? 'act.bookmarked' : 'act.bookmark'))} <kbd>b</kbd></button>`;
  }
  const sn = state.snoozes.get(a.id);
  const by = [a.feed_title, a.published ? fmtAgo(a.published) : ''].filter(Boolean).map(esc).join(' · ');
  return `<div class="ph"><span>${idx + 1} / ${l.length}</span><span class="nav2">`
    + `<button type="button" class="btn ghost ico" data-cmd="prev" aria-label="${esc(t('reader.prev'))}">${ic('up')}</button>`
    + `<button type="button" class="btn ghost ico" data-cmd="next" aria-label="${esc(t('reader.next'))}">${ic('down')}</button>${close}</span></div>`
    + `<div class="rd"><div class="rd-kicker"><span class="pill ${s}">${SEV_LABEL[s]} · ${esc(t('reader.burn'))} ${burn(a.score)}</span>`
    + `${topTopic(a) ? `<span>${esc(topTopic(a))}</span>` : ''}${sn ? `<span>· ${esc(t('reader.snoozedUntil', { when: fmtWhen(sn.snooze_until) }))}</span>` : ''}</div>`
    + `<h2 id="rd-title">${esc(a.title)}</h2>${by ? `<div class="rd-by">${by}</div>` : ''}`
    + `<div class="rd-actions">${acts}</div>`
    + (a.summary ? `<p class="rd-sum">${esc(a.summary)}</p>` : '')
    + `<div class="rd-sec"><h3>${esc(t('reader.signal'))}</h3>${_signal(a)}</div>`
    + ((a.matched_keywords || []).length ? `<div class="rd-sec"><h3>${esc(t('reader.keywords'))}</h3><div class="kws">${a.matched_keywords.map(k => `<span>${esc(k)}</span>`).join('')}</div></div>` : '')
    + '</div>';
}

function _panelVisible() {
  return !!state.open || (state.pin && window.matchMedia('(min-width: 1100px)').matches);
}

function renderPanel() {
  const p = byId('panel');
  const visible = _panelVisible();
  p.classList.toggle('open', !!state.open);
  p.inert = !visible;
  p.innerHTML = visible ? _readerHtml(currentArticle(), visibleList()) : '';
}

// ── Overflow menu ──────────────────────────────────────────────────────
const ACCENT_SWATCHES = [null, '#4f7f78', '#3d63c9', '#b4552d', '#7a4fb0'];

function renderMenu() {
  const pop = byId('menu-pop');
  byId('menu-btn').setAttribute('aria-expanded', String(state.menu));
  pop.hidden = !state.menu;
  if (!state.menu) { pop.innerHTML = ''; return; }
  const r = document.documentElement, d = r.dataset.density, th = r.dataset.theme, acc = lsGet('accent');
  const seg = (attr, opts, cur) => `<div class="seg">${opts.map(([v, k]) => `<button type="button" data-${attr}="${v}" aria-pressed="${cur === v}">${esc(t(k))}</button>`).join('')}</div>`;
  let h = `<div class="sec"><div class="inline"><span>${esc(t('menu.density'))}</span>${seg('dens', [['scan', 'dens.scan'], ['read', 'dens.read']], d)}</div>`
    + `<div class="inline"><span>${esc(t('menu.theme'))}</span>${seg('theme', [['light', 'theme.light'], ['dark', 'theme.dark']], th)}</div>`
    + `<div class="inline"><span>${esc(t('menu.accent'))}</span><div class="swatches">`
    + ACCENT_SWATCHES.map(c => `<button type="button" data-accent="${c || ''}" aria-pressed="${(c || null) === acc}" aria-label="${esc(c ? t('menu.accentN', { c }) : t('menu.accentDefault'))}" style="background:${c || 'var(--text)'}"></button>`).join('')
    + `<input type="color" id="accent-input" value="${esc(acc || '#4f7f78')}" aria-label="${esc(t('menu.accentCustom'))}"></div></div></div>`;
  if (state.authenticated) {
    h += `<div class="sec"><button type="button" class="it" role="menuitemcheckbox" aria-checked="${state.autoRead}" data-cmd="autoread">${esc(t('menu.autoRead'))}<span class="tog${state.autoRead ? ' on' : ''}" aria-hidden="true"></span></button></div>`
      + `<div class="sec"><div class="lbl">${esc(t('menu.scoring'))}</div><button type="button" class="it" role="menuitem" data-cmd="cfg">${ic('sliders')}${esc(t('menu.topicsFeeds'))}</button>`
      + `<button type="button" class="it${state.rescoreArm ? ' warnc' : ''}" role="menuitem" data-cmd="rescore">${ic('redo')}${esc(state.rescoreArm ? t('btn.rescoreConfirm', { n: state.articles.length }) : t('btn.rescore'))}</button></div>`;
  }
  h += `<div class="sec"><div class="lbl">${esc(t('menu.lang'))}</div><div class="langs">`
    + LANGS.map(l => `<button type="button" class="it" role="menuitemradio" aria-checked="${state.lang === l.code}" data-lang="${l.code}"><span class="code">${l.code.toUpperCase()}</span>${esc(l.label)}</button>`).join('')
    + '</div></div><div class="sec">'
    + (state.authenticated ? `<div class="lbl">${esc(t('menu.signedIn', { user: window._USER || '' }))}</div><button type="button" class="it" role="menuitem" data-cmd="pwd">${ic('key')}${esc(t('btn.changePassword'))}</button>` : '')
    + `<button type="button" class="it" role="menuitem" data-cmd="help">${ic('kb')}${esc(t('menu.shortcuts'))}<span class="k">?</span></button>`
    + (state.authenticated
      ? `<button type="button" class="it" role="menuitem" data-cmd="logout">${ic('out')}${esc(t('btn.logout'))}</button>`
      : `<a class="it" role="menuitem" href="/login">${ic('out')}${esc(t('btn.login'))}</a>`)
    + '</div>';
  pop.innerHTML = h;
}

// ── Render entry points ────────────────────────────────────────────────
function _shellClasses() {
  const sh = byId('shell');
  sh.classList.toggle('pinned', state.pin);
  sh.classList.toggle('collapsed', state.collapse);
  byId('side').classList.toggle('open', state.side);
  byId('scrim').classList.toggle('open', state.side);
}

function render() {
  cancelAnimationFrame(_mainRaf);
  recompute();
  _shellClasses();
  renderSidebar(); renderToolbar(); renderSummary(); renderList(); renderPanel(); renderMenu();
}

// Slider drag and typing: rebuild only toolbar, summary, list and panel, once per frame.
let _mainRaf = 0;
function renderMain() {
  cancelAnimationFrame(_mainRaf);
  _mainRaf = requestAnimationFrame(() => {
    recompute(); renderToolbar(); renderSummary(); renderList(); renderPanel();
  });
}
