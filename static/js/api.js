// ── API ────────────────────────────────────────────────────────────────
async function fetchStatus() { return (await fetch('/api/status')).json(); }

async function fetchMe() {
  try {
    const data = await (await fetch('/api/me')).json();
    state.authenticated = data.authenticated;
    const badge = document.getElementById('auth-badge');
    const loginBtn = document.getElementById('login-btn');
    if (data.authenticated) {
      document.getElementById('auth-username').textContent = data.username || '';
      badge.style.display = '';
      loginBtn.style.display = 'none';
    } else {
      badge.style.display = 'none';
      loginBtn.style.display = '';
    }
  } catch {}
}

async function doLogout() {
  await fetch('/logout', { method: 'POST' });
  state.authenticated = false;
  fetchMe();
}

function _requireAuth() {
  if (!state.authenticated) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    return false;
  }
  return true;
}

async function loadArticles() {
  try {
    const params = new URLSearchParams({ days: state.days });
    if (state.showRead) params.set('show_read', 'true');
    const data = await (await fetch(`/api/articles?${params}`)).json();
    state.articles = data.articles;
    state.displayed = 100; state.everLoaded = true;
    const currentIds = new Set(data.articles.map(a => a.id));
    for (const id of _markedIds) if (!currentIds.has(id)) _markedIds.delete(id);
    saveReadIds();
    buildTopicPills(data.articles.filter(a => !a._read)); applyFilters();
    const status = await fetchStatus();
    updateLastRefresh(status.last_refresh);
  } catch (e) { showError(e.message); }
}

async function markVisibleAsRead() {
  const ids = state.filtered.slice(0, state.displayed).map(a => a.id);
  if (!ids.length) return;
  const btn = document.getElementById('mark-read-btn');
  btn.disabled = true; btn.textContent = t('toast.marking');
  try {
    const r = await fetch('/api/mark-read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_ids: ids }),
    });
    if (!r.ok) throw new Error('Failed');
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    saveReadIds();
    state.displayed = 100; buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id))); applyFilters();
  } catch (e) { alert('Erreur : ' + e.message); }
  finally { btn.disabled = false; btn.innerHTML = t('btn.markVisible'); }
}

async function markSingleAsRead(id, e) {
  e.stopPropagation(); e.preventDefault();
  try {
    await fetch('/api/mark-read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_ids: [id] }),
    });
    _markedIds.add(id); _readQueue.delete(id);
    saveReadIds();
    if (state.openRow === id) toggleDetail(id);
    document.querySelector(`.feed-row[data-id="${CSS.escape(id)}"]`)?.classList.add('read');
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id)));
    updateStats();
  } catch (e) { console.error(e); }
}

async function markDayAsRead(btn) {
  const group = btn.closest('.date-group');
  if (!group) return;
  const ids = JSON.parse(group.dataset.ids || '[]');
  if (!ids.length) return;
  btn.disabled = true;
  try {
    await fetch('/api/mark-read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_ids: ids }),
    });
    const s = new Set(ids);
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    saveReadIds();
    if (s.has(state.openRow)) toggleDetail(state.openRow);
    group.querySelectorAll('.feed-row').forEach(row => row.classList.add('read'));
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id)));
    applyFilters();
  } catch (e) { console.error(e); }
  finally { btn.disabled = false; }
}

async function markSearchAsRead() {
  const ids = state.filtered.map(a => a.id);
  if (!ids.length) return;
  const btn = document.getElementById('search-read-btn');
  btn.disabled = true; btn.textContent = t('toast.marking');
  try {
    const r = await fetch('/api/mark-read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_ids: ids }),
    });
    if (!r.ok) throw new Error('Failed');
    for (const id of ids) { _markedIds.add(id); _readQueue.delete(id); }
    saveReadIds();
    state.displayed = 100;
    buildTopicPills(state.articles.filter(a => !_markedIds.has(a.id))); applyFilters();
  } catch (e) { alert('Erreur : ' + e.message); }
  finally { btn.disabled = false; btn.textContent = t('btn.markSearch'); }
}

