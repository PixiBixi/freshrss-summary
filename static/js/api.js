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

function postMarkRead(ids) { return apiFetch('/api/mark-read', { json: { article_ids: ids } }); }

function fetchStatus(opts) { return apiJson('/api/status', opts); }

function fetchMe() {
  state.authenticated = !!window._AUTH;
  const authEl     = document.getElementById('overflow-auth');
  const loginEl    = document.getElementById('overflow-login');
  const usernameEl = document.getElementById('auth-username');
  if (state.authenticated) {
    if (usernameEl) usernameEl.textContent = window._USER || '';
    if (authEl)  authEl.style.display  = '';
    if (loginEl) loginEl.style.display = 'none';
  } else {
    if (authEl)  authEl.style.display  = 'none';
    if (loginEl) loginEl.style.display = '';
  }
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

let _loadCtl = null;

async function loadArticles() {
  if (_loadCtl) _loadCtl.abort();
  const ctl = _loadCtl = new AbortController();
  try {
    const params = new URLSearchParams({ days: state.days, limit: 0 });
    if (state.showRead) params.set('show_read', 'true');
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
    document.getElementById('error-state').style.display = 'none';
    state.articles = data.articles;
    state.displayed = 100; state.everLoaded = true;
    const currentIds = new Set(data.articles.map(a => a.id));
    for (const id of _markedIds) if (!currentIds.has(id)) _markedIds.delete(id);
    saveReadIds();
    buildTopicPills(data.articles.filter(a => !a._read)); applyFilters();
    try {
      const status = await fetchStatus({ signal: ctl.signal });
      if (!ctl.signal.aborted) updateLastRefresh(status.last_refresh);
    } catch { /* last-refresh label is cosmetic */ }
  } catch (e) {
    if (e.name === 'AbortError' || ctl !== _loadCtl) return;
    showError(e.message);
  }
}

async function markVisibleAsRead() {
  const ids = state.filtered.slice(0, state.displayed).map(a => a.id);
  if (!ids.length) return;
  try {
    await postMarkRead(ids);
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    saveReadIds();
    state.displayed = 100; buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id))); applyFilters();
  } catch (e) { _reportError(e); }
}

async function markSingleAsRead(id, e) {
  e.stopPropagation(); e.preventDefault();
  try {
    await postMarkRead([id]);
    _markedIds.add(id); _readQueue.delete(id);
    saveReadIds();
    if (state.openRow === id) toggleDetail(id);
    document.querySelector(`.feed-row[data-id="${CSS.escape(id)}"], .compact-row[data-id="${CSS.escape(id)}"]`)?.classList.add('read');
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id)));
    updateStats();
  } catch (err) { _reportError(err); }
}

async function markDayAsRead(btn) {
  const group = btn.closest('.date-group');
  if (!group) return;
  const ids = JSON.parse(group.dataset.ids || '[]');
  if (!ids.length) return;
  btn.disabled = true;
  try {
    await postMarkRead(ids);
    const s = new Set(ids);
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    state.articles = state.articles.filter(a => !s.has(a.id));
    saveReadIds();
    if (s.has(state.openRow)) { state.openRow = null; }
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id)));
    applyFilters();
  } catch (e) { _reportError(e); }
  finally { btn.disabled = false; }
}

async function markSearchAsRead() {
  const ids = state.filtered.slice(0, state.displayed).map(a => a.id);
  if (!ids.length) return;
  const btn = document.getElementById('search-read-btn');
  btn.disabled = true; btn.textContent = t('toast.marking');
  try {
    await postMarkRead(ids);
    const idSet = new Set(ids);
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    state.articles = state.articles.filter(a => !idSet.has(a.id));
    saveReadIds();
    state.displayed = 100;
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id))); applyFilters();
  } catch (e) { _reportError(e); }
  finally { btn.disabled = false; btn.textContent = t('btn.markSearch'); }
}

