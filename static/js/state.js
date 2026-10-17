// ── Constants ──────────────────────────────────────────────────────────
// Severity bands on the raw score. Burn rate shown in the UI is score / BURN_DIVISOR.
// Calibrated on prod scores (30 days): P1 ~ top 1% (about 2 a day), P2 ~ next 3%. 400/200 left almost everything P3.
const SEV_P1_MIN = 100;
const SEV_P2_MIN = 40;
const BURN_DIVISOR = 100;
const MIN_SCORE_MAX = 800;
const PAGE_SIZE = 30;
const READ_FLUSH_MS = 3000;
const PERIODS = [7, 14, 30, 0];

// ── Storage (private windows and blocked storage throw) ────────────────
function lsGet(k, d = null) {
  try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; }
}
function lsSet(k, v) {
  try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch {}
}

// ── State ──────────────────────────────────────────────────────────────
let state = {
  articles: [], everLoaded: false, loadError: null,
  view: 'triage', topic: null, search: '', sev: null,
  minScore: (() => { const v = parseFloat(lsGet('freshrss-minscore')); return Number.isFinite(v) ? Math.min(Math.max(v, 0), MIN_SCORE_MAX) : 0; })(),
  days: (() => { const v = parseInt(lsGet('freshrss-days'), 10); return PERIODS.includes(v) ? v : 7; })(),
  sortKey: (lsGet('freshrss-sort', 'burn:-1').split(':')[0]) || 'burn',
  sortDir: lsGet('freshrss-sort', 'burn:-1').split(':')[1] === '1' ? 1 : -1,
  shown: PAGE_SIZE, sel: 0, open: null,
  pin: lsGet('freshrss-pin', '1') === '1',
  collapse: lsGet('freshrss-collapse', '0') === '1',
  side: false, menu: false, rescoreArm: false,
  syncing: false, rescoring: false, pollInterval: null,
  lastRefresh: null, syncError: null, allTopics: [],
  snoozes: new Map(),
  autoRead: lsGet('freshrss-autoread', '1') === '1',
  keep: new Set(), lastAck: null,
  authenticated: !!window._AUTH,
  lang: (() => {
    const s = lsGet('freshrss-lang');
    if (s && I18N[s]) return s;
    const nav = (navigator.language || '').toLowerCase().slice(0, 2);
    return I18N[nav] ? nav : 'fr';
  })(),
};

// ── Auto mark-as-read on scroll ────────────────────────────────────────
// Rows scrolled past the top of the list are queued, flushed after READ_FLUSH_MS,
// then stay dimmed (state.keep) until the view or filters change.
const LS_KEY = 'freshrss-read-ids';
const _markedIds = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(LS_KEY) || '[]')); }
  catch { return new Set(); }
})();
function saveReadIds() { lsSet(LS_KEY, JSON.stringify([..._markedIds])); }
const _readQueue = new Set();
const _readInflight = new Set();
let _readFlushTimer = null;
let _lastListTop = 0;
let _scrollTicking = false;

function _scanScrolledPast(el) {
  _scrollTicking = false;
  const head = el.querySelector('.head');
  const top = el.getBoundingClientRect().top + (head ? head.offsetHeight : 0);
  let added = false;
  // Rows are in DOM order: stop at the first one still on screen.
  for (const r of el.querySelectorAll('.row[data-id]')) {
    const id = r.dataset.id;
    if (_markedIds.has(id) || _readQueue.has(id) || _readInflight.has(id) || r.classList.contains('read')) continue;
    if (r.getBoundingClientRect().bottom >= top) break;
    _readQueue.add(id); r.classList.add('queued'); added = true;
  }
  if (added) { updateReadQueueBadge(); scheduleReadFlush(); }
}

function initReadTracking(el) {
  el.addEventListener('scroll', () => {
    const down = el.scrollTop > _lastListTop;
    _lastListTop = el.scrollTop;
    if (!down || _scrollTicking || !state.authenticated || !state.autoRead || state.view !== 'triage') return;
    _scrollTicking = true;
    requestAnimationFrame(() => _scanScrolledPast(el));
  }, { passive: true });
}

function scheduleReadFlush() {
  if (_readFlushTimer) return;
  _readFlushTimer = setTimeout(flushReadQueue, READ_FLUSH_MS);
}

async function flushReadQueue() {
  _readFlushTimer = null;
  if (!_readQueue.size) return;
  if (!state.authenticated) { _readQueue.clear(); return; }
  const ids = [..._readQueue]; _readQueue.clear();
  ids.forEach(id => _readInflight.add(id));
  try {
    await postMarkRead(ids);
    for (const id of ids) { _markedIds.add(id); state.keep.add(id); }
    saveReadIds();
    onScrollReadFlushed(ids);
  } catch (e) {
    ids.forEach(id => _readQueue.add(id));
    scheduleReadFlush();
  } finally {
    ids.forEach(id => _readInflight.delete(id));
  }
}

window.addEventListener('beforeunload', () => {
  if (!_readQueue.size || !state.authenticated) return;
  navigator.sendBeacon('/api/mark-read',
    new Blob([JSON.stringify({ article_ids: [..._readQueue] })], { type: 'application/json' }));
});
