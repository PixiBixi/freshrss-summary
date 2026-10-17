// ── Toast ──────────────────────────────────────────────────────────────
// One toast at a time. `action` is a callback shown as a link button (undo).
let _toastTimeout = null;
let _toastAction = null;

function toast(msg, o = {}) {
  const el = byId('toast');
  el.className = 'toast on' + (o.err ? ' err' : '');
  _toastAction = o.action || null;
  el.innerHTML = (o.spin ? '<span class="spin" aria-hidden="true"></span>' : '')
    + `<span class="tt">${esc(msg)}</span>`
    + (o.action ? `<button type="button" data-toast="action">${esc(o.label || t('toast.undo'))}</button>` : '')
    + (o.spin ? '' : `<button type="button" class="tx" data-toast="close" aria-label="${esc(t('toast.close'))}">${ic('x')}</button>`);
  if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }
  if (!o.sticky) _toastTimeout = setTimeout(dismissToast, o.ms || (o.err ? 6000 : 4000));
}

function showToast(msg) { toast(msg, { spin: true, sticky: true }); }

function updateToast(msg) {
  const tt = document.querySelector('#toast .tt');
  if (tt) tt.textContent = msg;
}

function toastSuccess(msg) { toast(msg); }

function toastError(msg) { toast(msg, { err: true }); }

function dismissToast() {
  byId('toast').classList.remove('on');
  _toastAction = null;
  if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }
}

function progress(p) {
  const l = byId('sync-line');
  l.style.opacity = p >= 100 ? 0 : 1;
  l.style.width = Math.min(p, 100) + '%';
  if (p >= 100) setTimeout(() => { l.style.width = '0'; }, 400);
}

// ── Utility ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Only http(s) URLs are linkable: blocks javascript:/data: URLs coming from feeds.
function safeUrl(u) { return /^https?:\/\//i.test(String(u ?? '')) ? String(u) : '#'; }

function openUrl(u) {
  const url = safeUrl(u);
  if (url !== '#') window.open(url, '_blank', 'noopener');
}

// ── Button loading states ──────────────────────────────────────────────
function setRefreshBtnLoading(on) { state.syncing = on; renderToolbar(); }

function setRescoreBtnLoading(on) { state.rescoring = on; }

// ── View, filters, display ─────────────────────────────────────────────
function _resetListScroll() { const l = byId('list'); l.scrollTop = 0; _lastListTop = 0; }

function setView(v) {
  if (!state.authenticated && v !== 'triage') return;
  const reload = (v === 'read') !== (state.view === 'read');
  state.keep.clear(); state.view = v; state.sel = 0; state.open = null; state.side = false; state.shown = PAGE_SIZE;
  if (reload) { state.everLoaded = false; loadArticles(); }
  render(); _resetListScroll();
}

function setFilter(patch) {
  Object.assign(state, patch);
  state.keep.clear(); state.sel = 0; state.shown = PAGE_SIZE;
  render(); _resetListScroll();
}

function resetFilters() {
  setFilter({ topic: null, search: '', minScore: 0, sev: null });
  lsSet('freshrss-minscore', '0');
}

function setDays(n) {
  state.days = n; lsSet('freshrss-days', String(n));
  state.keep.clear(); state.sel = 0; state.shown = PAGE_SIZE;
  renderSidebar(); loadArticles();
}

function setSort(k) {
  if (state.sortKey === k) state.sortDir = -state.sortDir;
  else { state.sortKey = k; state.sortDir = (k === 'burn' || k === 'age') ? -1 : 1; }
  lsSet('freshrss-sort', `${state.sortKey}:${state.sortDir}`);
  state.sel = 0; render();
}

function setDensity(d) { document.documentElement.dataset.density = d; lsSet('freshrss-density', d); render(); }

function setTheme(th) { document.documentElement.dataset.theme = th; lsSet('theme', th); render(); }

function _onAccent(hex) {
  const n = parseInt(hex.slice(1), 16);
  const lum = (0.299 * (n >> 16) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255)) / 255;
  return lum > 0.6 ? '#111' : '#fff';
}

