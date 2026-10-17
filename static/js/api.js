// ── API ────────────────────────────────────────────────────────────────
// Single fetch wrapper: 401 -> login redirect, non-ok -> Error(detail), `json` -> JSON body.
async function apiFetch(url, opts = {}) {
  const { json, ...init } = opts;
  if (json !== undefined) {
    init.method = init.method || 'POST';
    init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
    init.body = JSON.stringify(json);
  }
  const r = await fetch(url, init);
  if (r.status === 401) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    const err = new Error('unauthorized'); err.status = 401; throw err;
  }
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    const err = new Error(typeof data.detail === 'string' && data.detail ? data.detail : t('toast.error'));
    err.status = r.status; throw err;
  }
  return r;
}

async function apiJson(url, opts) { return (await apiFetch(url, opts)).json(); }

function _reportError(e) {
  if (e.name === 'AbortError' || e.status === 401) return;
  toastError(e.message || t('toast.error'));
}

function postMarkRead(ids) { return apiJson('/api/mark-read', { json: { article_ids: ids } }); }
function postMarkUnread(ids) { return apiJson('/api/mark-unread', { json: { article_ids: ids } }); }

function fetchStatus(opts) { return apiJson('/api/status', opts); }

function fetchMe() {
  state.authenticated = !!window._AUTH;
  document.documentElement.classList.toggle('auth', state.authenticated);
}

async function doLogout() {
  await fetch('/logout', { method: 'POST' });
  window.location.href = '/login';
}

function _requireAuth() {
  if (!state.authenticated) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    return false;
  }
  return true;
}

function _applyStatus(s) {
  state.lastRefresh = s.last_refresh || null;
  state.syncError = s.is_loading ? null : (s.error || null);
  if (Array.isArray(s.all_topics)) state.allTopics = s.all_topics;
}

let _loadCtl = null;

async function loadArticles() {
  if (_loadCtl) _loadCtl.abort();
  const ctl = _loadCtl = new AbortController();
  try {
    const params = new URLSearchParams({ days: state.days, limit: 0 });
    if (state.view === 'read') params.set('show_read', 'true');
    let data;
    for (let attempt = 0; ; attempt++) {
      try { data = await apiJson(`/api/articles?${params}`, { signal: ctl.signal }); break; }
      catch (e) {
        if (e.status !== 503 || attempt >= 5) throw e;
        await new Promise(res => setTimeout(res, 1000));
        if (ctl.signal.aborted) return;
      }
    }
    if (ctl.signal.aborted) return;
    state.loadError = null;
    state.articles = data.articles;
    state.everLoaded = true;
    const currentIds = new Set(data.articles.map(a => a.id));
    for (const id of _markedIds) if (!currentIds.has(id)) _markedIds.delete(id);
    saveReadIds();
    try {
      const status = await fetchStatus({ signal: ctl.signal });
      if (!ctl.signal.aborted) _applyStatus(status);
    } catch { /* last-refresh label is cosmetic */ }
    render();
  } catch (e) {
    if (e.name === 'AbortError' || ctl !== _loadCtl) return;
    state.loadError = e.message || t('toast.error');
    state.everLoaded = true;
    render();
  }
}

async function fetchSnoozes() {
  if (!state.authenticated) return;
  try {
    const { snoozes } = await apiJson('/api/snoozes');
    state.snoozes = new Map((snoozes || []).map(s => [s.article_id, s]));
    render();
  } catch (e) { _reportError(e); }
}

// ── Ack (mark read) and undo ───────────────────────────────────────────
// Optimistic: rows fade out, ids are hidden at once, rolled back if the POST fails.
async function ackArticles(ids, label) {
  if (!state.authenticated || !ids.length) return;
  ids.forEach(id => rowEl(id)?.classList.add('leaving'));
  await new Promise(res => setTimeout(res, 180));
  for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
  saveReadIds();
  if (ids.includes(state.open)) state.open = null;
  render();
  try {
    const r = await postMarkRead(ids);
    state.lastAck = ids;
    const msg = label || (ids.length > 1 ? t('toast.ackedN', { n: ids.length }) : t('toast.acked'));
    toast(msg + ' · ' + t(r && r.status !== 'ok' ? 'toast.ackQueued' : 'toast.ackSynced'),
      { action: undoAck, label: t('toast.undoKey') });
  } catch (e) {
    for (const id of ids) _markedIds.delete(id);
    saveReadIds(); render(); _reportError(e);
  }
}

