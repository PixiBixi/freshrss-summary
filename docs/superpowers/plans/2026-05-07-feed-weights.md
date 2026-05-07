# Feed Weights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-feed score multiplier configurable from the scoring config UI — articles from noisy feeds score lower, trusted feeds score higher.

**Architecture:** Feed weights stored as a separate key in the `meta` DB table. The scorer applies the multiplier (`score_final = base_score × feed_weight`) after computing the keyword-based score. The existing scoring config modal gains a second "Feeds" tab alongside "Topics". No new endpoints — `GET/PUT /api/config/scoring` is extended.

**Tech Stack:** Python/FastAPI, SQLAlchemy async Core, vanilla JS, Jinja2

---

## File Map

| File | Change |
|------|--------|
| `scorer.py` | Add `feed_weight` to `ScoredArticle`; add `feed_weights` param to `score_article()` and `score_articles()` |
| `db.py` | Add `get_feed_weights()` / `set_feed_weights()` |
| `app.py` | Import new DB funcs; extend `ScoringConfigRequest`; update GET/PUT endpoints; pass `feed_weights` down all scoring pipelines |
| `static/js/api.js` | Update `updateScoringConfig()` to send `feed_weights` |
| `static/js/i18n.js` | Add `cfg.tabTopics`, `cfg.tabFeeds`, `cfg.noFeeds` for all 6 languages |
| `templates/index.html` | Add tab bar to scoring modal; add `id` to "Add topic" button |
| `static/css/app.css` | Add `.modal-tabs`, `.modal-tab`, `.fw-row` styles |
| `static/js/ui.js` | Add `_scoringState`; update `openScoringModal()`; add `switchScoringTab()`, `_renderFeedRows()`, `_feedWeightRowHtml()`, `resetFeedWeight()`, `_collectFeedWeights()`; update `saveScoringConfig()` |
| `static/js/render.js` | Extend score tooltip with feed weight indicator |
| `tests/test_scorer.py` | Add `TestFeedWeights` class |
| `tests/test_db.py` | Add `TestFeedWeights` class |

---

## Task 1 — Scorer: add `feed_weights` parameter

**Files:**
- Modify: `scorer.py`
- Modify: `tests/test_scorer.py`

- [ ] **Step 1.1: Write failing tests**

Add at the end of `tests/test_scorer.py`:

```python
# ── feed_weights ─────────────────────────────────────────────────────────────


class TestFeedWeights:
    def test_multiplier_applied_to_score(self):
        article = make_article(title="kubernetes", feed_title="Hacker News")
        topic = make_topic("k8s", ["kubernetes"], weight=1.0)
        result = score_article(article, [topic], title_weight=3,
                               feed_weights={"Hacker News": 0.5})
        # base = 3.0, × 0.5 = 1.5
        assert result.score == pytest.approx(1.5)

    def test_feed_weight_stored_on_result(self):
        article = make_article(title="kubernetes", feed_title="My Feed")
        topic = make_topic("k8s", ["kubernetes"])
        result = score_article(article, [topic], title_weight=3,
                               feed_weights={"My Feed": 2.0})
        assert result.feed_weight == 2.0

    def test_unknown_feed_defaults_to_1(self):
        article = make_article(title="kubernetes", feed_title="Unknown Feed")
        topic = make_topic("k8s", ["kubernetes"], weight=1.0)
        result = score_article(article, [topic], title_weight=3,
                               feed_weights={"Other Feed": 0.5})
        assert result.feed_weight == 1.0
        assert result.score == pytest.approx(3.0)

    def test_none_feed_weights_neutral(self):
        article = make_article(title="kubernetes")
        topic = make_topic("k8s", ["kubernetes"])
        without = score_article(article, [topic], title_weight=3, feed_weights=None)
        with_none = score_article(article, [topic], title_weight=3)
        assert without.score == with_none.score

    def test_feed_weight_in_to_dict(self):
        article = make_article(title="kubernetes", feed_title="Boosted Feed")
        topic = make_topic("k8s", ["kubernetes"])
        d = score_article(article, [topic], title_weight=3,
                          feed_weights={"Boosted Feed": 3.0}).to_dict()
        assert "feed_weight" in d
        assert d["feed_weight"] == 3.0

    def test_score_articles_passes_feed_weights(self):
        articles = [
            make_article(id="noisy", title="kubernetes", feed_title="Noisy Feed"),
            make_article(id="trusted", title="kubernetes", feed_title="Trusted Feed"),
        ]
        topic = make_topic("k8s", ["kubernetes"])
        results = score_articles(
            articles, [topic], title_weight=3, min_score=0,
            feed_weights={"Noisy Feed": 0.1, "Trusted Feed": 2.0},
        )
        scores = {r.article.id: r.score for r in results}
        assert scores["trusted"] > scores["noisy"]
```

