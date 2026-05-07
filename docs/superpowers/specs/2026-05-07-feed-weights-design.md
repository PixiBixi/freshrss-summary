# Feed Weights — Design Spec
**Date:** 2026-05-07
**Status:** Approved

## Problem

The keyword scorer treats all feeds equally. A noisy feed (e.g. Hacker News) inflates
scores just as much as a curated one. Users have no way to down-weight noisy sources
or boost trusted ones without touching keywords.

## Goal

Let the user assign a per-feed score multiplier from the UI. Articles from a penalised
feed score lower; articles from a boosted feed score higher. Everything else (topic
keywords, title weight, min_score filter) is unchanged.

## Out of Scope

- Per-feed keyword overrides
- Feed blocklist / hard-hide
- Multi-user feed weights
- PWA (next step)

---

## Data Model

Feed weights are stored as an additional key in the existing scoring config JSON blob
in the database (same table, same row as topics).

**Before:**
```json
{ "topics": { "SRE": { "keywords": [...], "weight": 1.5 } } }
```

**After:**
```json
{
  "topics": { "SRE": { "keywords": [...], "weight": 1.5 } },
  "feed_weights": { "Hacker News": 0.5, "Kubernetes Blog": 2.0 }
}
```

- Feeds absent from `feed_weights` default to `1.0` (neutral).
- `get_scoring_config` / `save_scoring_config` in `db.py` are unchanged — they already
  store and retrieve an opaque JSON blob.

---

## Scorer (`scorer.py`)

`score_article()` receives a new optional parameter:

```python
def score_article(
    article: Article,
    topics: list[TopicConfig],
    title_weight: int = 3,
    feed_weights: dict[str, float] | None = None,
) -> ScoredArticle:
```

After computing the base score:

```python
feed_mult = (feed_weights or {}).get(article.feed_title, 1.0)
total_score = sum(matched_topics.values()) * feed_mult
```

`ScoredArticle.to_dict()` exposes the applied multiplier:

```python
"feed_weight": feed_mult,  # 1.0 if neutral — used by UI tooltip
```

`score_articles()` forwards the new param to `score_article()`.

`analyze_favorites()` does **not** receive feed weights — favourite analysis operates
on raw topic affinity, not adjusted scores.

---

## API

### `GET /api/config/scoring`

**Before:** `{ "topics": { ... } }`
**After:** `{ "topics": { ... }, "feed_weights": { ... } }`

Missing `feed_weights` key (old DB rows) is treated as `{}`.

### `PUT /api/config/scoring`

Pydantic model extended:

```python
class ScoringConfigPayload(BaseModel):
    topics: dict
    feed_weights: dict[str, float] = {}
```

Both `topics` and `feed_weights` are saved together. A PUT without `feed_weights`
resets feed weights to empty (callers must always send both).

### Refresh / rescore pipelines

Both `_run_refresh()` and `_blocking_rescore_compute()` already call
`_get_or_init_scoring_config()`. They are updated to extract `feed_weights` from the
config and pass it down to the scorer. No new endpoints needed.

---

## UI

### Config drawer — new "Feeds" tab

The existing scoring config drawer (`ui.js`) gains a second tab alongside "Topics".

**Feed list population:**
- Union of feeds present in `state.articles` and feeds already saved with a weight ≠ 1.0.
- Sorted alphabetically.
- Feeds at `1.0` displayed dimmed; feeds with a custom weight highlighted with the
  accent colour.

**Each row:**
```
[Feed title]          [× 0.50 ▼▲]   [Reset]
```
- Number input, range `0.1–5.0`, step `0.1`.
- "Reset" button sets back to `1.0` and removes the entry from the saved dict.

**Save button:** shared with the Topics tab — sends `{ topics, feed_weights }` in one
PUT call.

### Score tooltip

If `feed_weight ≠ 1.0`, the existing per-article score tooltip gains a line:
```
feed ×0.50
```

---

## Error Handling

- Invalid multiplier values (< 0.1 or > 5.0) rejected client-side before save.
- `PUT /api/config/scoring` validates `feed_weights` values are floats in `[0.1, 5.0]`
  server-side; returns 422 on violation.
- If `feed_weights` key is missing from the DB blob (legacy rows), API returns `{}` and
  the scorer uses 1.0 for all feeds.

---

## Testing

- `scorer.py`: unit test `score_article()` with `feed_weights={"Feed A": 0.5}` —
  verify score is halved vs baseline.
- `scorer.py`: test missing feed defaults to 1.0.
- `app.py`: test `GET /api/config/scoring` returns `feed_weights` key.
- `app.py`: test `PUT /api/config/scoring` round-trips both topics and feed_weights.
- `app.py`: test `PUT` with out-of-range multiplier returns 422.