async function toggleBookmark(id, e) {
  e.stopPropagation(); e.preventDefault();
  try {
    const r = await fetch('/api/bookmark', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_id: id }),
    });
    if (!r.ok) return;
    const { bookmarked } = await r.json();
    const article = state.articles.find(a => a.id === id);
    if (article) article.bookmarked = bookmarked;
    const btn = document.querySelector(`.row-bookmark[onclick*="${CSS.escape(id)}"]`);
    if (btn) {
      btn.textContent = bookmarked ? '★' : '☆';
      btn.classList.toggle('bookmarked', bookmarked);
    }
    buildTopicPills(state.articles);
  } catch (e) { console.error(e); }
}

function triggerRefresh() {
  if (!_requireAuth()) return;
  setRefreshBtnLoading(true);
  showToast(t('toast.starting'));

  const es = new EventSource('/api/refresh/stream');
  const freshMap = new Map();
  let buffer = [];
  let renderTimer = null;

  function flushBuffer(isFinal = false) {
    renderTimer = null;
    for (const a of buffer) freshMap.set(a.id, a);
    buffer = [];

    if (isFinal) {
      state.articles = [...freshMap.values()];
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
    const event = JSON.parse(ev.data);
    switch (event.type) {
      case 'progress':
        updateToast(event.message);
        break;
      case 'article':
        buffer.push(event.article);
        if (!renderTimer) renderTimer = setTimeout(() => flushBuffer(false), 400);
        break;
      case 'done':
        if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
        flushBuffer(true);
        es.close();
        setRefreshBtnLoading(false);
        toastSuccess(event.total_fetched === 0
          ? t('toast.noUnread')
          : t('toast.relevant', { n: event.count }));
        break;
      case 'error':
        if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
        es.close();
        setRefreshBtnLoading(false);
        toastError(event.message);
        break;
      case 'busy':
        es.close();
        setRefreshBtnLoading(false);
        toastError(t('toast.busy'));
        break;
    }
  };

  es.onerror = () => {
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
    es.close();
    setRefreshBtnLoading(false);
    toastError(t('toast.lost'));
  };
}

function triggerRescore() {
  const btn = document.getElementById('rescore-btn');
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
    const r = await fetch('/api/rescore', { method: 'POST' });
    const json = await r.json();
    if (!r.ok) { toastError(json.detail || t('toast.error')); setRescoreBtnLoading(false); return; }
    if (json.status === 'already_loading') { toastError(t('toast.alreadyLoading')); setRescoreBtnLoading(false); return; }
    startRescorePolling();
  } catch (e) { toastError(e.message); setRescoreBtnLoading(false); }
}

function startRescorePolling() {
  if (state.pollInterval) return;
  state.pollInterval = setInterval(async () => {
    try {
      const s = await fetchStatus();
      updateToast(s.load_progress || t('toast.loading'));
      if (!s.is_loading) {
        stopPolling(); setRescoreBtnLoading(false);
        if (s.error) toastError(s.error);
        else { toastSuccess(t('toast.rescored', { n: s.article_count })); await loadArticles(); }
      }
    } catch (e) { stopPolling(); setRescoreBtnLoading(false); toastError(e.message); }
  }, 1500);
}

function startPolling() {
  if (state.pollInterval) return;
  state.pollInterval = setInterval(async () => {
    try {
      const s = await fetchStatus();
      updateToast(s.load_progress || t('toast.loading'));
      if (!s.is_loading) {
        stopPolling(); setRefreshBtnLoading(false);
        if (s.error) toastError(s.error);
        else { toastSuccess(t('toast.relevant', { n: s.article_count })); await loadArticles(); }
      }
    } catch (e) { stopPolling(); setRefreshBtnLoading(false); toastError(e.message); }
  }, 1500);
}

function stopPolling() {
  if (state.pollInterval) { clearInterval(state.pollInterval); state.pollInterval = null; }
}

// ── Scoring config ─────────────────────────────────────────────────────
async function fetchScoringConfig() {
  const r = await fetch('/api/config/scoring');
  if (!r.ok) throw new Error('Failed to load scoring config');
  return (await r.json()).topics;
}

async function updateScoringConfig(topics) {
  const r = await fetch('/api/config/scoring', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topics }),
  });
  if (!r.ok) throw new Error('Failed to save scoring config');
}

async function changePassword(currentPassword, newPassword) {
  const r = await fetch('/api/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || 'error');
  }
}