- [ ] **Step 1.2: Run to confirm they fail**

```bash
cd /Users/jeremy/Documents/perso/git/freshrss-summary
source .venv/bin/activate
pytest tests/test_scorer.py::TestFeedWeights -v
```

Expected: `ERROR` — `score_article() got unexpected keyword argument 'feed_weights'`

- [ ] **Step 1.3: Implement in `scorer.py`**

Add `feed_weight: float = 1.0` field to `ScoredArticle` (after `matched_keywords`, before `_stripped_content`):

```python
@dataclass
class ScoredArticle:
    article: Article
    score: float
    matched_topics: dict[str, float]
    matched_keywords: list[str]
    feed_weight: float = 1.0
    _stripped_content: str = field(default="", repr=False)
```

Add `feed_weight` to `to_dict()` (after `"matched_keywords"`):

```python
    def to_dict(self) -> dict:
        stripped = self._stripped_content
        return {
            "id": self.article.id,
            "title": self.article.title,
            "url": self.article.url,
            "feed_title": self.article.feed_title,
            "published": self.article.published,
            "score": round(self.score, 2),
            "matched_topics": {k: round(v, 2) for k, v in self.matched_topics.items()},
            "matched_keywords": self.matched_keywords[:10],
            "feed_weight": round(self.feed_weight, 2),
            "top_topic": self.top_topic,
            "summary": stripped[:400],
            "_content": stripped,
        }
```

Update `score_article()` signature and body — add `feed_weights` param and apply multiplier:

```python
def score_article(
    article: Article,
    topics: list[TopicConfig],
    title_weight: int = 3,
    feed_weights: dict[str, float] | None = None,
) -> ScoredArticle:
    title_lower = article.title.lower()
    stripped_content = _strip_html(article.content)
    content_lower = stripped_content.lower()

    matched_topics: dict[str, float] = {}
    all_keywords: set[str] = set()

    for topic in topics:
        if topic.pattern is None:
            continue
        title_matches = topic.pattern.findall(title_lower)
        content_matches = topic.pattern.findall(content_lower)
        hits = len(title_matches) * title_weight + len(content_matches)
        if hits > 0:
            matched_topics[topic.name] = hits * topic.weight
            all_keywords.update(title_matches)
            all_keywords.update(content_matches)

    feed_mult = (feed_weights or {}).get(article.feed_title, 1.0)
    total_score = sum(matched_topics.values()) * feed_mult

    return ScoredArticle(
        article=article,
        score=total_score,
        matched_topics=matched_topics,
        matched_keywords=sorted(all_keywords),
        feed_weight=feed_mult,
        _stripped_content=stripped_content,
    )
```

Update `score_articles()` signature — add `feed_weights` param and forward it:

```python
def score_articles(
    articles: list[Article],
    topics: list[TopicConfig],
    title_weight: int = 3,
    min_score: float = 1.0,
    feed_weights: dict[str, float] | None = None,
) -> list[ScoredArticle]:
    scored = []
    for article in articles:
        result = score_article(article, topics, title_weight, feed_weights=feed_weights)
        if result.score >= min_score:
            scored.append(result)

    scored.sort(key=lambda a: a.score, reverse=True)
    return scored
```

- [ ] **Step 1.4: Run all scorer tests**

```bash
pytest tests/test_scorer.py -v
```

Expected: all tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add scorer.py tests/test_scorer.py
git commit -m "feat(scorer): add per-feed score multiplier"
```

---

## Task 2 — DB: `get_feed_weights` / `set_feed_weights`

**Files:**
- Modify: `db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 2.1: Write failing tests**

Add at the end of `tests/test_db.py` (also add `get_feed_weights, set_feed_weights` to the import at the top of the file):

