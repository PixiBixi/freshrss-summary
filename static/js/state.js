// ── State ──────────────────────────────────────────────────────────────
let state = {
  articles: [], filtered: [], displayed: 100,
  activeTopic: null, sort: 'date', minScore: parseFloat(localStorage.getItem('freshrss-minscore')) || 1,
  pollInterval: null,
  openRow: null,
  search: '',
  focusedIdx: -1,
  compact: localStorage.getItem('freshrss-compact') === '1',
  showBookmarks: false,
  showRead: false,
  authenticated: false,
  everLoaded: false,
  days: 7,
  lang: (() => {
    const s = localStorage.getItem('freshrss-lang');
    if (s && I18N[s]) return s;
    const nav = navigator.language.toLowerCase().slice(0, 2);
    return I18N[nav] ? nav : 'fr';
  })(),
};

// ── Auto mark-as-read on scroll ────────────────────────────────────────
const LS_KEY = 'freshrss-read-ids';
const _markedIds = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(LS_KEY) || '[]')); }
  catch { return new Set(); }
})();
function saveReadIds() {
  try { localStorage.setItem(LS_KEY, JSON.stringify([..._markedIds])); } catch {}
}
const _readQueue = new Set();
let _readFlushTimer = null;
let _lastScrollY = 0;

window.addEventListener('scroll', () => {
  const currentY = window.scrollY;
  if (currentY <= _lastScrollY) { _lastScrollY = currentY; return; }
  _lastScrollY = currentY;

  document.querySelectorAll('.feed-row[data-id]').forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.bottom < 0) {
      const id = el.dataset.id;
      if (id && !_markedIds.has(id) && !el.dataset.alreadyRead) {
        _markedIds.add(id);
        _readQueue.add(id);
        scheduleReadFlush();
      }
    }
  });
}, { passive: true });

function scheduleReadFlush() {
  if (_readFlushTimer) return;
  _readFlushTimer = setTimeout(flushReadQueue, 3000);
}

async function flushReadQueue() {
  _readFlushTimer = null;
  if (!_readQueue.size) return;
  if (!state.authenticated) { _readQueue.clear(); return; }
  const ids = [..._readQueue]; _readQueue.clear();
  try {
    await fetch('/api/mark-read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_ids: ids }),
    });
    for (const id of ids) {
      document.querySelector(`.feed-row[data-id="${CSS.escape(id)}"]`)?.classList.add('read');
    }
    saveReadIds();
    applyFilters();
  } catch (e) {
    ids.forEach(id => { _markedIds.delete(id); _readQueue.add(id); });
    scheduleReadFlush();
  }
}

window.addEventListener('beforeunload', () => {
  if (!_readQueue.size || !state.authenticated) return;
  navigator.sendBeacon('/api/mark-read',
    new Blob([JSON.stringify({ article_ids: [..._readQueue] })], { type: 'application/json' }));
});