function markVisibleAsRead() { ackArticles(visibleList().map(a => a.id)); }

function markSingleAsRead(id) { ackArticles([id]); }

function markDayAsRead(key) {
  const items = visibleList().filter(a => dayKey(a.published) === key);
  ackArticles(items.map(a => a.id), t('toast.ackedDay', { n: items.length, day: dayLabel(items[0]?.published).toLowerCase() }));
}

async function markUnread(ids, msg) {
  if (!state.authenticated || !ids.length) return;
  try {
    await postMarkUnread(ids);
    for (const id of ids) { _markedIds.delete(id); state.keep.delete(id); }
    saveReadIds();
    let missing = false;
    for (const id of ids) {
      const a = state.articles.find(x => x.id === id);
      if (a) a._read = false; else missing = true;
    }
    if (missing) await loadArticles(); else render();
    toastSuccess(msg || (ids.length > 1 ? t('toast.unackedN', { n: ids.length }) : t('toast.unacked')));
  } catch (e) { _reportError(e); }
}

function undoAck() {
  const ids = state.lastAck;
  if (!ids || !ids.length) return;
  state.lastAck = null;
  markUnread(ids, ids.length > 1 ? t('toast.unackedN', { n: ids.length }) : t('toast.undone'));
}

// ── Bookmark, snooze ───────────────────────────────────────────────────
async function toggleBookmark(id) {
  if (!_requireAuth()) return;
  try {
    const { bookmarked } = await apiJson('/api/bookmark', { json: { article_id: id } });
    const article = state.articles.find(a => a.id === id);
    if (article) article.bookmarked = bookmarked;
    render();
    toastSuccess(t(bookmarked ? 'toast.bmAdded' : 'toast.bmRemoved'));
  } catch (err) { _reportError(err); }
}

async function snoozeArticle(id) {
  if (!_requireAuth()) return;
  const a = state.articles.find(x => x.id === id);
  try {
    const r = await apiJson('/api/snooze', { json: { article_id: id } });
    state.snoozes.set(id, { article_id: id, snooze_until: r.snooze_until, title: a?.title || '', url: a?.url || '' });
    if (state.open === id) state.open = null;
    render();
    toast(t('toast.snoozed', { when: fmtWhen(r.snooze_until) }), { action: () => cancelSnooze(id, true), label: t('toast.undo') });
  } catch (err) {
    if (err.status === 400) toastError(t('toast.snoozeNoTelegram'));
    else _reportError(err);
  }
}

async function cancelSnooze(id, quiet) {
  if (!_requireAuth()) return;
  try {
    await apiFetch(`/api/snooze/${encodeURIComponent(id)}`, { method: 'DELETE' });
    state.snoozes.delete(id);
    if (state.view === 'sn' && state.open === id) state.open = null;
    render();
    toastSuccess(t(quiet ? 'toast.snoozeCancelled' : 'toast.woken'));
  } catch (err) { _reportError(err); }
}

// ── Refresh (SSE) ──────────────────────────────────────────────────────
let _refreshES = null;