```python
# ── feed_weights ──────────────────────────────────────────────────────────────


class TestFeedWeights:
    async def test_defaults_to_empty(self, db):
        weights = await get_feed_weights()
        assert weights == {}

    async def test_roundtrip(self, db):
        await set_feed_weights({"Hacker News": 0.5, "Kubernetes Blog": 2.0})
        weights = await get_feed_weights()
        assert weights == {"Hacker News": 0.5, "Kubernetes Blog": 2.0}

    async def test_overwrite(self, db):
        await set_feed_weights({"Feed A": 0.5})
        await set_feed_weights({"Feed B": 2.0})
        weights = await get_feed_weights()
        assert weights == {"Feed B": 2.0}

    async def test_empty_dict(self, db):
        await set_feed_weights({"Feed A": 0.5})
        await set_feed_weights({})
        weights = await get_feed_weights()
        assert weights == {}
```

- [ ] **Step 2.2: Run to confirm they fail**

```bash
pytest tests/test_db.py::TestFeedWeights -v
```

Expected: `ImportError` — `cannot import name 'get_feed_weights'`

- [ ] **Step 2.3: Implement in `db.py`**

Add after `set_scoring_config()` (around line 327):

```python
async def get_feed_weights() -> dict[str, float]:
    """Return feed weight multipliers from DB, or {} if not set."""
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                select(meta_table.c.value).where(meta_table.c.key == "feed_weights")
            )
        ).first()
    return json.loads(row[0]) if row else {}


async def set_feed_weights(weights: dict[str, float]) -> None:
    """Persist feed weight multipliers to DB."""
    async with get_engine().begin() as conn:
        await _set_meta(conn, "feed_weights", json.dumps(weights, ensure_ascii=False))
```

- [ ] **Step 2.4: Run all DB tests**

```bash
pytest tests/test_db.py -v
```

Expected: all tests PASS

- [ ] **Step 2.5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): add get/set feed_weights to meta store"
```

---

## Task 3 — App: API + pipelines

**Files:**
- Modify: `app.py`

- [ ] **Step 3.1: Add `get_feed_weights, set_feed_weights` to import**

In `app.py`, find the `from db import (` block (line ~38) and add `get_feed_weights` and `set_feed_weights`:

```python
from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    add_snooze,
    clear_pending_sync,
    delete_snooze,
    get_bookmarked_ids,
    get_due_snoozes,
    get_engine,
    get_feed_weights,
    get_meta,
    get_pending_sync,
    get_scoring_config,
    get_user_hash,
    has_users,
    init_db,
    load_articles,
    load_for_rescore,
    load_read_articles,
    save_articles,
    set_articles_read,
    set_feed_weights,
    set_scoring_config,
    set_user_password,
    toggle_bookmark,
    upsert_user,
)
```

- [ ] **Step 3.2: Extend `ScoringConfigRequest` and update `GET/PUT /api/config/scoring`**

Replace the existing `ScoringConfigRequest` + both endpoint functions (around line 852):

```python
@app.get("/api/config/scoring", dependencies=[Depends(require_auth)])
async def get_scoring() -> dict[str, Any]:
    """Return the active scoring config (topics + feed weights) from DB."""
    topics = await _get_or_init_scoring_config()
    feed_weights = await get_feed_weights()
    return {"topics": topics, "feed_weights": feed_weights}


class ScoringConfigRequest(BaseModel):
    topics: dict[str, Any]
    feed_weights: dict[str, float] = {}


@app.put("/api/config/scoring", dependencies=[Depends(require_auth)])
async def update_scoring(req: ScoringConfigRequest) -> dict[str, str]:
    """Persist a new scoring config to DB. Takes effect on next refresh or rescore."""
    for feed, weight in req.feed_weights.items():
        if not (0.1 <= weight <= 5.0):
            raise HTTPException(
                status_code=422,
                detail=f"Feed weight for '{feed}' must be between 0.1 and 5.0",
            )
    await set_scoring_config(req.topics)
    await set_feed_weights(req.feed_weights)
    logger.info(
        "Scoring config updated: %d topics, %d feed weights",
        len(req.topics),
        len(req.feed_weights),
    )
    return {"status": "ok"}
