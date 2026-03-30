// ── Filters ────────────────────────────────────────────────────────────
function applyFilters() {
  let a = [...state.articles];
  if (state.activeTopic) a = a.filter(x => state.activeTopic in x.matched_topics);
  a = a.filter(x => x.score >= state.minScore);
  if (state.showBookmarks) a = a.filter(x => x.bookmarked);
  if (state.search) {
    const q = state.search.toLowerCase();
    a = a.filter(x => x.title.toLowerCase().includes(q) || x.feed_title.toLowerCase().includes(q));
  }
  if (state.sort === 'score')     a.sort((x, y) => y.score - x.score);
  else if (state.sort === 'date') a.sort((x, y) => y.published - x.published);
  else if (state.sort === 'feed') a.sort((x, y) => x.feed_title.localeCompare(y.feed_title));
  state.filtered = a;
  state.focusedIdx = -1;
  document.getElementById('search-read-btn').style.display = state.search && a.length ? '' : 'none';
  renderArticles(); updateStats();
}

function filterTopic(topic) {
  state.activeTopic = topic; state.showBookmarks = false; state.displayed = 100;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  document.getElementById(topic ? `pill-${topic.replace(/\s+/g, '-')}` : 'pill-all')?.classList.add('active');
  applyFilters();
}

function filterBookmarks() {
  state.showBookmarks = !state.showBookmarks;
  state.activeTopic = null;
  state.displayed = 100;
  buildTopicPills(state.articles);
  applyFilters();
}

function loadMore() { state.displayed += 100; renderArticles(); }

// ── Render ─────────────────────────────────────────────────────────────
function renderArticles() {
  const grid     = document.getElementById('articles-grid');
  const empty    = document.getElementById('empty-state');
  const allread  = document.getElementById('allread-state');
  const lm       = document.getElementById('load-more-bar');

  if (!state.filtered.length) {
    grid.classList.remove('visible'); lm.classList.remove('visible');
    document.getElementById('mark-read-btn').disabled = true;
    const allDone = state.everLoaded && state.articles.length === 0 && !state.showRead;
    allread.style.display = allDone ? 'flex' : 'none';
    empty.style.display   = allDone ? 'none'  : 'flex';
    return;
  }

  allread.style.display = 'none';
  empty.style.display = 'none';
  grid.classList.add('visible');
  document.getElementById('mark-read-btn').disabled = false;

  const toShow = state.filtered.slice(0, state.displayed);
  const groups = groupByDate(toShow);
  grid.innerHTML = groups.map(([label, items]) => `
    <div class="date-group" data-ids="${esc(JSON.stringify(items.map(a => a.id)))}">
      <div class="date-header">
        ${esc(label)}
        <span class="date-hr"></span>
        <button class="day-open-btn" onclick="openDayLinks(this)">${t('btn.dayOpen')}</button>
        <button class="day-read-btn" onclick="markDayAsRead(this)">${t('btn.dayRead')}</button>
      </div>
      <div class="feed-list">
        ${items.map(renderRow).join('')}
      </div>
    </div>
  `).join('');

  _markedIds.forEach(id => {
    document.querySelector(`.feed-row[data-id="${CSS.escape(id)}"]`)?.classList.add('read');
  });

  lm.classList.toggle('visible', state.filtered.length > state.displayed);
}

function groupByDate(articles) {
  const now   = new Date();
  const today = dateKey(now);
  const yest  = dateKey(new Date(now - 86400000));

  const buckets = new Map();
  for (const a of articles) {
    const d   = a.published ? new Date(a.published * 1000) : new Date(0);
    const key = dateKey(d);
    let label;
    if (key === today)     label = `${t('date.today')} — ${fmtDate(d)}`;
    else if (key === yest) label = `${t('date.yesterday')} — ${fmtDate(d)}`;
    else                   label = fmtDate(d);
    if (!buckets.has(label)) buckets.set(label, []);
    buckets.get(label).push(a);
  }
  // Groups newest-first; within each group, sort by score descending
  return [...buckets.entries()]
    .map(([label, items]) => {
      items.sort((a, b) => b.score - a.score);
      const maxPublished = items.reduce((m, a) => a.published > m ? a.published : m, 0);
      return { label, items, maxPublished };
    })
    .sort((a, b) => b.maxPublished - a.maxPublished)
    .map(({ label, items }) => [label, items]);
}

function dateKey(d) { return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; }

