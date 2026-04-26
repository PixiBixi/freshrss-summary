# Telegram Digest — Design Spec

**Date:** 2026-04-26
**Status:** Approved

## Goal

Send a daily digest of the top 20% articles (by score) to a Telegram chat, every evening at 21h (Europe/Paris). Also sendable on-demand via the `/digest` Telegram bot command.

---

## Architecture

```
config.yaml (telegram.bot_token / chat_id / digest_hour)
       │
       ├─► APScheduler job "digest" at 21h Europe/Paris
       │       └─► telegram_digest.py
       │               ├─ build_digest(articles) → str (HTML)
       │               └─ send_message(token, chat_id, text) → httpx POST
       │                       └─► Telegram Bot API
       │
       └─► POST /telegram/webhook  (FastAPI endpoint)
               ├─ verify X-Telegram-Bot-Api-Secret-Token header
               └─► same build_digest + send_message
```

**New file:** `telegram_digest.py`
**Modified files:** `app.py` (lifespan, load_config, new endpoint), `config.example.yaml`

---

## Components

### `telegram_digest.py`

Three functions, no global state:

```python
async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """POST to Telegram sendMessage API. Splits at 4096 chars if needed."""

def build_digest(articles: list[ScoredArticle]) -> str:
    """
    Filter articles published in last 24h.
    Keep top 20% by score: math.ceil(len(articles) * 0.2), minimum 1.
    Sort by score descending.
    Return HTML-formatted digest string.
    """

async def send_digest(cfg: dict, cache: Cache) -> None:
    """Entry point called by scheduler and webhook handler."""
```

### FastAPI changes (`app.py`)

**`load_config()`** — add telegram section:
```python
tg = cfg.setdefault("telegram", {})
if v := os.environ.get("TELEGRAM_BOT_TOKEN"):   tg["bot_token"] = v
if v := os.environ.get("TELEGRAM_CHAT_ID"):     tg["chat_id"] = v
if v := os.environ.get("TELEGRAM_WEBHOOK_SECRET"): tg["webhook_secret"] = v
if v := os.environ.get("PUBLIC_URL"):           cfg.setdefault("server", {})["public_url"] = v
```

No validation — missing token/chat_id silently disables the feature.

**`lifespan()`** — add digest job after existing scheduler setup:
```python
from apscheduler.triggers.cron import CronTrigger

tg_cfg = cfg.get("telegram", {})
if tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.start()
    hour = int(tg_cfg.get("digest_hour", 21))
    scheduler.add_job(
        send_digest,
        CronTrigger(hour=hour, minute=0, timezone="Europe/Paris"),
        args=[tg_cfg, cache], id="daily_digest",
        max_instances=1, coalesce=True,
    )
    # Register webhook if public_url configured
    if public_url := cfg.get("server", {}).get("public_url"):
        await _register_webhook(tg_cfg, public_url)
```

**New endpoint:**
```python
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # Verify X-Telegram-Bot-Api-Secret-Token header
    # Parse update JSON
    # If message.text == "/digest" → send_digest(tg_cfg, cache)
    return {}
```

---

## Message Format

```
📡 FreshRSS Digest — Dimanche 27 avril

<a href="url">Kubernetes 1.32 — what's new</a> · <b>142</b> · The Register
<a href="url">ArgoCD multi-source apps GA</a> · <b>98</b> · CNCF Blog
<a href="url">GKE Autopilot node pool customization</a> · <b>87</b> · Google Cloud
...

18 articles · top 20% du jour
```

- Telegram parse mode: `HTML`
- Score in bold after the link
- If digest exceeds 4096 chars: split into consecutive messages at article boundaries
- If no articles in last 24h: send "📡 Aucun article pertinent dans les dernières 24h."
- Date formatted in French (locale-independent, using a hardcoded weekday/month dict)

---

## Config

### `config.yaml`

```yaml
telegram:
  bot_token: ""        # TELEGRAM_BOT_TOKEN env var
  chat_id: ""          # TELEGRAM_CHAT_ID env var
  digest_hour: 21      # Hour in Europe/Paris timezone (default: 21)
  webhook_secret: ""   # TELEGRAM_WEBHOOK_SECRET env var — random string you choose

server:
  public_url: ""       # PUBLIC_URL env var — e.g. https://freshrss.example.com
                       # Required for automatic webhook registration
```

### Webhook registration

On startup, if `bot_token` + `chat_id` + `public_url` are all set:
- Calls `setWebhook` with `url={public_url}/telegram/webhook` and `secret_token={webhook_secret}`
- Logs success/failure — never crashes the app on failure

If `public_url` is absent: webhook not registered automatically. User must call
`https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/telegram/webhook` manually.

### Security

- Webhook endpoint checks `X-Telegram-Bot-Api-Secret-Token` header against `webhook_secret`
- If header missing or wrong → 403 (no processing)
- If `webhook_secret` not configured → endpoint disabled (returns 404)

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Telegram API unreachable | Log error, do not retry (next scheduled run will try again) |
| No articles in last 24h | Send "no articles" message |
| `bot_token`/`chat_id` missing | Feature silently disabled at startup |
| Webhook secret mismatch | Return 403, log warning |
| Split message fails | Log error, best-effort send what was built |

---

## Out of scope

- Multiple chat IDs
- Per-user digest preferences
- Interactive menus or inline keyboard buttons
- Retry logic for Telegram API failures
- Digest history / deduplication across runs