```

- [ ] **Step 3.3: Update `_fetch_and_score_iter` and `_blocking_fetch_and_score`**

In `_fetch_and_score_iter` (line ~517), add `feed_weights` param and pass it to `score_articles`:

```python
def _fetch_and_score_iter(
    cfg: dict, topics_cfg: dict, feed_weights: dict[str, float] | None = None
) -> Iterator[tuple[list[dict], int]]:
    fr_cfg = cfg["freshrss"]
    fetch_cfg = cfg.get("fetch", {})
    scoring_cfg = cfg.get("scoring", {})
    batch_size = int(fetch_cfg.get("batch_size", 1000))
    max_batches = int(fetch_cfg.get("max_batches", 10))
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics(topics_cfg)
    total_fetched = 0

    with FreshRSSClient(fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]) as client:
        for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
            total_fetched += len(batch)
            scored = [
                sa.to_dict()
                for sa in score_articles(
                    batch, topics, title_weight=title_weight, min_score=min_score,
                    feed_weights=feed_weights,
                )
            ]
            yield scored, total_fetched
```

In `_blocking_fetch_and_score` (line ~544), add `feed_weights` param and forward it:

```python
def _blocking_fetch_and_score(
    cfg: dict, topics_cfg: dict, feed_weights: dict[str, float] | None = None
) -> tuple[list[dict], int]:
    """Blocking fetch + score — runs in a thread pool via asyncio.to_thread."""
    all_articles: list[dict] = []
    total_fetched = 0

    for scored_batch, total_fetched in _fetch_and_score_iter(cfg, topics_cfg, feed_weights):
        cache.load_progress = f"Récupération : {total_fetched} articles..."
        all_articles.extend(scored_batch)

    if total_fetched == 0:
        logger.warning("No articles fetched from FreshRSS — DB not modified")

    return all_articles, total_fetched
```

- [ ] **Step 3.4: Update `_blocking_rescore_compute`**

Add `feed_weights` param and pass to `score_articles`:

```python
def _blocking_rescore_compute(
    raw: list[dict], cfg: dict, topics_cfg: dict,
    feed_weights: dict[str, float] | None = None,
) -> list[dict]:
    """CPU re-scoring of cached articles. Runs in a thread pool via asyncio.to_thread."""
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics(topics_cfg)

    cache.load_progress = f"Re-scoring {len(raw)} articles..."
    articles = [article_from_row(r) for r in raw]
    return [
        a.to_dict()
        for a in score_articles(
            articles, topics, title_weight=title_weight, min_score=min_score,
            feed_weights=feed_weights,
        )
    ]
```

- [ ] **Step 3.5: Update `_run_refresh` to fetch and pass `feed_weights`**

In `_run_refresh()`, find the call to `asyncio.to_thread(_blocking_fetch_and_score, cfg, topics_cfg)` and update:

```python
        topics_cfg = await _get_or_init_scoring_config()
        feed_weights = await get_feed_weights()

        article_dicts, total_fetched = await asyncio.to_thread(
            _blocking_fetch_and_score, cfg, topics_cfg, feed_weights
        )
```

- [ ] **Step 3.6: Update `_run_rescore` to fetch and pass `feed_weights`**

In `_run_rescore()`, find the call to `asyncio.to_thread(_blocking_rescore_compute, raw, cfg, topics_cfg)` and update:

```python
        topics_cfg = await _get_or_init_scoring_config()
        feed_weights = await get_feed_weights()
        article_dicts = await asyncio.to_thread(
            _blocking_rescore_compute, raw, cfg, topics_cfg, feed_weights
        )
