<div align="center">

# FreshRSS Summary

**Triage your unread FreshRSS articles by relevance, not by date.**

[![CI](https://github.com/PixiBixi/freshrss-summary/actions/workflows/ci.yml/badge.svg)](https://github.com/PixiBixi/freshrss-summary/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/PixiBixi/freshrss-summary)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](Dockerfile)
[![Docker image](https://img.shields.io/badge/ghcr.io-pixibixi%2Ffreshrss--summary-2496ED?logo=docker&logoColor=white)](https://github.com/PixiBixi/freshrss-summary/pkgs/container/freshrss-summary)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/triage-dark.png">
  <img alt="FreshRSS Summary triage view with the reader preview open" src="docs/screenshots/triage-light.png" width="100%">
</picture>

</div>

## Features

- **Scored**: keyword-based relevance per topic, shown as a burn rate (`score / 100`) with P1, P2, P3 severities
- **Tunable**: topics, keywords and per-feed multipliers editable live from the UI, no restart
- **Fast triage**: views for Triage, Bookmarks, Snoozed and Read, burn-rate slider, period and topic filters, full-text search, open or ack a whole day at once
- **Two densities**: Scan for skimming, Lecture for reading, plus a reader preview you can pin
- **Keyboard first**: vim-style navigation and a `Cmd+K` command palette
- **Hands-off**: scroll auto-read with undo, background auto-refresh, Telegram digest
- **Polished**: light and dark themes, accent colour, 6 languages (fr, en, de, es, it, pt)
- **Safe to expose**: anonymous visitors get a read-only view, everything else needs a login
- **Self-hosted**: SQLite, MySQL or PostgreSQL, Docker image, Helm chart, Prometheus metrics

<details>
<summary>Command palette</summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/palette-dark.png">
  <img alt="Command palette" src="docs/screenshots/palette-light.png" width="100%">
</picture>

</details>

## Contents

- [Quick start](#quick-start)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Scoring](#scoring)
- [Database](#database)
- [Deployment](#deployment)
- [API](#api)
- [Telegram digest](#telegram-digest)
- [Observability](#observability)
- [CLI](#cli)
- [Development](#development)

## Quick start

### Docker

```bash
docker run -d --name freshrss-summary -p 8123:8123 \
  -e FRESHRSS_URL=https://rss.example.com \
  -e FRESHRSS_USERNAME=user \
  -e FRESHRSS_API_PASSWORD=pass \
  -e ADMIN_PASSWORD=mypass \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/pixibixi/freshrss-summary:latest
```

Open [http://localhost:8123](http://localhost:8123), log in as `admin` and click **Sync**. `FRESHRSS_API_PASSWORD` is the FreshRSS API password (FreshRSS Settings, Authentication), not your login password.

### Local

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # skip if uv is installed
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp config.example.yaml config.yaml                # set FreshRSS url, username, api_password
python app.py                                     # or: uvicorn app:app --host 0.0.0.0 --port 8123 --reload
```

## Keyboard shortcuts

Press `?` in the app to list them. Shortcuts are ignored while typing in an input.

| Key | Action |
|-----|--------|
| `Cmd+K` / `Ctrl+K` | Open the command palette |
| `j` / `ArrowDown` | Next article |
| `k` / `ArrowUp` | Previous article |
| `Enter` | Open the article in the reader preview |
| `o` | Open the article source in a new tab |
| `m` | Mark the article as read (Triage view, login required) |
| `M` | Mark all shown articles as read (Triage view, login required) |
| `u` | Undo the last mark as read (login required) |
| `s` | Snooze the article (Triage view, login required) |
| `b` | Toggle bookmark (login required) |
| `v` | Toggle density (Scan / Lecture) |
| `p` | Pin or unpin the reader preview |
| `[` | Collapse or expand the sidebar |
| `r` | Sync (refresh) |
| `/` | Focus the search box |
| `1` / `2` / `3` | Filter on P1 / P2 / P3 (press again to clear) |
| `0` | Reset filters |
| `?` | Show the help |
| `Esc` | Close the menu, reader preview or sidebar |

## Configuration

`config.yaml` (gitignored, contains credentials) is loaded first, then overridden by environment variables. Start from `config.example.yaml`.

```yaml
freshrss:
  url: https://rss.example.com
  username: your_user
  api_password: your_api_password    # not the login password
  # Set it in FreshRSS: Settings > Authentication > API password

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

scheduler:
  interval_minutes: 60  # auto-refresh every 60 min (0 = disabled)

# auth:
#   secret_key: ""    # generate: python3 -c "import secrets; print(secrets.token_hex(32))"
```

Topics and keywords are seeded from `config.yaml` on first startup, then edited live from the UI (persisted in the database).

### Environment variables

| Env var | Config equivalent |
|---------|-------------------|
| `FRESHRSS_URL` | `freshrss.url` |
| `FRESHRSS_USERNAME` | `freshrss.username` |
| `FRESHRSS_API_PASSWORD` | `freshrss.api_password` |
| `DATABASE_URL` | `database.url` |
| `SERVER_HOST` | `server.host` |
| `SERVER_PORT` | `server.port` |
| `SESSION_HTTPS_ONLY` | `server.https_only` (default `false`; `true` adds the `Secure` flag to the session cookie, set it behind HTTPS) |
| `ADMIN_USERNAME` | *(admin user, default: `admin`)* |
| `ADMIN_PASSWORD` | *(reset/init admin password)* |
| `SECRET_KEY` | `auth.secret_key` |
| `REFRESH_INTERVAL_MINUTES` | `scheduler.interval_minutes` |
| `TELEGRAM_BOT_TOKEN` | `telegram.bot_token` |
| `TELEGRAM_CHAT_ID` | `telegram.chat_id` |
| `TELEGRAM_WEBHOOK_SECRET` | `telegram.webhook_secret` |
| `PUBLIC_URL` | `server.public_url` |

### Auto-refresh

Set `scheduler.interval_minutes` (or `REFRESH_INTERVAL_MINUTES`) to fetch on a schedule (`0` = disabled, the default in env form).

- A scheduled run is skipped silently if a manual refresh is already in progress.
- The scheduler starts at app boot and shuts down cleanly on exit.

### Session key

Sessions are signed with, in order of precedence: `SECRET_KEY`, then `auth.secret_key` in `config.yaml`, then a random key generated on first run and stored in the database. The generated key survives restarts and is shared by every replica pointing at the same database. Setting `SECRET_KEY` explicitly is recommended: it keeps the key out of the database and lets you rotate it, which invalidates all active sessions.

## Authentication

On first start, an admin account is created with a random password printed in the logs:

```
========================================================
  FIRST RUN - admin account created
  Username : admin
  Password : xK9mP2rT...
  Set ADMIN_PASSWORD env var to override on restart
========================================================
```

To change the password:

- **From the UI**: open the `...` menu, then **Password** (requires login). Enter the current password, then the new one (min. 8 characters) with confirmation.
- **Via env var on restart**: `ADMIN_PASSWORD=newpassword python app.py`, or `docker run -e ADMIN_USERNAME=jeremy -e ADMIN_PASSWORD=mypass ...`

Login attempts are rate-limited to **10 per minute per IP**.

| Access | Endpoints |
|--------|-----------|
| Public (read-only) | `/`, `/login`, `/logout`, `/api/articles` (`show_read` ignored), `/api/status`, `/health` |
| Login required (session cookie) | `/api/refresh`, `/api/refresh/stream`, `/api/mark-read`, `/api/mark-unread`, `/api/rescore`, `/api/bookmark`, `/api/snooze`, `/api/snoozes`, `/api/feeds`, `/api/config/scoring` (GET, PUT), `/api/change-password`, `/metrics` |
| Own secret | `/telegram/webhook` (see [Telegram digest](#telegram-digest)) |

## Scoring

```
score = sum(title_occurrences * title_weight + body_occurrences) * topic_weight * feed_weight
```

The UI shows the score as a burn rate (`score / 100`). Hover or open an article to see the per-topic breakdown, plus the feed multiplier when it is not the default.

### Topics (default config)

12 topics, each with a tunable weight and keyword list:

| Topic | Default weight |
|-------|---------------|
| SRE | 1.5 |
| Kubernetes | 1.5 |
| GKE | 2.0 |
| GitOps (ArgoCD, Flux...) | 1.5 |
| Terraform / IaC | 1.3 |
| Immutable OS | 1.4 |
| Platform Engineering | 1.2 |
| Observability | 1.1 |
| Security | 1.1 |
| CI/CD | 1.0 |
| Networking | 1.0 |
| FinOps | 1.2 |

Weights and keywords are edited from the scoring modal (sidebar, Topics, Manage): saved to the database, followed by an automatic rescore. `python cli.py tune --apply` suggests weights from your starred articles.

### Per-feed multipliers

The **Feeds** tab of the scoring modal sets a score multiplier per feed (0.1 to 10.0, default `1.0`). Feeds with non-default multipliers are listed first, colour-coded by intensity (boost in accent colour, malus in red).

## Database

Default: SQLite at `data/articles.db`, created automatically. For MySQL or PostgreSQL, install the async driver and set `database.url` or `DATABASE_URL`:

```bash
uv pip install aiomysql   # mysql+aiomysql://user:pass@host/db
uv pip install asyncpg    # postgresql+asyncpg://user:pass@host/db
```

Schema migrations are applied automatically on startup (additive only).

<details>
<summary>The seen_ids table</summary>

The `seen_ids` table tracks every article ID the incremental refresh has already processed, including the ones scored below `min_score` that are never stored in `articles`. Without it the refresh diff would re-list them every time, so they would be downloaded and re-scored on every run. It is seeded from the articles already present on first startup and pruned as FreshRSS drops IDs from its unread set, so it stays roughly the size of that set. A rescore forgets the IDs of the articles it drops below `min_score`, so the next refresh fetches them again if they are still unread upstream and scores them with the current weights. IDs are recorded in the same transaction as the articles they belong to.

</details>

## Deployment

### Docker

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

A `docker-compose.yml` using the published image is provided.

### Helm (Kubernetes)

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

| Key | Description |
|-----|-------------|
| `freshrss.url` | FreshRSS instance URL |
| `freshrss.username` | FreshRSS username |
| `secret.freshrssApiPassword` | FreshRSS API password (not the login password) |
| `secret.adminPassword` | Admin UI password |
| `secret.secretKey` | Session signing secret - generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `secret.databaseUrl` | Optional - override SQLite with MySQL/PostgreSQL URL |
| `persistence.size` | PVC size for SQLite data (default: `1Gi`) |
| `ingress.enabled` | Expose via ingress controller |
| `networkPolicy.enabled` | Enable NetworkPolicy (default: `true`) |
| `networkPolicy.dbPort` | Egress port for external DB - `5432` (PG) / `3306` (MySQL) / `0` to disable |

> Run a single replica whatever the database, and do **not** enable `autoscaling`: the cache, refresh slot, scheduler (refresh + Telegram digest) and login rate limit are per-process.

## API

### `GET /api/articles`

Public (no session needed, except `show_read`). Returns `{"total": <int>, "articles": [...]}`; `total` counts every match before pagination. All parameters are optional.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | `7` | Only articles published in the last N days; `0` = no limit |
| `topic` | | Only articles matching this topic |
| `min_score` | | Only articles with `score >= min_score` |
| `feeds` | | Comma-separated `feed_title` list to keep (exact match) |
| `exclude_feeds` | | Comma-separated `feed_title` list to drop (exact match) |
| `dedupe` | | `title`: one article per title, the best-scored one |
| `sort` | `score` | `score`, `date` or `feed` |
| `limit` | `1000` | Page size; `0` = everything |
| `offset` | `0` | Pagination offset |
| `fields` | | Comma-separated keys to return per article (`id`, `title`, `url`, `feed_title`, `published`, `score`, `top_topic`, `matched_topics`, `matched_keywords`, `feed_weight`, `summary`, `bookmarked`, `_read`); unknown key = 400 |
| `summary_chars` | | Summary as plain text (tags stripped, whitespace collapsed), truncated to N characters |
| `show_read` | `false` | Include read articles (authenticated only, ignored otherwise) |

Feed titles containing a comma cannot be passed to `feeds` / `exclude_feeds`.

Compact listing for an agent:

```bash
curl -s 'https://summary.example.com/api/articles?days=30&limit=0&min_score=5&exclude_feeds=DEV.to&dedupe=title&fields=id,title,url,feed_title,score,top_topic,summary&summary_chars=200'
```

### `POST /api/mark-unread`

Auth required. Inverse of `/api/mark-read`: restores the articles to the unread list and unmarks them in FreshRSS (best effort, not retried).

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' -d '{"article_ids": ["tag:a"]}' https://summary.example.com/api/mark-unread
# {"status": "ok", "unmarked": 1}
```

`status` is `ok`, `queued` (FreshRSS unreachable) or `not_configured`. Empty `article_ids` returns 400.

### `GET /api/snoozes`

Auth required. All pending snoozes, ordered by `snooze_until`.

```json
{"snoozes": [{"article_id": "tag:a", "snooze_until": 1760000000, "title": "K8s guide", "url": "https://example.com/k8s"}]}
```

### `DELETE /api/snooze/{article_id}`

Auth required. Cancels the pending snooze of an article. Returns `{"status": "ok"}`.

## Telegram digest

Optional. With `bot_token` and `chat_id` set, a daily digest is sent at `digest_hour` (Europe/Paris, default `21`). Send `/digest` to the bot for an on-demand digest (requires the webhook). The app also sends trending alerts and snooze reminders.

1. Create a bot with @BotFather and copy the token.
2. Send a message to the bot, then read `chat.id` from `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Set `PUBLIC_URL` (or `server.public_url`) so the webhook registers automatically, or register it manually:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<PUBLIC_URL>/telegram/webhook&secret_token=<SECRET>"
```

```yaml
telegram:
  bot_token: ""          # TELEGRAM_BOT_TOKEN
  chat_id: ""            # TELEGRAM_CHAT_ID
  digest_hour: 21        # Hour in Europe/Paris timezone (0-23)
  webhook_secret: ""     # TELEGRAM_WEBHOOK_SECRET, any random string
```

`/telegram/webhook` checks the `X-Telegram-Bot-Api-Secret-Token` header against `webhook_secret`: 404 if Telegram is not configured, 403 if the secret is invalid.

## Observability

### Health check

`GET /health` - no authentication required.

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

`GET /metrics` - **authentication required**. Scrape it with a session cookie, or put it behind your own reverse-proxy auth. Standard Prometheus text format.

| Metric | Type | Description |
|--------|------|-------------|
| `freshrss_articles_total` | Gauge | Articles currently in memory cache |
| `freshrss_articles_by_topic{topic}` | Gauge | Articles per topic in cache |
| `freshrss_last_refresh_timestamp_seconds` | Gauge | Unix timestamp of last successful refresh |
| `freshrss_refreshes_total` | Counter | Successful refreshes since startup |
| `freshrss_refresh_duration_seconds` | Histogram | Refresh duration (buckets: 2s to 300s) |
| `freshrss_rescores_total` | Counter | Rescore runs since startup |
| `freshrss_rescore_duration_seconds` | Histogram | Scoring phase of a rescore (buckets: 1s to 300s) |
| `freshrss_rescore_articles` | Histogram | Articles processed per rescore |
| `freshrss_rescore_workers` | Gauge | Worker processes used by the last rescore |

Per-article rescore cost, comparable across hosts (worker count follows the CPUs the container can use):

```promql
rate(freshrss_rescore_duration_seconds_sum[1h])
  / rate(freshrss_rescore_articles_sum[1h])
```

## CLI

Offline operations, no server needed:

```bash
python cli.py <command> [options]
```

| Command | Description |
|---------|-------------|
| `check` | Test FreshRSS connection and DB reachability |
| `stats` | Show DB statistics (articles, bookmarks, topics, last refresh) |
| `fetch [--dry-run]` | Same incremental refresh as the app: fetch and score the unread articles not seen yet, save them, mark read the ones FreshRSS no longer lists as unread |
| `rescore [--dry-run]` | Reapply the active topics and feed weights (DB, as edited in the UI) to articles already in DB |
| `import [FILE] [--starred] [--limit N] [--dry-run]` | Import from a JSON file or from FreshRSS starred stream. Articles already read stay read; imported articles that FreshRSS does not list as unread are marked read by the next refresh |
| `tune [--apply] [--limit N]` | Analyze starred articles, suggest weight adjustments; `--apply` writes them to the DB scoring config, like the scoring modal (run `rescore` afterwards) |

```bash
python cli.py check
python cli.py fetch --dry-run
python cli.py import --starred --limit 300
python cli.py tune --apply
python cli.py import articles.json
```

## Development

```bash
uv pip install -r requirements-dev.txt
uv run pytest            # add -v for verbose output
pre-commit run --all-files
```

Tests need no network or FreshRSS access.

<details>
<summary>Test modules</summary>

| Module | Coverage |
|--------|---------|
| `test_scorer.py` | `_strip_html`, `TopicConfig`, `build_topics`, `score_article`, `score_articles`, `analyze_favorites`, `ScoredArticle.to_dict`, feed weight multiplier |
| `test_db.py` | Save/load roundtrip, soft-delete, bookmarks, users, pending sync outbox, `load_for_rescore`, `get_scoring_config`, `set_scoring_config`, feed weights |
| `test_freshrss_client.py` | `_parse_item`, login, `_fetch_batch`, `fetch_unread`, `mark_as_read`, context manager |
| `test_app.py` | Password hashing, `load_config`, `Cache.populate` |
| `test_cli.py` | `load_config`, ANSI helpers |

</details>

<details>
<summary>Code quality</summary>

<img src="scorecard.png" width="100%">

</details>

## License

[MIT](LICENSE)
