# AGENTS.md - FreshRSS Summary

## What this project is

Web UI Python (FastAPI) pour trier les articles non lus FreshRSS par pertinence thématique.
L'utilisateur est SRE/Platform Engineer - les topics prioritaires sont SRE, GKE, ArgoCD, Terraform, Kubernetes.

## Quick map

| File | Role |
|------|------|
| `app.py` | FastAPI app, endpoints, cache in-memory, lifespan (DB init, admin user, scheduler, Telegram) |
| `auth.py` | Hash de mot de passe, `require_auth`, résolution de la clé de session, rate limit login |
| `config.py` | Chargement de `config.yaml` + surcharge par env vars, defaults |
| `models.py` | `Article` (dataclass) et les TypedDicts partagés (`ArticleDict`, `DbArticleRow`, ...) |
| `pipeline.py` | Logique fetch-score-rescore partagée entre `app.py` et `cli.py` |
| `freshrss_client.py` | Client API Google Reader (FreshRSS) |
| `scorer.py` | Scoring keyword-based par topic |
| `db.py` | Persistance async SQLAlchemy Core (SQLite/MySQL/PostgreSQL) |
| `scheduler.py` | Utilitaires asyncio génériques pour les tâches périodiques (refresh, digest) |
| `telegram_digest.py` | Digest Telegram (`/digest`), alertes trending, rappels de snooze |
| `metrics.py` | Registry Prometheus, mis à jour depuis le cache in-memory |
| `logging_config.py` | Config `logging.config.dictConfig` (root + loggers uvicorn) |
| `cli.py` | CLI offline : `check`, `stats`, `fetch`, `rescore`, `import`, `tune` |
| `templates/index.html` | HTML pur - structure seulement |
| `templates/login.html` | Page de connexion HTML pur |
| `static/css/app.css` | Styles de l'interface principale |
| `static/js/api.js` | Appels API, SSE, mark-as-read |
| `static/js/ui.js` | Init UI, event listeners, palette de commandes |
| `static/js/render.js` | Rendu DOM des articles |
| `static/js/state.js` | État global partagé |
| `static/js/i18n.js` | Traductions (fr/en/de/es/it/pt) |
| `static/css/login.css` | Styles de la page de connexion |
| `static/js/login.js` | i18n de la page de connexion |
| `config.yaml` | Credentials + topics (gitignored) |
| `config.example.yaml` | Template versionné |
| `helm/freshrss-summary/` | Chart Helm (Deployment, HPA, NetworkPolicy, Ingress, Secret) |

## Key conventions

- Config centralisée dans `config.py` : `config.yaml` (gitignored) chargé puis surchargé par env vars (liste complète dans le tableau du README)
- FreshRSS auth : API Google Reader via ClientLogin - champ `api_password` = mot de passe API FreshRSS (≠ mot de passe de connexion)
- SQLite path : `data/articles.db` (gitignored)
- Cache in-memory rechargé depuis SQLite au démarrage (lifespan FastAPI)
- Topics et keywords entièrement configurables dans `config.yaml`, éditables ensuite live depuis l'UI (persistés en DB)
- Table `seen_ids` (db.py) : évite de retélécharger/rescorer les articles déjà vus mais sous `min_score` - voir README section Database pour le détail
- Mettre à jour `README.md` quand une feature, un flag ou un comportement change

## Auth model

- Endpoints publics : `/`, `/login` (GET/POST), `/logout`, `/api/articles` (sans `show_read`), `/api/status`, `/health`
- Endpoints protégés (`require_auth`, session cookie) : `/api/refresh`, `/api/refresh/stream`, `/api/mark-read`, `/api/rescore`, `/api/bookmark`, `/api/snooze`, `/api/feeds`, `/api/config/scoring` (GET et PUT), `/api/change-password`, `/metrics`
- `show_read=True` sur `/api/articles` est silencieusement ignoré pour les anonymes
- Auth state côté client : `window._AUTH` (bool) et `window._USER` (string) injectés par Jinja2 - pas de fetch `/api/me`
- `/telegram/webhook` a son propre modèle d'auth, indépendant de `require_auth` : header `X-Telegram-Bot-Api-Secret-Token` comparé (`secrets.compare_digest`) à `telegram.webhook_secret` ; 404 si Telegram n'est pas configuré, 403 si le secret est invalide

## Pre-commit hooks

- `ruff` (`--fix`) et `ruff-format` peuvent réécrire un fichier au premier commit → re-stager et recommiter
- `check-yaml` exclut `helm/` (les templates Helm ne sont pas du YAML valide)
- `cocogitto` valide le message de commit (stage `commit-msg`) contre la convention Conventional Commits

## Commandes

- Setup : `uv venv && source .venv/bin/activate && uv pip install -r requirements-dev.txt`
- Lancer en local : `python app.py` ou `uvicorn app:app --host 0.0.0.0 --port 8123 --reload`
- Lint : `pre-commit run --all-files` (ou directement `ruff check --fix .` / `ruff format .`)
- Tests : `uv run pytest` ; un seul test : `uv run pytest tests/test_scorer.py::test_name` (ou `-k <expr>`)
- CI (`.github/workflows/ci.yml`) : job `lint` = `pre-commit/action`, job `test` = `uv run pytest --tb=short` (Python 3.14)