```

- [ ] **Step 3.7: Update the SSE stream `_event_gen` + `_worker`**

In `refresh_stream`, the `_worker` nested function takes `topics_cfg`. Add `feed_weights` param and forward it to `_fetch_and_score_iter`:

```python
    def _worker(topics_cfg: dict, feed_weights: dict[str, float]) -> None:
        # Runs in a thread pool — survives SSE client disconnections.
        cfg = load_config()
        all_articles: list[dict] = []
        total_fetched = 0
        _t0 = time.perf_counter()

        try:
            for scored_batch, total_fetched in _fetch_and_score_iter(cfg, topics_cfg, feed_weights):
                cache.load_progress = f"Récupération : {total_fetched} articles..."
                _put({"type": "progress", "message": cache.load_progress})
                for d in scored_batch:
                    all_articles.append(d)
                    _put({"type": "article", "article": d})

            if total_fetched == 0:
                logger.warning("Stream refresh: 0 articles fetched — DB not modified")
            else:
                cache.load_progress = "Sauvegarde..."
                asyncio.run_coroutine_threadsafe(
                    save_articles(all_articles, total_fetched), loop
                ).result()
                bookmarked = asyncio.run_coroutine_threadsafe(
                    get_bookmarked_ids(), loop
                ).result()
                for a in all_articles:
                    a["bookmarked"] = a["id"] in bookmarked
                cache.populate(all_articles, time.time(), total_fetched)
                _prom_refreshes.inc()
                _prom_refresh_dur.observe(time.perf_counter() - _t0)
                _update_prom_cache()
                logger.info(
                    "Stream refresh done: %d fetched, %d relevant",
                    total_fetched,
                    len(all_articles),
                )

            cache.load_progress = "Terminé"
            _put({"type": "done", "total_fetched": total_fetched, "count": len(all_articles)})

        except Exception as e:
            logger.exception("refresh-stream worker failed")
            cache.error = str(e)
            cache.load_progress = "Erreur"
            _put({"type": "error", "message": str(e)})
        finally:
            cache.is_loading = False
```

In `_event_gen`, fetch `feed_weights` and pass to worker:

```python
    async def _event_gen():
        cache.is_loading = True
        cache.error = None
        cache.load_progress = "Démarrage..."

        try:
            topics_cfg = await _get_or_init_scoring_config()
            feed_weights = await get_feed_weights()
        except Exception as e:
            cache.error = str(e)
            cache.load_progress = "Erreur"
            cache.is_loading = False
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        asyncio.create_task(asyncio.to_thread(_worker, topics_cfg, feed_weights))
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        except asyncio.CancelledError:
            pass
        # cache.is_loading is managed by the worker thread
```

- [ ] **Step 3.8: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 3.9: Commit**

```bash
git add app.py
git commit -m "feat(api): extend /api/config/scoring with feed_weights, wire into all pipelines"
```

---

## Task 4 — i18n: new keys

**Files:**
- Modify: `static/js/i18n.js`

- [ ] **Step 4.1: Add keys to all 6 languages**

In `i18n.js`, add to each language block (after the `'cfg.ph.keywords'` line):

```js
// French (fr)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'Aucun feed — rafraîchis pour charger tes articles.',

// English (en)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'No feeds yet — refresh to load your articles.',

// German (de)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'Keine Feeds — lade Artikel, um Feeds anzuzeigen.',

// Spanish (es)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'Sin feeds — actualiza para cargar tus artículos.',

// Italian (it)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'Nessun feed — aggiorna per caricare i tuoi articoli.',

// Portuguese (pt)
'cfg.tabTopics':    'Topics',
'cfg.tabFeeds':     'Feeds',
'cfg.noFeeds':      'Nenhum feed — atualize para carregar seus artigos.',
```

- [ ] **Step 4.2: Commit**

```bash
git add static/js/i18n.js
git commit -m "feat(i18n): add cfg.tabTopics, cfg.tabFeeds, cfg.noFeeds keys"
```

---

## Task 5 — UI: Feeds tab in scoring modal

**Files:**
- Modify: `templates/index.html`
- Modify: `static/css/app.css`
- Modify: `static/js/ui.js`
- Modify: `static/js/api.js`

- [ ] **Step 5.1: Update scoring modal HTML in `templates/index.html`**

Replace the scoring modal block (starting at the `<!-- Scoring config modal -->` comment):

```html
  <!-- Scoring config modal -->
  <div id="scoring-modal" class="modal-overlay" style="display:none" role="dialog" aria-modal="true" aria-labelledby="scoring-modal-title">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h2 id="scoring-modal-title" data-i18n="cfg.title">Configuration du scoring</h2>
        <button class="modal-close btn btn-ghost btn-icon" onclick="closeScoringModal()" aria-label="Fermer">✕</button>
      </div>
      <div class="modal-tabs">
        <button class="modal-tab active" id="tab-topics" onclick="switchScoringTab('topics')" data-i18n="cfg.tabTopics">Topics</button>
        <button class="modal-tab" id="tab-feeds" onclick="switchScoringTab('feeds')" data-i18n="cfg.tabFeeds">Feeds</button>
      </div>
      <div class="modal-body" id="scoring-topics"></div>
      <div class="modal-footer">
        <button class="btn btn-ghost" id="scoring-add-topic" onclick="addTopicRow()" data-i18n="cfg.addTopic">+ Ajouter un topic</button>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" onclick="closeScoringModal()" data-i18n="cfg.cancel">Annuler</button>
        <button class="btn btn-primary" id="scoring-save-btn" onclick="saveScoringConfig()" data-i18n="cfg.save">⇄ Enregistrer & re-scorer</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 5.2: Add CSS in `static/css/app.css`**

