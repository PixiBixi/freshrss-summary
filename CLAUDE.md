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
| `static/js/app.js` | Toute la logique JS (i18n, state, fetch, SSE…) |
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

## Règle MD obligatoire

À chaque modification technique, mettre à jour **sans attendre d'être demandé** :
- `CLAUDE/progress.md` — ligne dans le tableau de changements
- `CLAUDE/architecture.md` — si la structure ou une décision technique change
- `README.md` — si une feature, un flag ou un comportement change

## Detailed docs

- `CLAUDE/architecture.md` — décisions techniques
- `CLAUDE/progress.md` — historique des changements
