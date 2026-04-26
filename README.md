# FreshRSS Summary

Web UI to sort and score unread FreshRSS articles by topic relevance (SRE, Kubernetes, ArgoCD, Terraform...).

## Setup

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Create virtualenv and install dependencies
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# 3. Config
cp config.example.yaml config.yaml
# Edit config.yaml with your FreshRSS URL, username and API password
```

## Running

```bash
python app.py
# or
uvicorn app:app --host 0.0.0.0 --port 8123 --reload
```

Open [http://localhost:8123](http://localhost:8123) and click **Refresh**.

## Authentication

On first start, an admin account is created automatically with a random password printed in the logs:

```
========================================================
  FIRST RUN — admin account created
  Username : admin
  Password : xK9mP2rT...
  Set ADMIN_PASSWORD env var to override on restart
========================================================
```

To change the password:

- **From the UI**: click the **🔑 Password** button in the header filters bar (requires login). Enter the current password, then the new one (min. 8 characters) with confirmation.
- **Via env var on restart** (e.g. Docker / Kubernetes):

```bash
ADMIN_PASSWORD=newpassword python app.py
# or with Docker:
docker run -e ADMIN_USERNAME=jeremy -e ADMIN_PASSWORD=mypass ...
```

Only **Refresh** and **Rescore** require authentication. Reading articles is public.

## Config

`config.yaml` (not versioned — contains credentials):

```yaml
freshrss:
  url: https://rss.example.com
  username: your_user
  api_password: your_api_password    # ≠ login password
  # Set it in FreshRSS → Settings → Authentication → API password

database:
  # SQLAlchemy async URL (SQLite by default)
  # url: sqlite+aiosqlite:///./data/articles.db
  # url: mysql+aiomysql://user:pass@host:3306/freshrss
  # url: postgresql+asyncpg://user:pass@host:5432/freshrss

server:
  host: 0.0.0.0       # overridable via SERVER_HOST
  port: 8123           # overridable via SERVER_PORT
  reload: false        # set to true for development (auto-restart on code change)
  log_level: info      # uvicorn log level: debug | info | warning | error

fetch:
  batch_size: 1000    # articles per FreshRSS API call
  max_batches: 10     # max 10,000 unread articles fetched

scoring:
  title_weight: 3     # a title match counts 3x more than body
  min_score: 1        # minimum score to appear in the UI

# auth:
#   secret_key: ""    # generate: python3 -c "import secrets; print(secrets.token_hex(32))"
```

Topics and their keywords are editable live from the UI (⚙ **Topics** button in the header) — changes are persisted in the database, no restart required. The initial topic list is seeded from `config.yaml` on first startup.

## Database

Default: SQLite at `data/articles.db` (created automatically).

To use MySQL or PostgreSQL, install the corresponding async driver and set the URL:

```bash
# MySQL
uv pip install aiomysql
# config.yaml → database.url: mysql+aiomysql://user:pass@host/db

# PostgreSQL
uv pip install asyncpg
# config.yaml → database.url: postgresql+asyncpg://user:pass@host/db
```

The URL can also be set via the `DATABASE_URL` environment variable.

DB schema migrations are applied automatically on startup (additive only).

## Environment variables

All config values can be overridden by environment variables:

| Env var | Config equivalent |
|---------|-------------------|
| `FRESHRSS_URL` | `freshrss.url` |
| `FRESHRSS_USERNAME` | `freshrss.username` |
| `FRESHRSS_API_PASSWORD` | `freshrss.api_password` |
| `DATABASE_URL` | `database.url` |
| `SERVER_HOST` | `server.host` |
| `SERVER_PORT` | `server.port` |
| `ADMIN_USERNAME` | *(admin user, default: `admin`)* |
| `ADMIN_PASSWORD` | *(reset/init admin password)* |
| `SECRET_KEY` | `auth.secret_key` |

## Docker

```bash
docker build -t freshrss-summary .
docker run -p 8123:8123 \
  -e FRESHRSS_URL=https://rss.example.com \
  -e FRESHRSS_USERNAME=user \
  -e FRESHRSS_API_PASSWORD=pass \
  -e ADMIN_PASSWORD=mypass \
  -v $(pwd)/data:/app/data \
  freshrss-summary
```

## Helm (Kubernetes)

```bash
helm install freshrss-summary ./helm/freshrss-summary \
  --set freshrss.url=https://rss.example.com \
  --set freshrss.username=your_user \
  --set secret.freshrssApiPassword=your_api_password \
  --set secret.adminPassword=mypass \
  --set secret.secretKey=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  --set ingress.enabled=true \
  --set ingress.host=rss.example.com
```

For production, use an externally managed secret (ESO, Vault, etc.) instead of inline values:

```yaml
# values.yaml
secret:
  existingSecret: "freshrss-summary-creds"  # pre-existing Secret with expected keys
