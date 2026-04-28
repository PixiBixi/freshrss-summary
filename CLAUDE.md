# FreshRSS Summary — Claude Context

## What this project is

Web UI Python (FastAPI) pour trier les articles non lus FreshRSS par pertinence thématique.
L'utilisateur est SRE/Platform Engineer — les topics prioritaires sont SRE, GKE, ArgoCD, Terraform, Kubernetes.

## Quick map

| File | Role |
|------|------|
| `app.py` | FastAPI app, endpoints, cache in-memory, lifespan DB init |
| `freshrss_client.py` | Client API Google Reader (FreshRSS) |
| `scorer.py` | Scoring keyword-based par topic |
| `db.py` | Persistance async SQLAlchemy Core (SQLite/MySQL/PostgreSQL) |
| `templates/index.html` | HTML pur — structure seulement |
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

## Key conventions

- Config : `config.yaml` (gitignored) ou env vars (`FRESHRSS_URL`, `FRESHRSS_USERNAME`, `FRESHRSS_API_PASSWORD`, `SERVER_HOST`, `SERVER_PORT`)
- FreshRSS auth : API Google Reader via ClientLogin — champ `api_password` = mot de passe API FreshRSS (≠ mot de passe de connexion)
- SQLite path : `data/articles.db` (gitignored)
- Cache in-memory rechargé depuis SQLite au démarrage (lifespan FastAPI)
- Topics et keywords entièrement configurables dans `config.yaml`

## Règle MD obligatoire (note : CLAUDE/ n'existe pas encore)

À chaque modification technique, mettre à jour **sans attendre d'être demandé** :
- `CLAUDE/progress.md` — ligne dans le tableau de changements (créer si absent)
- `CLAUDE/architecture.md` — si la structure ou une décision technique change (créer si absent)
- `README.md` — si une feature, un flag ou un comportement change

## Auth model

- Endpoints publics : `/`, `/api/articles` (sans `show_read`), `/api/status`, `/health`
- Endpoints protégés (`require_auth`) : `/api/refresh/stream`, `/api/mark-read`, `/api/rescore`, `/api/config/scoring` (PUT), `/api/bookmark`, `/api/snooze`, `/api/change-password`, `/metrics`
- `show_read=True` sur `/api/articles` est silencieusement ignoré pour les anonymes
- Auth state côté client : `window._AUTH` (bool) et `window._USER` (string) injectés par Jinja2 — pas de fetch `/api/me`

## Pre-commit hooks

- `ruff-format` auto-modifie `app.py` lors du premier commit → re-stager le fichier et recommiter

## Detailed docs

- `CLAUDE/architecture.md` — décisions techniques (créer si absent)
- `CLAUDE/progress.md` — historique des changements (créer si absent)
