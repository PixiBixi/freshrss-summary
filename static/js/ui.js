// ── Command Palette commands ───────────────────────────────────────────
const PALETTE_COMMANDS = [
  { icon: '⟳', labelKey: 'btn.refresh',        shortcut: 'R', action: () => { closePalette(); triggerRefresh(); } },
  { icon: '✓', labelKey: 'btn.markVisible',     shortcut: 'M', action: () => { closePalette(); markVisibleAsRead(); } },
  { icon: '⇄', labelKey: 'btn.rescore',         shortcut: '',  action: () => { closePalette(); triggerRescore(); } },
  { icon: '⚙', labelKey: 'btn.scoringCfg',     shortcut: '',  action: () => { closePalette(); openScoringModal(); } },
  { icon: '📅', labelKey: 'palette.period7',    shortcut: '',  action: () => { closePalette(); setDays(7); } },
  { icon: '📅', labelKey: 'palette.period14',   shortcut: '',  action: () => { closePalette(); setDays(14); } },
  { icon: '📅', labelKey: 'palette.period30',   shortcut: '',  action: () => { closePalette(); setDays(30); } },
  { icon: '📅', labelKey: 'palette.periodAll',  shortcut: '',  action: () => { closePalette(); setDays(0); } },
  { icon: '🎨', labelKey: 'palette.accent',     shortcut: '',  action: () => { closePalette(); openOverflowMenu(); } },
  { icon: '🌐', labelKey: 'palette.lang',       shortcut: '',  action: () => { closePalette(); openOverflowMenu(); } },
  { icon: '🔑', labelKey: 'btn.changePassword', shortcut: '',  action: () => { closePalette(); openPwdModal(); } },
  { icon: '⎋',  labelKey: 'palette.logout',     shortcut: '',  action: () => { closePalette(); doLogout(); } },
];

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

// ── Detail panel (mode A) ──────────────────────────────────────────────
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