Add after the `.topic-keywords-label` rule (around line 551):

```css
/* ── Scoring modal tabs ──────────────────────────────── */
.modal-tabs {
  display: flex; border-bottom: 1px solid var(--border);
  padding: 0 20px; flex-shrink: 0;
}
.modal-tab {
  padding: 8px 16px; font-size: 13px; font-weight: 500;
  color: var(--text-3); background: none; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
  transition: color 0.15s; margin-bottom: -1px; font-family: inherit;
}
.modal-tab:hover { color: var(--text); }
.modal-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* ── Feed weight rows ────────────────────────────────── */
.fw-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-radius: 8px; background: var(--bg);
  border: 1px solid var(--border);
}
.fw-row--custom { border-color: var(--accent); }
.fw-name { flex: 1; font-size: 13px; font-weight: 500; color: var(--text-2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fw-mult { font-size: 13px; color: var(--text-3); flex-shrink: 0; }
```

- [ ] **Step 5.3: Update `static/js/ui.js`**

Add `_scoringState` module-level object just before the `openScoringModal` function (around line 262):

```js
// ── Scoring config modal ────────────────────────────────────────────────
const _scoringState = { activeTab: 'topics', topics: {}, feedWeights: {} };
```

Replace `openScoringModal()`:

```js
async function openScoringModal() {
  if (!_requireAuth()) return;
  const modal = document.getElementById('scoring-modal');
  modal.style.display = 'flex';
  document.getElementById('scoring-topics').innerHTML = '<p style="color:var(--text-3);font-size:13px">Chargement…</p>';

  try {
    const { topics, feed_weights } = await fetchScoringConfig();
    _scoringState.topics = topics;
    _scoringState.feedWeights = feed_weights || {};
    _scoringState.activeTab = 'topics';
    switchScoringTab('topics');
  } catch (e) {
    document.getElementById('scoring-topics').innerHTML =
      `<p style="color:#dc2626">${esc(e.message)}</p>`;
  }

  modal.onclick = (e) => { if (e.target === modal) closeScoringModal(); };
  document.addEventListener('keydown', _scoringEscHandler);
}
```

Add after `_renderScoringTopics()`:

```js
function switchScoringTab(tab) {
  // Persist current tab's edits before switching
  if (_scoringState.activeTab === 'topics') _scoringState.topics = _collectTopics();
  else _scoringState.feedWeights = _collectFeedWeights();

  _scoringState.activeTab = tab;
  document.getElementById('tab-topics').classList.toggle('active', tab === 'topics');
  document.getElementById('tab-feeds').classList.toggle('active', tab === 'feeds');
  document.getElementById('scoring-add-topic').style.display = tab === 'topics' ? '' : 'none';

  if (tab === 'topics') _renderScoringTopics(_scoringState.topics);
  else _renderFeedRows(_scoringState.feedWeights);
}

function _renderFeedRows(feedWeights) {
  const container = document.getElementById('scoring-topics');
  const knownFeeds = new Set(state.articles.map(a => a.feed_title));
  Object.keys(feedWeights).forEach(f => knownFeeds.add(f));

  if (!knownFeeds.size) {
    container.innerHTML = `<p style="color:var(--text-3);font-size:13px">${esc(t('cfg.noFeeds'))}</p>`;
    return;
  }
  container.innerHTML = [...knownFeeds].sort()
    .map(feed => _feedWeightRowHtml(feed, feedWeights[feed] ?? 1.0))
    .join('');
}

function _feedWeightRowHtml(feed, weight) {
  const isCustom = Math.abs(weight - 1.0) > 0.001;
  return `
    <div class="fw-row${isCustom ? ' fw-row--custom' : ''}" data-feed="${esc(feed)}">
      <span class="fw-name" title="${esc(feed)}">${esc(feed)}</span>
      <span class="fw-mult">×</span>
      <input type="number" class="fw-weight topic-weight" value="${weight}" min="0.1" max="5.0" step="0.1"
        aria-label="${esc(t('cfg.tabFeeds'))}" oninput="this.closest('.fw-row').classList.toggle('fw-row--custom', Math.abs(parseFloat(this.value)-1.0)>0.001)" />
      <button class="btn btn-ghost topic-remove" onclick="resetFeedWeight(this)" aria-label="Réinitialiser">↺</button>
    </div>`;
}

function resetFeedWeight(btn) {
  const row = btn.closest('.fw-row');
  row.querySelector('.fw-weight').value = '1.0';
  row.classList.remove('fw-row--custom');
}

function _collectFeedWeights() {
  const weights = {};
  for (const row of document.querySelectorAll('.fw-row')) {
    const feed = row.dataset.feed;
    const w = parseFloat(row.querySelector('.fw-weight').value) || 1.0;
    if (Math.abs(w - 1.0) > 0.001) weights[feed] = w;
  }
  return weights;
}
```