async function toggleBookmark(id, e) {
  e.stopPropagation(); e.preventDefault();
  try {
    const { bookmarked } = await apiJson('/api/bookmark', { json: { article_id: id } });
    const article = state.articles.find(a => a.id === id);
    if (article) article.bookmarked = bookmarked;
    const btn = document.querySelector(`.row-bookmark[data-id="${CSS.escape(id)}"]`);
    if (btn) {
      btn.textContent = bookmarked ? '★' : '☆';
      btn.classList.toggle('bookmarked', bookmarked);
    }
    buildTopicPills(state.articles);
  } catch (err) { _reportError(err); }
}

let _refreshES = null;

function triggerRefresh() {
  if (_refreshES) return;
  if (!_requireAuth()) return;
  setRefreshBtnLoading(true);
  showToast(t('toast.starting'));

  const es = _refreshES = new EventSource('/api/refresh/stream');
  const freshMap = new Map();
  let buffer = [];
  let renderTimer = null;
  let isIncremental = false;

  function closeStream() {
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
    es.close();
    _refreshES = null;
    setRefreshBtnLoading(false);
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
      state.displayed = 100;
    } else {
      const existingIds = new Set(state.articles.map(a => a.id));
      const toAdd = [...freshMap.values()].filter(a => !existingIds.has(a.id));
      if (!toAdd.length) return;
      state.articles = [...state.articles, ...toAdd];
    }
    buildTopicPills(state.articles);
    applyFilters();
  }

  es.onmessage = (ev) => {
    let event;
    try { event = JSON.parse(ev.data); } catch { return; }
    switch (event.type) {
      case 'progress':
        updateToast(event.message);
        break;
      case 'removed': {
        const removedSet = new Set(event.ids);
        state.articles = state.articles.filter(a => !removedSet.has(a.id));
        buildTopicPills(state.articles);
        applyFilters();
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
        toastSuccess(event.total_fetched === 0
          ? t('toast.noUnread')
          : t('toast.relevant', { n: event.count }));
        break;
      case 'error':
        closeStream();
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

function triggerRescore() {
  const btn = document.getElementById('rescore-btn');
  // Since the editorial redesign the rescore action lives in the overflow menu
  // and in the command palette - neither leaves a button in the DOM to carry the
  // two-step confirm, and the menu closes on click anyway. Fall back to a plain
  // dialog so the action still cannot fire by accident.
  if (!btn) {
    if (window.confirm(t('btn.rescoreConfirm'))) _doRescore();
    return;
  }
  if (btn.dataset.confirming === 'true') {
    clearTimeout(btn._confirmTimer);
    delete btn.dataset.confirming;
    btn.className = 'btn btn-ghost';
    btn.innerHTML = t('btn.rescore');
    _doRescore();
  } else {
    btn.dataset.confirming = 'true';
    btn.className = 'btn btn-warn';
    btn.innerHTML = t('btn.rescoreConfirm');
    btn._confirmTimer = setTimeout(() => {
      delete btn.dataset.confirming;
      btn.className = 'btn btn-ghost';
      btn.innerHTML = t('btn.rescore');
    }, 4000);
  }
}

async function _doRescore() {
  if (!_requireAuth()) return;
  setRescoreBtnLoading(true); showToast(t('toast.rescoring'));
  try {
    const json = await apiJson('/api/rescore', { method: 'POST' });
    if (json.status === 'already_loading') { toastError(t('toast.alreadyLoading')); setRescoreBtnLoading(false); return; }
    startRescorePolling();
  } catch (e) { _reportError(e); setRescoreBtnLoading(false); }
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
        stopPolling(); setLoading(false);
        if (s.error) toastError(s.error);
        else { toastSuccess(okMsg(s)); await loadArticles(); }
      }
    } catch (e) {
      if (++failures >= 5) { stopPolling(); setLoading(false); _reportError(e); }
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

async function updateScoringConfig(topics, feed_weights = {}) {
  await apiFetch('/api/config/scoring', { method: 'PUT', json: { topics, feed_weights } });
}

async function snoozeArticle(id, e) {
  e.stopPropagation(); e.preventDefault();
  if (!_requireAuth()) return;
  try {
    await apiFetch('/api/snooze', { json: { article_id: id } });
    showToast(t('toast.snoozed'));
  } catch (err) { _reportError(err); }
}

async function changePassword(currentPassword, newPassword) {
  await apiFetch('/api/change-password', {
    json: { current_password: currentPassword, new_password: newPassword },
  });
}
