// ── Toast ──────────────────────────────────────────────────────────────
let _toastTimeout = null;

function showToast(msg) {
  const el = document.getElementById('toast'); el.className = '';
  document.getElementById('toast-text').textContent = msg;
  document.getElementById('toast-spinner').style.display = 'block';
  document.getElementById('toast-close').style.display = 'none';
  if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }
}

function updateToast(msg) { document.getElementById('toast-text').textContent = msg; }

function toastSuccess(msg) {
  const el = document.getElementById('toast'); el.className = 'ok';
  document.getElementById('toast-spinner').style.display = 'none';
  document.getElementById('toast-text').textContent = '✓ ' + msg;
  document.getElementById('toast-close').style.display = 'inline';
  _toastTimeout = setTimeout(dismissToast, 4000);
}

function toastError(msg) {
  const el = document.getElementById('toast'); el.className = 'err';
  document.getElementById('toast-spinner').style.display = 'none';
  document.getElementById('toast-text').textContent = '✕ ' + msg;
  document.getElementById('toast-close').style.display = 'inline';
}

function dismissToast() {
  document.getElementById('toast').className = 'hidden';
  if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }
}

function showError(msg) {
  const el = document.getElementById('error-state');
  el.style.display = 'block'; el.textContent = msg;
}

// ── Utility ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Detail panel ───────────────────────────────────────────────────────
function toggleDetail(id) {
  const detail = document.getElementById(`detail-${id}`);
  if (!detail) return;
  if (detail.classList.contains('open')) {
    detail.classList.remove('open');
    state.openRow = null;
  } else {
    if (state.openRow) {
      const prev = document.getElementById(`detail-${state.openRow}`);
      if (prev) prev.classList.remove('open');
    }
    detail.classList.add('open');
    state.openRow = id;
  }
}

// ── Show read articles ─────────────────────────────────────────────────
async function toggleShowRead() {
  state.showRead = !state.showRead;
  const btn = document.getElementById('show-old-btn');
  btn.classList.toggle('btn-primary', state.showRead);
  btn.classList.toggle('btn-ghost', !state.showRead);
  btn.textContent = t(state.showRead ? 'btn.hideRead' : 'btn.showRead');
  await loadArticles();
}

// ── Compact mode ───────────────────────────────────────────────────────
function toggleCompact() {
  state.compact = !state.compact;
  localStorage.setItem('freshrss-compact', state.compact ? '1' : '0');
  const grid = document.getElementById('articles-grid');
  const btn  = document.getElementById('compact-btn');
  grid.classList.toggle('compact', state.compact);
  btn.classList.toggle('btn-primary', state.compact);
  btn.classList.toggle('btn-ghost', !state.compact);
}

// ── Button loading states ──────────────────────────────────────────────
function setRefreshBtnLoading(on) {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = on;
  btn.innerHTML = on
    ? `<span class="spinner" style="display:inline-block;width:12px;height:12px;border-width:2px"></span> ${t('toast.loading')}`
    : t('btn.refresh');
}

function setRescoreBtnLoading(on) {
  const btn = document.getElementById('rescore-btn');
  btn.disabled = on;
  btn.className = 'btn btn-ghost';
  delete btn.dataset.confirming;
  clearTimeout(btn._confirmTimer);
  btn.innerHTML = on
    ? `<span class="spinner" style="display:inline-block;width:12px;height:12px;border-width:2px"></span> ${t('toast.rescoring')}`
    : t('btn.rescore');
}

// ── Last refresh label ─────────────────────────────────────────────────
function updateLastRefresh(ts) {
  const el = document.getElementById('last-refresh-label');
  if (!el) return;
  if (!ts) { el.textContent = ''; el.className = 'last-refresh'; el.title = ''; return; }
  const diff = Math.floor(Date.now() / 1000 - ts);
  const stale = diff > 10800;
  let text;
  if (diff < 60)         text = t('time.now');
  else if (diff < 3600)  text = t('time.min', { n: Math.floor(diff / 60) });
  else if (diff < 86400) text = t('time.h',   { n: Math.floor(diff / 3600) });
  else                   text = t('time.d',   { n: Math.floor(diff / 86400) });
  el.textContent = stale ? `⚠ ${text}` : text;
  el.className = 'last-refresh' + (stale ? ' stale' : '');
  el.title = stale ? t('stale.title') : '';
}