Replace `saveScoringConfig()`:

```js
async function saveScoringConfig() {
  const btn = document.getElementById('scoring-save-btn');
  btn.disabled = true;
  // Collect current tab state
  if (_scoringState.activeTab === 'topics') _scoringState.topics = _collectTopics();
  else _scoringState.feedWeights = _collectFeedWeights();
  try {
    await updateScoringConfig(_scoringState.topics, _scoringState.feedWeights);
    closeScoringModal();
    showToast(t('cfg.saved'));
    _doRescore();
  } catch (e) {
    toastError(e.message);
    btn.disabled = false;
  }
}
```

- [ ] **Step 5.4: Update `updateScoringConfig` in `static/js/api.js`**

Replace the existing `updateScoringConfig` function:

```js
async function updateScoringConfig(topics, feed_weights = {}) {
  const r = await fetch('/api/config/scoring', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topics, feed_weights }),
  });
  if (!r.ok) throw new Error('Failed to save scoring config');
}
```

- [ ] **Step 5.5: Smoke-test manually**

Start the app (`uvicorn app:app --reload`), open the UI, click ⚙ Topics, confirm:
- Two tabs visible: "Topics" / "Feeds"
- Topics tab shows existing topics as before
- Feeds tab shows all feeds from loaded articles
- Setting a feed to ×0.5 highlights the row in accent color
- Saving triggers a rescore; articles from that feed score lower

- [ ] **Step 5.6: Commit**

```bash
git add templates/index.html static/css/app.css static/js/ui.js static/js/api.js
git commit -m "feat(ui): add Feeds tab to scoring config modal"
```

---

## Task 6 — Render: feed weight in score tooltip

**Files:**
- Modify: `static/js/render.js`

- [ ] **Step 6.1: Update tooltip in `renderRow()`**

In `renderRow()`, replace the `const tooltip = ...` line:

```js
  const feedLine = (a.feed_weight && Math.abs(a.feed_weight - 1.0) > 0.001)
    ? ` · feed ×${a.feed_weight.toFixed(2)}`
    : '';
  const tooltip = Object.entries(a.matched_topics)
    .sort((x, y) => y[1] - x[1])
    .map(([topic, v]) => `${topic}\u00a0${v.toFixed(1)}`)
    .join(' · ') + feedLine;
```

- [ ] **Step 6.2: Update tooltip in `renderCompactRow()`**

Same change in `renderCompactRow()` — replace its `const tooltip = ...` line:

```js
  const feedLine = (a.feed_weight && Math.abs(a.feed_weight - 1.0) > 0.001)
    ? ` · feed ×${a.feed_weight.toFixed(2)}`
    : '';
  const tooltip = Object.entries(a.matched_topics)
    .sort((x, y) => y[1] - x[1])
    .map(([topic, v]) => `${topic}\u00a0${v.toFixed(1)}`)
    .join(' · ') + feedLine;
```

- [ ] **Step 6.3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6.4: Commit**

```bash
git add static/js/render.js
git commit -m "feat(ui): show feed weight multiplier in score tooltip"
```