// ── Compact row expand (mode C) ────────────────────────────────────────
function toggleCompactRow(id) {
  if (state.openRow && state.openRow !== id) {
    const prev = document.getElementById(`cexp-${state.openRow}`);
    const prevRow = document.querySelector(`.compact-row[data-id="${CSS.escape(state.openRow)}"]`);
    if (prev) prev.classList.remove('open');
    if (prevRow) {
      prevRow.classList.remove('compact-expanded');
      const chev = prevRow.querySelector('.compact-chevron');
      if (chev) chev.textContent = '▼';
    }
  }

  const detail = document.getElementById(`cexp-${id}`);
  const row = document.querySelector(`.compact-row[data-id="${CSS.escape(id)}"]`);
  if (!detail || !row) return;

  const isOpen = detail.classList.contains('open');
  if (isOpen) {
    detail.classList.remove('open');
    row.classList.remove('compact-expanded');
    state.openRow = null;
    const chev = row.querySelector('.compact-chevron');
    if (chev) chev.textContent = '▼';
  } else {
    detail.classList.add('open');
    row.classList.add('compact-expanded');
    state.openRow = id;
    const chev = row.querySelector('.compact-chevron');
    if (chev) chev.textContent = '▲';
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
  state.openRow = null;
  const item = document.getElementById('compact-overflow-item');
  if (item) item.style.color = state.compact ? 'var(--accent)' : '';
  closeOverflowMenu();
  renderArticles();
}

// ── Overflow menu ──────────────────────────────────────────────────────
function openOverflowMenu() {
  document.getElementById('overflow-menu').classList.add('open');
  document.getElementById('overflow-btn').setAttribute('aria-expanded', 'true');
  _buildOverflowLang();
  initAccentColor();
}

function closeOverflowMenu() {
  document.getElementById('overflow-menu')?.classList.remove('open');
  document.getElementById('overflow-btn')?.setAttribute('aria-expanded', 'false');
}

function toggleOverflowMenu() {
  const menu = document.getElementById('overflow-menu');
  if (menu.classList.contains('open')) closeOverflowMenu();
  else openOverflowMenu();
}

function _buildOverflowLang() {
  const container = document.getElementById('overflow-lang');
  if (!container) return;
  container.innerHTML = LANGS.map(l =>
    `<button class="overflow-lang-item${l.code === state.lang ? ' active' : ''}"
      onclick="setLang('${l.code}'); closeOverflowMenu()">
      <span>${l.flag}</span><span>${l.label}</span>
    </button>`
  ).join('');
}

// ── Accent color ───────────────────────────────────────────────────────
function setAccentColor(val) {
  document.documentElement.style.setProperty('--accent', val);
  localStorage.setItem('freshrss-accent', val);
}

function resetAccentColor(e) {
  if (e) e.stopPropagation();
  const def = '#5c98a0';
  setAccentColor(def);
  const picker = document.getElementById('accent-picker');
  if (picker) picker.value = def;
}

function initAccentColor() {
  const saved = localStorage.getItem('freshrss-accent') || '#5c98a0';
  document.documentElement.style.setProperty('--accent', saved);
  const picker = document.getElementById('accent-picker');
  if (picker) picker.value = saved;
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
  // rescore btn is now in overflow menu — no DOM button to update
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

// ── Days period ────────────────────────────────────────────────────────
function setDays(n) {
  state.days = n;
  const sel = document.getElementById('days-select');
  if (sel) sel.value = String(n);
  loadArticles();
}

// ── Keyboard navigation ────────────────────────────────────────────────
function _rowSelector(id) {
  return state.compact
    ? `.compact-row[data-id="${CSS.escape(id)}"]`
    : `.feed-row[data-id="${CSS.escape(id)}"]`;
}

function moveFocus(dir) {
  const maxIdx = Math.min(state.filtered.length, state.displayed) - 1;
  if (maxIdx < 0) return;
  const next = Math.max(0, Math.min(maxIdx, state.focusedIdx + dir));

  if (state.focusedIdx >= 0) {
    const curr = state.filtered[state.focusedIdx];
    if (curr) document.querySelector(_rowSelector(curr.id))?.classList.remove('focused');
  }

  state.focusedIdx = next;
  const article = state.filtered[next];
  if (!article) return;

  if (next >= state.displayed - 3 && state.filtered.length > state.displayed) {
    state.displayed += 100;
    renderArticles();
  }

  const row = document.querySelector(_rowSelector(article.id));
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

// ── Command Palette ────────────────────────────────────────────────────
let _paletteFocusIdx = 0;
let _paletteFiltered = [];

function openPalette() {
  const overlay = document.getElementById('cmd-palette');
  if (!overlay) return;
  overlay.style.display = 'flex';
  const input = document.getElementById('palette-input');
  input.value = '';
  _paletteFocusIdx = 0;
  _renderPalette('');
  setTimeout(() => input.focus(), 0);
}

function closePalette() {
  const overlay = document.getElementById('cmd-palette');
  if (overlay) overlay.style.display = 'none';
}

function _renderPalette(query) {
  const q = query.toLowerCase().trim();
  _paletteFiltered = PALETTE_COMMANDS.filter(c => {
    const label = t(c.labelKey).toLowerCase();
    return !q || label.includes(q) || c.icon.includes(q);
  });
  if (_paletteFocusIdx >= _paletteFiltered.length) _paletteFocusIdx = 0;

  const list = document.getElementById('palette-list');
  list.innerHTML = _paletteFiltered.map((c, i) => `
    <div class="palette-item${i === _paletteFocusIdx ? ' focused' : ''}"
      onclick="_execPaletteIdx(${i})"
      onmouseover="_paletteFocusIdx=${i}; _highlightPalette()">
      <span class="palette-item-label">${esc(t(c.labelKey))}</span>
      ${c.shortcut ? `<span class="palette-shortcut">${esc(c.shortcut)}</span>` : ''}
    </div>`).join('');
}

function _highlightPalette() {
  document.querySelectorAll('.palette-item').forEach((el, i) => {
    el.classList.toggle('focused', i === _paletteFocusIdx);
  });
}

function _execPaletteIdx(idx) {
  if (_paletteFiltered[idx]) _paletteFiltered[idx].action();
}

// ── Init ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initAccentColor();

  // Compact mode state indicator
  if (state.compact) {
    const item = document.getElementById('compact-overflow-item');
    if (item) item.style.color = 'var(--accent)';
  }

  document.getElementById('sort-select').addEventListener('change', e => { state.sort = e.target.value; applyFilters(); });
  const minScoreEl = document.getElementById('min-score');
  const minScoreVal = document.getElementById('min-score-val');
  minScoreEl.value = state.minScore;
  if (minScoreVal) minScoreVal.textContent = state.minScore;
  minScoreEl.addEventListener('input', e => {
    state.minScore = parseFloat(e.target.value) || 0;
    if (minScoreVal) minScoreVal.textContent = state.minScore;
    localStorage.setItem('freshrss-minscore', state.minScore);
    applyFilters();
  });
  document.getElementById('days-select').addEventListener('change', e => {
    state.days = parseInt(e.target.value);
    loadArticles();
  });
  document.getElementById('search-input').addEventListener('input', e => {
    state.search = e.target.value.trim();
    state.displayed = 100;
    applyFilters();
  });

  document.getElementById('palette-input')?.addEventListener('input', e => {
    _paletteFocusIdx = 0;
    _renderPalette(e.target.value);
  });

  document.getElementById('cmd-palette')?.addEventListener('click', closePalette);

  // Close overflow menu on outside click
  document.addEventListener('click', e => {
    if (!e.target.closest('.overflow-wrap')) closeOverflowMenu();
  });

  document.addEventListener('keydown', (e) => {
    // ⌘K / Ctrl+K — toggle palette
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      const palette = document.getElementById('cmd-palette');
      if (palette && palette.style.display !== 'none') closePalette();
      else openPalette();
      return;
    }

    // Palette navigation (when open)
    const paletteOpen = document.getElementById('cmd-palette')?.style.display !== 'none';
    if (paletteOpen) {
      if (e.key === 'Escape') { closePalette(); return; }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        _paletteFocusIdx = Math.min(_paletteFocusIdx + 1, _paletteFiltered.length - 1);
        _highlightPalette();
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        _paletteFocusIdx = Math.max(_paletteFocusIdx - 1, 0);
        _highlightPalette();
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        _execPaletteIdx(_paletteFocusIdx);
        return;
      }
      return;
    }

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
      if (state.authenticated && state.focusedIdx >= 0) {
        const a = state.filtered[state.focusedIdx];
        if (a) markSingleAsRead(a.id, { stopPropagation: () => {}, preventDefault: () => {} });
      }
    }
    else if (e.key === 'r' && !e.ctrlKey && !e.metaKey) triggerRefresh();
    else if (e.key === 'Escape' && state.openRow) {
      if (state.compact) toggleCompactRow(state.openRow);
      else toggleDetail(state.openRow);
    }
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