// ── Keyboard navigation ────────────────────────────────────────────────
function moveFocus(dir) {
  const maxIdx = Math.min(state.filtered.length, state.displayed) - 1;
  if (maxIdx < 0) return;
  const next = Math.max(0, Math.min(maxIdx, state.focusedIdx + dir));

  if (state.focusedIdx >= 0) {
    const curr = state.filtered[state.focusedIdx];
    if (curr) document.querySelector(`.feed-row[data-id="${CSS.escape(curr.id)}"]`)?.classList.remove('focused');
  }

  state.focusedIdx = next;
  const article = state.filtered[next];
  if (!article) return;

  if (next >= state.displayed - 3 && state.filtered.length > state.displayed) {
    state.displayed += 100;
    renderArticles();
  }

  const row = document.querySelector(`.feed-row[data-id="${CSS.escape(article.id)}"]`);
  if (row) { row.classList.add('focused'); row.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
}

// ── Open all links of a day ────────────────────────────────────────────
function openDayLinks(btn) {
  const group = btn.closest('.date-group');
  if (!group) return;
  const ids = new Set(JSON.parse(group.dataset.ids || '[]'));
  const articles = state.articles.filter(a => ids.has(a.id));
  if (!articles.length) return;
  if (articles.length > 10 && !confirm(`Ouvrir ${articles.length} onglets ?`)) return;
  articles.forEach(a => window.open(a.url, '_blank', 'noopener'));
}

// ── Scoring config modal ────────────────────────────────────────────────
async function openScoringModal() {
  if (!_requireAuth()) return;
  const modal = document.getElementById('scoring-modal');
  modal.style.display = 'flex';
  document.getElementById('scoring-topics').innerHTML = '<p style="color:var(--text-3);font-size:13px">Chargement…</p>';

  try {
    const topics = await fetchScoringConfig();
    _renderScoringTopics(topics);
  } catch (e) {
    document.getElementById('scoring-topics').innerHTML =
      `<p style="color:#dc2626">${esc(e.message)}</p>`;
  }

  // Close on overlay click
  modal.onclick = (e) => { if (e.target === modal) closeScoringModal(); };
  document.addEventListener('keydown', _scoringEscHandler);
}

function _scoringEscHandler(e) {
  if (e.key === 'Escape') closeScoringModal();
}

function closeScoringModal() {
  document.getElementById('scoring-modal').style.display = 'none';
  document.removeEventListener('keydown', _scoringEscHandler);
}

function _renderScoringTopics(topics) {
  const container = document.getElementById('scoring-topics');
  if (!Object.keys(topics).length) {
    container.innerHTML = '<p style="color:var(--text-3);font-size:13px">Aucun topic configuré.</p>';
    return;
  }
  container.innerHTML = Object.entries(topics)
    .map(([name, cfg]) => _topicRowHtml(name, cfg))
    .join('');
}

function _topicRowHtml(name, cfg) {
  const kws = Array.isArray(cfg.keywords) ? cfg.keywords.join('\n') : '';
  const weight = typeof cfg.weight === 'number' ? cfg.weight : 1.0;
  return `
    <div class="topic-row">
      <div class="topic-row-header">
        <input type="text" class="topic-name" value="${esc(name)}" placeholder="${esc(t('cfg.ph.name'))}" aria-label="Nom du topic" />
        <input type="number" class="topic-weight" value="${weight}" min="0.1" step="0.1" aria-label="Poids" />
        <button class="btn btn-ghost topic-remove" onclick="removeTopicRow(this)" aria-label="Supprimer ce topic">✕</button>
      </div>
      <div class="topic-keywords-label">${esc(t('cfg.colKeywords'))}</div>
      <textarea class="topic-keywords" placeholder="${esc(t('cfg.ph.keywords'))}" aria-label="Mots-clés">${esc(kws)}</textarea>
    </div>`;
}

function addTopicRow() {
  const container = document.getElementById('scoring-topics');
  // Remove placeholder text if present
  if (container.querySelector('p')) container.innerHTML = '';
  const div = document.createElement('div');
  div.innerHTML = _topicRowHtml('', { keywords: [], weight: 1.0 });
  container.appendChild(div.firstElementChild);
  container.lastElementChild.querySelector('.topic-name')?.focus();
}

function removeTopicRow(btn) {
  btn.closest('.topic-row').remove();
}

function _collectTopics() {
  const topics = {};
  for (const row of document.querySelectorAll('.topic-row')) {
    const name = row.querySelector('.topic-name').value.trim();
    if (!name) continue;
    const weight = parseFloat(row.querySelector('.topic-weight').value) || 1.0;
    const keywords = row.querySelector('.topic-keywords').value
      .split('\n').map(k => k.trim().toLowerCase()).filter(Boolean);
    topics[name] = { keywords, weight };
  }
  return topics;
}

async function saveScoringConfig() {
  const btn = document.getElementById('scoring-save-btn');
  btn.disabled = true;
  try {
    const topics = _collectTopics();
    await updateScoringConfig(topics);
    closeScoringModal();
    // Auto-rescore with new weights
    showToast(t('cfg.saved'));
    _doRescore();
  } catch (e) {
    toastError(e.message);
    btn.disabled = false;
  }
}

// ── Password change modal ───────────────────────────────────────────────
function openPwdModal() {
  if (!_requireAuth()) return;
  const modal = document.getElementById('pwd-modal');
  document.getElementById('pwd-current').value = '';
  document.getElementById('pwd-new').value = '';
  document.getElementById('pwd-confirm').value = '';
  document.getElementById('pwd-error').textContent = '';
  modal.style.display = 'flex';
  document.getElementById('pwd-current').focus();
  modal.onclick = (e) => { if (e.target === modal) closePwdModal(); };
  document.addEventListener('keydown', _pwdEscHandler);
}

function _pwdEscHandler(e) {
  if (e.key === 'Escape') closePwdModal();
}

function closePwdModal() {
  document.getElementById('pwd-modal').style.display = 'none';
  document.removeEventListener('keydown', _pwdEscHandler);
}

async function savePwd() {
  const current = document.getElementById('pwd-current').value;
  const newPwd  = document.getElementById('pwd-new').value;
  const confirm = document.getElementById('pwd-confirm').value;
  const errEl   = document.getElementById('pwd-error');
  errEl.textContent = '';

  if (newPwd !== confirm) {
    errEl.textContent = t('pwd.mismatch');
    return;
  }

  const btn = document.getElementById('pwd-save-btn');
  btn.disabled = true;
  try {
    await changePassword(current, newPwd);
    closePwdModal();
    toastSuccess(t('pwd.ok'));
  } catch (e) {
    const key = e.message === 'current_password_wrong' ? 'pwd.wrongCurrent'
              : e.message === 'password_too_short'     ? 'pwd.tooShort'
              : null;
    errEl.textContent = key ? t(key) : (e.message || t('toast.error'));
    btn.disabled = false;
  }
}

// ── Init ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (state.compact) {
    document.getElementById('articles-grid').classList.add('compact');
    document.getElementById('compact-btn').classList.add('btn-primary');
    document.getElementById('compact-btn').classList.remove('btn-ghost');
  }

  document.getElementById('sort-select').addEventListener('change', e => { state.sort = e.target.value; applyFilters(); });
  const minScoreEl = document.getElementById('min-score');
  minScoreEl.value = state.minScore;
  minScoreEl.addEventListener('input', e => { state.minScore = parseFloat(e.target.value) || 0; localStorage.setItem('freshrss-minscore', state.minScore); applyFilters(); });
  document.getElementById('days-select').addEventListener('change', e => {
    state.days = parseInt(e.target.value);
    loadArticles();
  });
  document.getElementById('search-input').addEventListener('input', e => {
    state.search = e.target.value.trim();
    state.displayed = 100;
    applyFilters();
  });

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); moveFocus(1); }
    else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); moveFocus(-1); }
    else if (e.key === 'o' || e.key === 'Enter') {
      if (state.focusedIdx >= 0) {
        const a = state.filtered[state.focusedIdx];
        if (a) window.open(a.url, '_blank', 'noopener');
      }
    }
    else if (e.key === 'm') {
      if (state.focusedIdx >= 0) {
        const a = state.filtered[state.focusedIdx];
        if (a) markSingleAsRead(a.id, { stopPropagation: () => {}, preventDefault: () => {} });
      }
    }
    else if (e.key === 'r' && !e.ctrlKey && !e.metaKey) triggerRefresh();
    else if (e.key === 'Escape' && state.openRow) toggleDetail(state.openRow);
  });

  fetchMe();
  applyI18n();

  fetchStatus().then(status => {
    updateLastRefresh(status.last_refresh);
    if (status.is_loading) { setRefreshBtnLoading(true); showToast(status.load_progress || t('toast.loading')); startPolling(); }
    else if (status.article_count > 0) loadArticles();
  });

  setInterval(async () => { const s = await fetchStatus(); updateLastRefresh(s.last_refresh); }, 60000);
});