function setAccent(c, persist = true) {
  const r = document.documentElement;
  if (c && /^#[0-9a-fA-F]{6}$/.test(c)) { r.style.setProperty('--accent', c); r.style.setProperty('--on-accent', _onAccent(c)); }
  else { r.style.removeProperty('--accent'); r.style.removeProperty('--on-accent'); c = null; }
  if (persist) lsSet('accent', c);
}

function move(delta) {
  const l = visibleList();
  if (!l.length) return;
  state.sel = Math.max(0, Math.min(l.length - 1, state.sel + delta));
  // Prefetch the next page when the cursor reaches the end of what is shown.
  if (state.sel >= l.length - 1 && _view.list.length > state.shown) state.shown += PAGE_SIZE;
  if (state.open) state.open = l[state.sel].id;
  render();
  document.querySelector('.row[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
}

// ── Open all links of a day ────────────────────────────────────────────
function openDayLinks(key) {
  const articles = visibleList().filter(a => dayKey(a.published) === key && safeUrl(a.url) !== '#');
  if (!articles.length) return;
  if (articles.length > 10 && !confirm(t('confirm.openTabs', { n: articles.length }))) return;
  articles.forEach(a => window.open(safeUrl(a.url), '_blank', 'noopener'));
}

// ── Commands (buttons, menu, palette, keyboard) ────────────────────────
function command(c) {
  switch (c) {
    case 'sync': triggerRefresh(); break;
    case 'reload': loadArticles(); break;
    case 'menu': state.menu = !state.menu; state.rescoreArm = false; renderMenu(); break;
    case 'pin': state.pin = !state.pin; state.open = null; lsSet('freshrss-pin', state.pin ? '1' : '0'); render(); break;
    case 'collapse': state.collapse = !state.collapse; lsSet('freshrss-collapse', state.collapse ? '1' : '0'); render(); break;
    case 'palette': openPalette(); break;
    case 'cfg': openScoringModal('topics'); break;
    case 'cfgfeeds': openScoringModal('feeds'); break;
    case 'pwd': openPwdModal(); break;
    case 'help': openHelp(); break;
    case 'logout': doLogout(); break;
    case 'login': window.location.href = '/login'; break;
    case 'autoread':
      state.autoRead = !state.autoRead; lsSet('freshrss-autoread', state.autoRead ? '1' : '0'); renderMenu();
      toastSuccess(t(state.autoRead ? 'toast.autoReadOn' : 'toast.autoReadOff'));
      break;
    case 'rescore': triggerRescore(); break;
    case 'rescore-now': _doRescore(); break;
    case 'ackvisible': if (state.view === 'triage') markVisibleAsRead(); break;
    case 'reset': resetFilters(); break;
    case 'clearq': setFilter({ search: '' }); byId('q').focus(); break;
    case 'more': state.shown += PAGE_SIZE; renderMain(); break;
    case 'prev': move(-1); break;
    case 'next': move(1); break;
    case 'density': setDensity(document.documentElement.dataset.density === 'scan' ? 'read' : 'scan'); break;
    case 'theme': setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'); break;
    case 'menu-open': state.menu = true; renderMenu(); break;
  }
}

function _closeMenu() { if (state.menu) { state.menu = false; state.rescoreArm = false; renderMenu(); } }

function _articleAction(act, id) {
  if (act === 'ack') markSingleAsRead(id);
  else if (act === 'bm') toggleBookmark(id);
  else if (act === 'sn') snoozeArticle(id);
  else if (act === 'unack') markUnread([id]);
  else if (act === 'wake') cancelSnooze(id);
}

// ── Modal layer ────────────────────────────────────────────────────────
// One modal at a time in #layer; focus returns to the opener on close.
const M = { kind: null, opener: null };

function _layer(html, cls = '') {
  byId('layer').innerHTML = html ? `<div class="ov ${cls}" data-ovl>${html}</div>` : '';
}

function closeModal() {
  M.kind = null; _layer('');
  if (M.opener && document.contains(M.opener)) M.opener.focus();
  M.opener = null;
}

function _openModal(kind) {
  if (!M.kind) M.opener = document.activeElement;
  M.kind = kind; state.menu = false; renderMenu();
}

function _modalHead(id, titleKey) {
  return `<div class="mh"><h2 id="${id}">${esc(t(titleKey))}</h2><button type="button" class="btn ghost ico x" data-mclose aria-label="${esc(t('modal.close'))}">${ic('x')}</button></div>`;
}

// Tab stays inside the open dialog.
function _trapFocus(e) {
  const dlg = document.querySelector('#layer [role="dialog"]');
  if (!dlg) return;
  const f = [...dlg.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled && x.offsetParent);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
}

// ── Password change modal ──────────────────────────────────────────────
function openPwdModal() {
  if (!_requireAuth()) return;
  _openModal('pwd');
  _layer(`<div class="modal" role="dialog" aria-modal="true" aria-labelledby="pwd-t">${_modalHead('pwd-t', 'pwd.title')}`
    + `<form class="mb form" id="pwd-form" novalidate>`
    + `<label class="field">${esc(t('pwd.current'))}<input class="input" type="password" id="pwd-current" autocomplete="current-password"></label>`
    + `<label class="field">${esc(t('pwd.new'))}<input class="input" type="password" id="pwd-new" autocomplete="new-password"><span class="hint">${esc(t('pwd.hint'))}</span></label>`
    + `<label class="field">${esc(t('pwd.confirm'))}<input class="input" type="password" id="pwd-confirm" autocomplete="new-password"></label>`
    + `<p class="form-err" id="pwd-error" role="alert"></p></form>`
    + `<div class="mf"><span class="sp"></span><button type="button" class="btn" data-mclose>${esc(t('pwd.cancel'))}</button>`
    + `<button type="button" class="btn primary" id="pwd-save-btn" data-cmd-modal="pwdsave">${esc(t('pwd.save'))}</button></div></div>`);
  byId('pwd-current').focus();
}

async function savePwd() {
  const current = byId('pwd-current').value;
  const newPwd  = byId('pwd-new').value;
  const confirmPwd = byId('pwd-confirm').value;
  const errEl   = byId('pwd-error');
  errEl.textContent = '';
  if (!current) { errEl.textContent = t('pwd.needCurrent'); return; }
  if (newPwd.length < 8) { errEl.textContent = t('pwd.tooShort'); return; }
  if (newPwd !== confirmPwd) { errEl.textContent = t('pwd.mismatch'); return; }

  const btn = byId('pwd-save-btn');
  btn.disabled = true;
  try {
    await changePassword(current, newPwd);
    closeModal();
    toastSuccess(t('pwd.ok'));
  } catch (e) {
    const key = e.message === 'current_password_wrong' ? 'pwd.wrongCurrent'
              : e.message === 'password_too_short'     ? 'pwd.tooShort'
              : null;
    errEl.textContent = key ? t(key) : (e.message || t('toast.error'));
    btn.disabled = false;
  }
}

// ── Help modal ─────────────────────────────────────────────────────────
const HELP_KEYS = [
  ['help.nav'], ['j / k', 'help.next'], ['Enter', 'help.enter'], ['o', 'help.open'], ['Esc', 'help.esc'],
  ['help.triage'], ['m', 'help.ack'], ['Shift M', 'help.ackAll'], ['u', 'help.undo'], ['s', 'help.snooze'], ['b', 'help.bookmark'],
  ['help.filters'], ['/', 'help.search'], ['1 / 2 / 3', 'help.sev'], ['0', 'help.reset'],
  ['help.display'], ['⌘K', 'help.palette'], ['v', 'help.density'], ['p', 'help.pin'], ['[', 'help.sidebar'], ['r', 'help.sync'], ['?', 'help.help'],
];

function openHelp() {
  _openModal('help');
  _layer(`<div class="modal" role="dialog" aria-modal="true" aria-labelledby="help-t">${_modalHead('help-t', 'help.title')}<div class="mb"><div class="keys">`
    + HELP_KEYS.map(k => k.length === 1 ? `<h3>${esc(t(k[0]))}</h3>` : `<kbd>${esc(k[0])}</kbd><span>${esc(t(k[1]))}</span>`).join('')
    + '</div></div></div>');
  document.querySelector('#layer [data-mclose]')?.focus();
}

// ── Command Palette ────────────────────────────────────────────────────
const P = { ids: [], sel: 0 };

// [group, label key, shortcut, command id, auth only]
function _paletteCommands() {
  const c = [
    ['pal.gActions', 'pal.sync', 'r', 'sync', true], ['pal.gActions', 'pal.ackVisible', '⇧M', 'ackvisible', true], ['pal.gActions', 'pal.rescore', '', 'rescore-now', true],
    ['pal.gViews', 'pal.vTriage', '', 'v:triage'], ['pal.gViews', 'pal.vBookmarks', '', 'v:bm', true], ['pal.gViews', 'pal.vSnoozed', '', 'v:sn', true], ['pal.gViews', 'pal.vRead', '', 'v:read', true],
    ['pal.gFilters', 'pal.p1', '1', 'sev:crit'], ['pal.gFilters', 'pal.p2', '2', 'sev:warn'], ['pal.gFilters', 'pal.p3', '3', 'sev:ok'], ['pal.gFilters', 'pal.reset', '0', 'reset'],
    ['pal.gFilters', 'pal.period7', '', 'd:7'], ['pal.gFilters', 'pal.period14', '', 'd:14'], ['pal.gFilters', 'pal.period30', '', 'd:30'], ['pal.gFilters', 'pal.periodAll', '', 'd:0'],
    ['pal.gDisplay', 'pal.density', 'v', 'density'], ['pal.gDisplay', 'pal.pin', 'p', 'pin'], ['pal.gDisplay', 'pal.sidebar', '[', 'collapse'], ['pal.gDisplay', 'pal.theme', '', 'theme'], ['pal.gDisplay', 'pal.accent', '', 'menu-open'],
    ['pal.gConfig', 'pal.topics', '', 'cfg', true], ['pal.gConfig', 'pal.feeds', '', 'cfgfeeds', true], ['pal.gConfig', 'pal.lang', '', 'menu-open'],
    ['pal.gAccount', 'btn.changePassword', '', 'pwd', true], ['pal.gAccount', 'menu.shortcuts', '?', 'help'],
    ['pal.gAccount', state.authenticated ? 'btn.logout' : 'btn.login', '', state.authenticated ? 'logout' : 'login'],
  ].filter(x => state.authenticated || !x[4]).map(x => [t(x[0]), t(x[1]), x[2], x[3]]);
  for (const [name] of topicCounts()) c.push([t('pal.gTopics'), t('pal.topic', { t: name }), '', 't:' + name]);
  return c;
}

function openPalette() {
  if (M.kind === 'pal') { closeModal(); return; }
  _openModal('pal'); P.sel = 0;
  _layer(`<div class="modal pal" role="dialog" aria-modal="true" aria-label="${esc(t('pal.label'))}"><div class="pin">${ic('search')}`
    + `<input id="pal-q" placeholder="${esc(t('pal.placeholder'))}" autocomplete="off" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-label="${esc(t('pal.label'))}"></div>`
    + '<div class="pl" id="pal-list" role="listbox"></div>'
    + `<div class="foot"><span><span class="kbd">↑↓</span> ${esc(t('pal.navigate'))}</span><span><span class="kbd">↵</span> ${esc(t('pal.run'))}</span><span><span class="kbd">esc</span> ${esc(t('pal.close'))}</span></div></div>`);
  _renderPalette('');
  byId('pal-q').focus();
}

function _renderPalette(query) {
  const q = query.toLowerCase().trim();
  const c = _paletteCommands().filter(x => !q || x[1].toLowerCase().includes(q) || x[0].toLowerCase().includes(q));
  const arts = q.length > 1 ? state.articles.filter(a => (a.title || '').toLowerCase().includes(q)).slice(0, 6) : [];
  P.ids = c.map(x => x[3]).concat(arts.map(a => 'a:' + a.id));
  if (P.sel >= P.ids.length) P.sel = 0;
  let h = '', g = null, i = 0;
  for (const x of c) {
    if (x[0] !== g) { h += `<div class="g">${esc(x[0])}</div>`; g = x[0]; }
    h += `<button type="button" class="c" role="option" id="pal-o${i}" data-pal="${i}" aria-selected="${i === P.sel}">${esc(x[1])}${x[2] ? `<span class="k">${esc(x[2])}</span>` : ''}</button>`; i++;
  }
  if (arts.length) {
    h += `<div class="g">${esc(t('pal.gArticles'))}</div>`;
    for (const a of arts) {
      h += `<button type="button" class="c" role="option" id="pal-o${i}" data-pal="${i}" aria-selected="${i === P.sel}"><span class="tt">${esc(a.title)}</span><span class="meta ${sevOf(a.score)}">${burn(a.score)}</span></button>`; i++;
    }
  }
  byId('pal-list').innerHTML = h || `<div class="empty">${esc(t('pal.none', { q }))}</div>`;
  byId('pal-q').setAttribute('aria-activedescendant', P.ids.length ? 'pal-o' + P.sel : '');
  document.querySelector('.pal .c[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
}

function _runPalette(i) {
  const id = P.ids[i];
  if (!id) return;
  closeModal();
  if (id.startsWith('a:')) {
    const aid = id.slice(2), art = state.articles.find(a => a.id === aid);
    if (!art) return;
    state.view = isAcked(art) && state.authenticated ? 'read' : 'triage';
    state.keep.clear(); state.topic = null; state.search = ''; state.sev = null; state.minScore = 0;
    recompute();
    const ix = _view.list.indexOf(art);
    if (ix >= 0) { state.shown = Math.max(state.shown, ix + 1); state.sel = ix; state.open = aid; }
    render(); rowEl(aid)?.scrollIntoView({ block: 'center' });
    return;
  }
  if (id.startsWith('v:')) { setView(id.slice(2)); return; }
  if (id.startsWith('sev:')) { setFilter({ sev: id.slice(4) }); return; }
  if (id.startsWith('d:')) { setDays(+id.slice(2)); return; }
  if (id.startsWith('t:')) { if (state.view !== 'triage') setView('triage'); setFilter({ topic: id.slice(2) }); return; }
  command(id);
}

// ── Scoring config modal ───────────────────────────────────────────────
// Draft edited in memory; nothing is sent before "Save and rescore".
const C = { tab: 'topics', topic: null, draft: null, fw: null, feeds: [], fq: '' };

async function openScoringModal(tab = 'topics') {
  if (!_requireAuth()) return;
  _openModal('cfg');
  _layer(`<div class="modal wide" role="dialog" aria-modal="true" aria-labelledby="cfg-t">${_modalHead('cfg-t', 'cfg.title')}<div class="mb"><p class="hint">${esc(t('cfg.loading'))}</p></div></div>`, 'cfg');
  try {
    const [cfg, feedsResp] = await Promise.all([fetchScoringConfig(), fetchFeeds()]);
    if (M.kind !== 'cfg') return;
    C.tab = tab; C.fq = '';
    C.draft = JSON.parse(JSON.stringify(cfg.topics || {}));
    C.fw = { ...(cfg.feed_weights || {}) };
    C.feeds = [...new Set([...(feedsResp.feeds || []), ...Object.keys(C.fw)])];
    if (!C.draft[C.topic]) C.topic = Object.keys(C.draft)[0] || null;
    _drawCfg();
  } catch (e) {
    if (M.kind === 'cfg') document.querySelector('#layer .mb').innerHTML = `<p class="form-err">${esc(e.message)}</p>`;
  }
}

function _kwTotal(d) { return Object.values(d).reduce((n, x) => n + (x.keywords || []).length, 0); }

function _fwAdjusted() { return Object.keys(C.fw).filter(k => Math.abs(C.fw[k] - 1) > 0.001).length; }

function _cfgTopicsBody() {
  const d = C.draft, names = Object.keys(d), tp = d[C.topic];
  const list = names.map(n => `<button type="button" class="tpc" role="option" data-tpc="${esc(n)}" aria-selected="${n === C.topic}">`
    + `<span class="nm">${esc(n || t('cfg.unnamed'))}</span><span class="wt">×${(+d[n].weight || 1).toFixed(2)}</span><span class="kc">${esc(t('cfg.kwCount', { n: (d[n].keywords || []).length }))}</span></button>`).join('')
    + `<button type="button" class="btn ghost add" data-cfg="addtopic">${ic('plus')}${esc(t('cfg.addTopic'))}</button>`;
  if (!tp) return `<div class="cfg-grid"><div class="cfg-list" role="listbox" aria-label="${esc(t('cfg.tabTopics'))}">${list}</div><div class="cfg-ed"><p class="hint">${esc(t('cfg.noTopics'))}</p></div></div>`;
  const w = +tp.weight || 1;
  return `<div class="cfg-grid"><div class="cfg-list" role="listbox" aria-label="${esc(t('cfg.tabTopics'))}">${list}</div><div class="cfg-ed">`
    + `<div class="two"><label class="field">${esc(t('cfg.ph.name'))}<input class="input" id="cfg-name" value="${esc(C.topic)}"></label>`
    + `<div class="field">${esc(t('cfg.weight'))}<div class="wrow"><input type="range" id="cfg-w" min="0.1" max="3" step="0.05" value="${w}" aria-label="${esc(t('cfg.weight'))}">`
    + `<input class="input" id="cfg-wn" type="number" min="0.1" max="10" step="0.05" value="${w}" aria-label="${esc(t('cfg.weightValue'))}"></div></div></div>`
    + `<div class="field"><span>${esc(t('cfg.colKeywords'))} <span class="hint">${esc(t('cfg.kwHint'))}</span></span><div class="chips">`
    + (tp.keywords || []).map((k, i) => `<span class="ch">${esc(k)}<button type="button" data-kwdel="${i}" aria-label="${esc(t('cfg.kwRemove', { k }))}">${ic('x')}</button></span>`).join('')
    + `<input id="cfg-kw" placeholder="${esc(t('cfg.ph.keywords'))}" aria-label="${esc(t('cfg.ph.keywords'))}"></div></div>`
    + `<div class="danger-zone"><button type="button" class="btn danger" data-cfg="deltopic">${esc(t('cfg.delTopic', { t: C.topic }))}</button></div></div></div>`;
}

function _cfgFeedsBody() {
  const unread = new Map();
  for (const a of state.articles) if (!isAcked(a)) unread.set(a.feed_title, (unread.get(a.feed_title) || 0) + 1);
  const q = C.fq.toLowerCase();
  const feeds = C.feeds.filter(f => !q || f.toLowerCase().includes(q))
    .sort((a, b) => (C.fw[b] ?? 1) - (C.fw[a] ?? 1) || a.localeCompare(b));
  const loc = _locale();
  const rows = feeds.map(f => {
    const w = C.fw[f] ?? 1, cls = w > 1.001 ? 'up' : w < 0.999 ? 'down' : 'def';
    return `<div class="frow"><span class="nm" title="${esc(f)}">${esc(f)}</span><span class="n">${(unread.get(f) || 0).toLocaleString(loc)}</span>`
      + `<span class="step"><button type="button" data-fstep="-" data-feed="${esc(f)}" aria-label="${esc(t('cfg.decrease'))}">-</button>`
      + `<input data-fin="${esc(f)}" type="number" min="0.1" max="10" step="0.1" value="${+w.toFixed(2)}" aria-label="${esc(t('cfg.multFor', { f }))}">`
      + `<button type="button" data-fstep="+" data-feed="${esc(f)}" aria-label="${esc(t('cfg.increase'))}">+</button></span>`
      + `<span class="eff ${cls}">${esc(t('cfg.eff.' + cls))}</span>`
      + (cls !== 'def' ? `<button type="button" class="btn ghost ico" data-freset="${esc(f)}" aria-label="${esc(t('cfg.resetFeed'))}" title="${esc(t('cfg.resetFeed'))}">${ic('undo')}</button>` : '<span></span>')
      + '</div>';
  }).join('');
  return `<div class="feeds"><div class="ftool"><label class="search">${ic('search')}<input id="cfg-fq" type="search" placeholder="${esc(t('cfg.filterFeeds'))}" value="${esc(C.fq)}" aria-label="${esc(t('cfg.filterFeeds'))}"></label><span class="hint">${esc(t('cfg.feedsHint'))}</span></div>`
    + `<div class="frow h"><span>${esc(t('cfg.colFeed'))}</span><span class="n">${esc(t('cfg.colUnread'))}</span><span>${esc(t('cfg.colMult'))}</span><span class="eff">${esc(t('cfg.colEffect'))}</span><span></span></div>`
    + (rows || `<p class="hint pad">${esc(t('cfg.noFeeds'))}</p>`) + '</div>';
}

function _drawCfg() {
  const names = Object.keys(C.draft), fwN = _fwAdjusted();
  const focus = document.activeElement?.id;
  _layer(`<div class="modal wide" role="dialog" aria-modal="true" aria-labelledby="cfg-t">${_modalHead('cfg-t', 'cfg.title')}`
    + `<div class="tabs" role="tablist"><button type="button" role="tab" data-tab="topics" aria-selected="${C.tab === 'topics'}">${esc(t('cfg.tabTopics'))}<span>${names.length}</span></button>`
    + `<button type="button" role="tab" data-tab="feeds" aria-selected="${C.tab === 'feeds'}">${esc(t('cfg.tabFeeds'))}<span>${esc(t('cfg.adjusted', { n: fwN }))}</span></button></div>`
    + `<div class="mb flush">${C.tab === 'topics' ? _cfgTopicsBody() : _cfgFeedsBody()}</div>`
    + `<div class="mf"><span class="stat">${esc(t('cfg.footer', { t: names.length, k: _kwTotal(C.draft), f: fwN }))}</span><span class="sp"></span>`
    + `<button type="button" class="btn" data-mclose>${esc(t('cfg.cancel'))}</button>`
    + `<button type="button" class="btn primary" id="cfg-save" data-cfg="save">${ic('redo')}${esc(t('cfg.save'))}</button></div></div>`, 'cfg');
  if (focus) byId(focus)?.focus();
}

function _cfgAction(a) {
  if (a === 'addtopic') {
    let n = t('cfg.newTopic'), k = 2;
    while (C.draft[n]) n = `${t('cfg.newTopic')} ${k++}`;
    C.draft[n] = { keywords: [], weight: 1 }; C.topic = n; _drawCfg(); byId('cfg-name')?.select();
  } else if (a === 'deltopic') {
    delete C.draft[C.topic]; C.topic = Object.keys(C.draft)[0] || null; _drawCfg();
  } else if (a === 'save') saveScoringConfig();
}

function _renameTopic(nn) {
  nn = nn.trim();
  if (!nn || nn === C.topic || C.draft[nn]) { _drawCfg(); return; }
  const o = {};
  for (const k of Object.keys(C.draft)) o[k === C.topic ? nn : k] = C.draft[k];
  C.draft = o; C.topic = nn; _drawCfg();
}

async function saveScoringConfig() {
  const name = byId('cfg-name');
  if (name && name.value.trim() !== C.topic) _renameTopic(name.value);
  const btn = byId('cfg-save');
  if (btn) btn.disabled = true;
  const fw = {};
  for (const [k, v] of Object.entries(C.fw)) if (Math.abs(v - 1) > 0.001) fw[k] = v;
  try {
    await updateScoringConfig(C.draft, fw);
    closeModal();
    showToast(t('cfg.saved'));
    _doRescore();
  } catch (e) {
    toastError(e.message);
    if (byId('cfg-save')) byId('cfg-save').disabled = false;
  }
}

// ── Delegated events (no inline JS built from data) ────────────────────
function _onClick(e) {
  const tgt = e.target.closest('button, a[data-cmd], [data-i], [data-side], [data-ovl]');
  if (state.menu && !e.target.closest('#menu-pop') && !e.target.closest('#menu-btn')) _closeMenu();
  if (!tgt) return;
  const ds = tgt.dataset;
  if (tgt.hasAttribute('data-ovl')) { if (e.target === tgt) closeModal(); return; }
  if (ds.toast) {
    const fn = _toastAction; dismissToast();
    if (ds.toast === 'action' && fn) fn();
    return;
  }
  if (tgt.hasAttribute('data-mclose')) { closeModal(); return; }
  if (ds.cmdModal === 'pwdsave') { savePwd(); return; }
  if (ds.cfg) { _cfgAction(ds.cfg); return; }
  if (ds.cmd) { e.preventDefault(); command(ds.cmd); return; }
  if (ds.pal !== undefined) { _runPalette(+ds.pal); return; }
  if (ds.tab) { C.tab = ds.tab; _drawCfg(); return; }
  if (ds.tpc !== undefined) {
    const nm = byId('cfg-name');
    if (nm && nm.value.trim() !== C.topic) _renameTopic(nm.value);
    C.topic = ds.tpc; _drawCfg(); return;
  }
  if (ds.kwdel !== undefined) { C.draft[C.topic].keywords.splice(+ds.kwdel, 1); _drawCfg(); byId('cfg-kw')?.focus(); return; }
  if (ds.fstep) {
    const w = (C.fw[ds.feed] ?? 1) + (ds.fstep === '+' ? 0.1 : -0.1);
    C.fw[ds.feed] = Math.max(0.1, Math.min(10, Math.round(w * 10) / 10)); _drawCfg(); return;
  }
  if (ds.freset) { delete C.fw[ds.freset]; _drawCfg(); return; }
  if (ds.dens) { setDensity(ds.dens); return; }
  if (ds.theme) { setTheme(ds.theme); return; }
  if (ds.accent !== undefined) { setAccent(ds.accent || null); renderMenu(); return; }
  if (ds.lang) { setLang(ds.lang); return; }
  if (ds.view) { if (!tgt.disabled) setView(ds.view); return; }
  if (ds.sort) { setSort(ds.sort); return; }
  if (ds.sev !== undefined) { setFilter({ sev: ds.sev && state.sev !== ds.sev ? ds.sev : null, open: null }); return; }
  if (ds.topic !== undefined) {
    if (state.view !== 'triage') { state.view = 'triage'; state.open = null; }
    state.side = false;
    setFilter({ topic: state.topic === ds.topic ? null : ds.topic, open: null }); return;
  }
  if (ds.days !== undefined) { setDays(+ds.days); return; }
  if (ds.clear) {
    if (ds.clear === 'min') lsSet('freshrss-minscore', '0');
    setFilter({ topic: ds.clear === 'topic' ? null : state.topic, minScore: ds.clear === 'min' ? 0 : state.minScore, search: ds.clear === 'q' ? '' : state.search });
    return;
  }
  if (ds.dact) { if (ds.dact === 'ack') markDayAsRead(ds.day); else openDayLinks(ds.day); return; }
  if (ds.act) { e.stopPropagation(); _articleAction(ds.act, ds.id); return; }
  if (tgt.hasAttribute('data-close')) { state.open = null; renderPanel(); return; }
  if (tgt.hasAttribute('data-side')) { state.side = !state.side; _shellClasses(); return; }
  if (ds.i !== undefined) { state.sel = +ds.i; state.open = ds.id; render(); }
}

function _onInput(e) {
  const el = e.target, id = el.id;
  if (id === 'q') { state.search = el.value.trim(); state.keep.clear(); state.sel = 0; state.shown = PAGE_SIZE; renderMain(); }
  else if (id === 'min-score') {
    state.minScore = +el.value; state.sel = 0; state.keep.clear();
    byId('min-val').textContent = burn(state.minScore);
    lsSet('freshrss-minscore', String(state.minScore));
    renderMain();
  }
  else if (id === 'accent-input') setAccent(el.value, false);
  else if (id === 'pal-q') { P.sel = 0; _renderPalette(el.value); }
  else if (id === 'cfg-w' || id === 'cfg-wn') {
    const v = Math.max(0.1, Math.min(10, +el.value || 1));
    C.draft[C.topic].weight = v;
    const other = byId(id === 'cfg-w' ? 'cfg-wn' : 'cfg-w'); if (other) other.value = v;
    const w = document.querySelector('.tpc[aria-selected="true"] .wt'); if (w) w.textContent = '×' + v.toFixed(2);
  }
  else if (id === 'cfg-name') {
    const nm = document.querySelector('.tpc[aria-selected="true"] .nm'); if (nm) nm.textContent = el.value || t('cfg.unnamed');
  }
  else if (id === 'cfg-fq') { C.fq = el.value; _drawCfg(); }
  else if (el.dataset.fin) { const v = +el.value; if (v >= 0.1 && v <= 10) C.fw[el.dataset.fin] = v; }
}

function _onChange(e) {
  const el = e.target;
  if (el.id === 'accent-input') { setAccent(el.value); renderMenu(); }
  else if (el.id === 'cfg-name') _renameTopic(el.value);
  else if (el.dataset.fin) _drawCfg();
  else if (el.id === 'min-score') renderSidebar();
}

function _onKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); return; }
  if (M.kind) {
    if (e.key === 'Escape') { e.preventDefault(); closeModal(); return; }
    if (e.key === 'Tab') { _trapFocus(e); return; }
    if (M.kind === 'pal' && P.ids.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        P.sel = (P.sel + (e.key === 'ArrowDown' ? 1 : -1) + P.ids.length) % P.ids.length;
        _renderPalette(byId('pal-q').value);
      } else if (e.key === 'Enter') { e.preventDefault(); _runPalette(P.sel); }
    }
    if (M.kind === 'cfg' && e.target.id === 'cfg-kw') {
      const kw = C.draft[C.topic].keywords;
      if (e.key === 'Enter') {
        e.preventDefault();
        const v = e.target.value.trim().toLowerCase();
        if (v && !kw.includes(v)) kw.push(v);
        _drawCfg(); byId('cfg-kw')?.focus();
      } else if (e.key === 'Backspace' && !e.target.value && kw.length) { kw.pop(); _drawCfg(); byId('cfg-kw')?.focus(); }
    }
    if (M.kind === 'cfg' && e.target.id === 'cfg-name' && e.key === 'Enter') { e.preventDefault(); _renameTopic(e.target.value); }
    if (M.kind === 'pwd' && e.key === 'Enter') { e.preventDefault(); savePwd(); }
    return;
  }
  if (e.target.matches?.('input, select, textarea')) { if (e.key === 'Escape') e.target.blur(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const l = visibleList(), cur = l[state.sel], k = e.key;
  const triage = state.view === 'triage' && state.authenticated;
  if (k === 'Escape') {
    if (state.menu) _closeMenu();
    else if (state.open) { state.open = null; renderPanel(); }
    else if (state.side) { state.side = false; _shellClasses(); }
  }
  else if (k === 'j' || k === 'ArrowDown') { e.preventDefault(); move(1); }
  else if (k === 'k' || k === 'ArrowUp') { e.preventDefault(); move(-1); }
  else if (k === 'Enter') { if (cur && !e.target.closest('button, a')) { state.open = cur.id; renderPanel(); } }
  else if (k === 'o') { if (cur) openUrl(cur.url); }
  else if (k === 'm') { if (cur && triage) markSingleAsRead(cur.id); }
  else if (k === 'M') { if (triage) markVisibleAsRead(); }
  else if (k === 'u') { if (state.authenticated) undoAck(); }
  else if (k === 's') { if (cur && triage) snoozeArticle(cur.id); }
  else if (k === 'b') { if (cur && state.authenticated && !cur._stub) toggleBookmark(cur.id); }
  else if (k === 'v') command('density');
  else if (k === 'p') command('pin');
  else if (k === '[') command('collapse');
  else if (k === 'r') triggerRefresh();
  else if (k === '/') { e.preventDefault(); byId('q').focus(); }
  else if (k === '?') openHelp();
  else if (k === '1' || k === '2' || k === '3') {
    const sv = ['crit', 'warn', 'ok'][+k - 1];
    setFilter({ sev: state.sev === sv ? null : sv });
  }
  else if (k === '0') resetFilters();
}

// ── Init ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-ic]').forEach(el => { el.outerHTML = ic(el.dataset.ic); });
  document.addEventListener('click', _onClick);
  document.addEventListener('input', _onInput);
  document.addEventListener('change', _onChange);
  document.addEventListener('keydown', _onKeydown);
  window.matchMedia('(min-width: 1100px)').addEventListener('change', renderPanel);
  initReadTracking(byId('list'));

  fetchMe();
  applyI18n();
  fetchSnoozes();

  fetchStatus().then(status => {
    _applyStatus(status);
    if (status.is_loading && state.authenticated) {
      setRefreshBtnLoading(true); showToast(status.load_progress || t('toast.loading')); progress(30); startPolling();
    }
  }).catch(() => {}).finally(loadArticles);

  setInterval(async () => {
    try { _applyStatus(await fetchStatus()); renderSummary(); } catch { /* retried next tick */ }
  }, 60000);
});