```

Key values:

| Key | Description |
|-----|-------------|
| `freshrss.url` | FreshRSS instance URL |
| `freshrss.username` | FreshRSS username |
| `secret.freshrssApiPassword` | FreshRSS API password (≠ login password) |
| `secret.adminPassword` | Admin UI password |
| `secret.secretKey` | JWT secret — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `secret.databaseUrl` | Optional — override SQLite with MySQL/PostgreSQL URL |
| `persistence.size` | PVC size for SQLite data (default: `1Gi`) |
| `ingress.enabled` | Expose via ingress controller |
| `networkPolicy.enabled` | Enable NetworkPolicy (default: `true`) |
| `networkPolicy.dbPort` | Egress port for external DB — `5432` (PG) / `3306` (MySQL) / `0` to disable |

> SQLite is the default — do **not** enable `autoscaling` with SQLite (single-writer constraint).

## CLI

The CLI provides offline operations without starting the server:

```bash
python cli.py <command> [options]
```

| Command | Description |
|---------|-------------|
| `check` | Test FreshRSS connection and DB reachability |
| `stats` | Show DB statistics (articles, bookmarks, topics, last refresh) |
| `fetch [--dry-run]` | Fetch unread articles from FreshRSS, score, and save to DB |
| `rescore [--dry-run]` | Reapply current topic weights to articles already in DB |
| `import [FILE] [--starred] [--limit N] [--dry-run]` | Import from a JSON file or from FreshRSS starred stream |
| `tune [--apply] [--limit N]` | Analyze starred articles, suggest weight adjustments; `--apply` writes to `config.yaml` (seed only — use the UI to update a running instance) |

```bash
python cli.py check
python cli.py fetch --dry-run
python cli.py import --starred --limit 300
python cli.py tune --apply
python cli.py import articles.json
```

## Scoring

```
score = Σ (title_occurrences × title_weight + body_occurrences) × topic_weight
```

The highest-scoring article best matches your configured topics. Score breakdown per topic is shown as a tooltip on each article's score badge.

### Topics (default config)

12 topics, each with tunable weight and keyword list:

| Topic | Default weight |
|-------|---------------|
| SRE | 1.5 |
| Kubernetes | 1.5 |
| GKE | 2.0 |
| GitOps (ArgoCD, Flux…) | 1.5 |
| Terraform / IaC | 1.3 |
| Immutable OS | 1.4 |
| Platform Engineering | 1.2 |
| Observability | 1.1 |
| Security | 1.1 |
| CI/CD | 1.0 |
| Networking | 1.0 |
| FinOps | 1.2 |

Weights and keywords are editable live from the UI (⚙ **Topics** button) — persisted in the database, no restart required. The `config.yaml` topics section is only used to seed the database on first startup. Use `python cli.py tune --apply` to suggest weight adjustments based on your starred articles.

## UI Features

### Reading

- **SSE streaming**: articles appear progressively as they are fetched, no full-page wait
- **Auto mark-as-read on scroll**: articles scrolled past are silently marked as read in FreshRSS after a 3s debounce
- **Mark as read**: single article, all articles in a day group, or all visible
- **Open all**: open every article in a day group as tabs (with confirmation above 10)
- **Show read**: toggle to reveal articles marked as read (kept 7 days, purged on refresh)
- **Bookmarks**: starred locally, survive refreshes

### Filtering & sorting

- **Topic pills**: filter by topic, with article count and proportion mini-bar
- **Sort**: by score (default), date, or source
- **Min score**: adjustable live — hides low-relevance articles
- **Period**: 7d / 14d / 30d / all
- **Full-text search**: client-side filter on title and feed name, with "mark all results as read" button

### Interface

- **Keyboard shortcuts**: `j`/`k` navigate, `Enter`/`o` open, `m` mark as read, `r` refresh, `Esc` close detail
- **Compact mode**: denser list layout, toggled with ⊟
- **Score tooltip**: hover the score badge to see per-topic contribution breakdown
- **Last refresh indicator**: shows time since last fetch; ⚠ warning if stale (>3h)
- **Rescore**: reapply current weights without re-fetching
- **Scoring config** (⚙ Topics): edit topic names, weights, and keywords live — saved to DB, triggers automatic rescore
- **Password change** (🔑 Password): change the current user's password directly from the UI — no restart required
- **i18n**: French, English, German, Spanish, Italian, Portuguese — auto-detected from browser, override persisted in localStorage

## Observability

### Health check

`GET /health` — no authentication required.

```json
{
  "status": "ok",
  "db": "ok",
  "articles": 142,
  "last_refresh": "2025-03-26T10:00:00Z",
  "is_loading": false
}
```

Returns `503` with `"status": "degraded"` if the DB is unreachable.

### Prometheus metrics

`GET /metrics` — no authentication required. Standard Prometheus text format.

| Metric | Type | Description |
|--------|------|-------------|
| `freshrss_articles_total` | Gauge | Articles currently in memory cache |
| `freshrss_articles_by_topic{topic}` | Gauge | Articles per topic in cache |
| `freshrss_last_refresh_timestamp_seconds` | Gauge | Unix timestamp of last successful refresh |
| `freshrss_refreshes_total` | Counter | Successful refreshes since startup |
| `freshrss_refresh_duration_seconds` | Histogram | Refresh duration (buckets: 2s–300s) |

## Testing

```bash
# Install dev dependencies
uv pip install -r requirements-dev.txt

# Run all tests
uv run pytest

# With verbose output
uv run pytest -v
```

114 tests across 5 modules — no network or FreshRSS access required:

| Module | Coverage |
|--------|---------|
| `test_scorer.py` | `_strip_html`, `TopicConfig`, `build_topics`, `score_article`, `score_articles`, `analyze_favorites`, `ScoredArticle.to_dict` |
| `test_db.py` | Save/load roundtrip, soft-delete, bookmarks, users, pending sync outbox, `load_for_rescore`, `get_scoring_config`, `set_scoring_config` |
| `test_freshrss_client.py` | `_parse_item`, login, `_fetch_batch`, `fetch_unread`, `mark_as_read`, context manager |
| `test_app.py` | Password hashing, `load_config`, `Cache.populate` |
| `test_cli.py` | `load_config`, ANSI helpers |