function triggerRefresh() {
  if (_refreshES || state.syncing) return;
  if (!_requireAuth()) return;
  setRefreshBtnLoading(true);
  showToast(t('toast.starting'));
  progress(8);

  const es = _refreshES = new EventSource('/api/refresh/stream');
  const freshMap = new Map();
  let buffer = [];
  let renderTimer = null;
  let isIncremental = false;
  let pct = 8;

  function closeStream() {
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
    es.close();
    _refreshES = null;
    setRefreshBtnLoading(false);
    progress(100);
  }

  function flushBuffer(isFinal = false) {
    renderTimer = null;
    for (const a of buffer) freshMap.set(a.id, a);
    buffer = [];

    if (isFinal) {
      if (isIncremental) {
        // Merge: removed articles already dropped by 'removed' event handler
        const existingIds = new Set(state.articles.map(a => a.id));
        const toAdd = [...freshMap.values()].filter(a => !existingIds.has(a.id));
        state.articles = [...state.articles, ...toAdd];
      } else {
        state.articles = [...freshMap.values()];
      }
      state.everLoaded = true;
    } else {
      const existingIds = new Set(state.articles.map(a => a.id));
      const toAdd = [...freshMap.values()].filter(a => !existingIds.has(a.id));
      if (!toAdd.length) return;
      state.articles = [...state.articles, ...toAdd];
    }
    renderMain(); renderSidebar();
  }

  es.onmessage = (ev) => {
    let event;
    try { event = JSON.parse(ev.data); } catch { return; }
    switch (event.type) {
      case 'progress':
        // No percentage in the stream: creep towards 90 % on each step.
        pct += (90 - pct) * 0.25; progress(pct);
        updateToast(event.message);
        break;
      case 'removed': {
        const removedSet = new Set(event.ids);
        state.articles = state.articles.filter(a => !removedSet.has(a.id));
        renderMain(); renderSidebar();
        break;
      }
      case 'article':
        buffer.push(event.article);
        if (!renderTimer) renderTimer = setTimeout(() => flushBuffer(false), 400);
        break;
      case 'done':
        isIncremental = !!event.incremental;
        if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
        flushBuffer(true);
        closeStream();
        state.lastRefresh = Math.floor(Date.now() / 1000); state.syncError = null;
        render();
        toastSuccess(event.total_fetched === 0
          ? t('toast.noUnread')
          : t('toast.relevant', { n: event.count }));
        break;
      case 'error':
        closeStream();
        state.syncError = event.message; render();
        toastError(event.message);
        break;
      case 'busy':
        closeStream();
        toastError(t('toast.busy'));
        break;
    }
  };

  es.onerror = () => {
    closeStream();
    toastError(t('toast.lost'));
  };
}

// ── Rescore ────────────────────────────────────────────────────────────
// Two-step confirm lives in the menu (state.rescoreArm); the palette and the
// scoring modal call _doRescore directly since they are explicit already.
function triggerRescore() {
  if (state.rescoreArm) { state.rescoreArm = false; state.menu = false; renderMenu(); _doRescore(); }
  else { state.rescoreArm = true; renderMenu(); }
}

async function _doRescore() {
  if (!_requireAuth()) return;
  setRescoreBtnLoading(true); showToast(t('toast.rescoring')); progress(15);
  try {
    const json = await apiJson('/api/rescore', { method: 'POST' });
    if (json.status === 'already_loading') { toastError(t('toast.alreadyLoading')); setRescoreBtnLoading(false); progress(100); return; }
    startRescorePolling();
  } catch (e) { _reportError(e); setRescoreBtnLoading(false); progress(100); }
}

// Status polling: ticks never overlap, and a failed status is not a finished load.
function _startStatusPolling(setLoading, okMsg) {
  if (state.pollInterval) return;
  let busy = false, failures = 0;
  state.pollInterval = setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
      const s = await fetchStatus();
      failures = 0;
      updateToast(s.load_progress || t('toast.loading'));
      if (!s.is_loading) {
        stopPolling(); setLoading(false); progress(100);
        _applyStatus(s);
        if (s.error) { toastError(s.error); render(); }
        else { toastSuccess(okMsg(s)); await loadArticles(); }
      }
    } catch (e) {
      if (++failures >= 5) { stopPolling(); setLoading(false); progress(100); _reportError(e); }
    } finally { busy = false; }
  }, 1500);
}

function startRescorePolling() {
  _startStatusPolling(setRescoreBtnLoading, s => t('toast.rescored', { n: s.article_count }));
}

function startPolling() {
  _startStatusPolling(setRefreshBtnLoading, s => t('toast.relevant', { n: s.article_count }));
}

function stopPolling() {
  if (state.pollInterval) { clearInterval(state.pollInterval); state.pollInterval = null; }
}

// ── Scoring config ─────────────────────────────────────────────────────
function fetchScoringConfig() { return apiJson('/api/config/scoring'); }

function fetchFeeds() { return apiJson('/api/feeds'); }

async function updateScoringConfig(topics, feed_weights = {}) {
  await apiFetch('/api/config/scoring', { method: 'PUT', json: { topics, feed_weights } });
}

async function changePassword(currentPassword, newPassword) {
  await apiFetch('/api/change-password', {
    json: { current_password: currentPassword, new_password: newPassword },
  });
}