function fmtDate(d) {
  const locale = state.lang === 'en' ? 'en-GB' : 'fr-FR';
  return d.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

function fmtTime(ts) {
  if (!ts) return '';
  const locale = state.lang === 'en' ? 'en-GB' : 'fr-FR';
  return new Date(ts * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

function renderRow(a) {
  const sc = a.score >= 15 ? 'hi' : a.score >= 5 ? 'md' : 'lo';
  const topTopic = a.top_topic || Object.keys(a.matched_topics)[0] || '';
  const kws = a.matched_keywords.slice(0, 6).map(k => `<span class="tag-kw">${esc(k)}</span>`).join('');
  const summary = a.summary ? `<p style="margin-bottom:6px">${esc(a.summary)}</p>` : '';
  const tooltip = Object.entries(a.matched_topics)
    .sort((x, y) => y[1] - x[1])
    .map(([topic, v]) => `${topic}\u00a0${v.toFixed(1)}`)
    .join(' · ');

  return `
    <div class="feed-row${a._read ? ' shown-read' : ''}" data-id="${esc(a.id)}"${a._read ? ' data-already-read="1"' : ''} onclick="toggleDetail('${esc(a.id)}')">
      <span class="row-score ${sc}" data-tooltip="${esc(tooltip)}">${a.score.toFixed(0)}</span>
      <span class="row-source">${esc(a.feed_title)}</span>
      <a class="row-title" href="${esc(a.url)}" target="_blank" rel="noopener"
        onclick="event.stopPropagation()">${esc(a.title)}</a>
      <div class="row-right">
        ${a._read ? `<span class="badge-read">${t('label.read')}</span>` : ''}
        ${topTopic ? `<span class="row-topic">${esc(topTopic)}</span>` : ''}
        <span class="row-date">${fmtTime(a.published)}</span>
        ${!a._read ? `<button class="row-bookmark ${a.bookmarked ? 'bookmarked' : ''}"
          onclick="toggleBookmark('${esc(a.id)}', event)"
          aria-label="${a.bookmarked ? 'Retirer des favoris' : 'Ajouter aux favoris'}"
          aria-pressed="${a.bookmarked}">${a.bookmarked ? '★' : '☆'}</button>
        <button class="row-lu" onclick="markSingleAsRead('${esc(a.id)}', event)" aria-label="Marquer comme lu">${t('btn.markRead')}</button>` : ''}
      </div>
    </div>
    <div class="feed-row-detail" id="detail-${esc(a.id)}">
      ${summary}
      <div class="detail-tags">${kws}</div>
    </div>`;
}

function buildTopicPills(articles) {
  const map = {};
  for (const a of articles) for (const topic of Object.keys(a.matched_topics)) map[topic] = (map[topic] || 0) + 1;
  const sorted = Object.entries(map).sort((a, b) => b[1] - a[1]);
  const maxCount = sorted.length ? sorted[0][1] : 1;
  const bar = document.getElementById('topic-bar');
  const bookmarkCount = articles.filter(a => a.bookmarked).length;
  bar.innerHTML = `
    <button class="pill ${!state.activeTopic && !state.showBookmarks ? 'active' : ''}" id="pill-all"
        style="--bar:100%" onclick="filterTopic(null)">
      ${t('topic.all')} <span style="opacity:.6">${articles.length}</span>
    </button>
    ${bookmarkCount > 0 ? `
    <button class="pill ${state.showBookmarks ? 'active' : ''}" id="pill-bookmarks"
        style="--bar:${Math.round(bookmarkCount / articles.length * 100)}%" onclick="filterBookmarks()">
      ${t('topic.bookmarks')} <span style="opacity:.6">${bookmarkCount}</span>
    </button>` : ''}
    ${sorted.map(([topic, n]) => `
      <button class="pill ${state.activeTopic === topic ? 'active' : ''}" id="pill-${esc(topic.replace(/\s+/g, '-'))}"
          style="--bar:${Math.round(n / maxCount * 100)}%" onclick="filterTopic('${esc(topic)}')">
        ${esc(topic)} <span style="opacity:.6">${n}</span>
      </button>`).join('')}`;
  bar.classList.toggle('visible', sorted.length > 0);
}

function updateStats() {
  document.getElementById('showing-count').textContent = Math.min(state.displayed, state.filtered.length);
  document.getElementById('total-count').textContent = state.filtered.length;
  document.getElementById('stats-badge').style.display = 'inline';
}
