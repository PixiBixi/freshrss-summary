# Changelog

- - -
## [v1.8.0](https://github.com/PixiBixi/freshrss-summary/compare/c04057d325815e581ccc84a9973f0f3e3f62736b..v1.8.0) - 2026-05-11
#### Features
- **(ci)** create GitHub release after cog bump with changelog notes - ([c04057d](https://github.com/PixiBixi/freshrss-summary/commit/c04057d325815e581ccc84a9973f0f3e3f62736b)) - Jeremy Delgado

- - -

## [v1.7.2](https://github.com/PixiBixi/freshrss-summary/compare/eaba6f926b2f56145ece610148da37f5e2255104..v1.7.2) - 2026-05-11
#### Bug Fixes
- **(ci)** add cog separator to CHANGELOG.md so cog bump can insert new versions - ([967153a](https://github.com/PixiBixi/freshrss-summary/commit/967153ac96e315d27439d449d9d78182f3ade1aa)) - Jeremy Delgado
- **(ci)** add tag_prefix=v to cog.toml so cocogitto resolves existing v* tags - ([c4c18cd](https://github.com/PixiBixi/freshrss-summary/commit/c4c18cdec12bc49f66eac52a45fe4cda08a51223)) - Jeremy Delgado
#### Miscellaneous Chores
- **(ci)** replace release-please-action with cocogitto-action - ([eaba6f9](https://github.com/PixiBixi/freshrss-summary/commit/eaba6f926b2f56145ece610148da37f5e2255104)) - Jeremy Delgado

- - -

## Unreleased ([51e2bb7..dfa942e](https://github.com/PixiBixi/freshrss-summary/compare/51e2bb7..dfa942e))
#### Code Health
- fix code quality + schema drift + type annotations - ([e276842](https://github.com/PixiBixi/freshrss-summary/commit/e276842b99cebf836546c292577b5d3bb97d27bb)) - Jeremy Delgado
- fix security cluster + suppress venv/worktree false positives - ([fb7b727](https://github.com/PixiBixi/freshrss-summary/commit/fb7b727065fb6f37fefd90ef36a1016e714321dd)) - Jeremy Delgado
#### Features
- (**app**) switch SSE refresh to incremental pipeline - ([9f14b24](https://github.com/PixiBixi/freshrss-summary/commit/9f14b2472e756977b8a0b967164449ca52532a2a)) - Jeremy Delgado
- (**app**) pass feed_weights through all scoring pipelines and extend scoring API - ([743b880](https://github.com/PixiBixi/freshrss-summary/commit/743b8804323f21daa7d72c20ccc90c8345e91ba8)) - Jeremy Delgado
- (**auth**) gate mark-as-read and bookmark actions behind authentication - ([5971f9e](https://github.com/PixiBixi/freshrss-summary/commit/5971f9eeda5299fa6f7e549edc733a2c8171bfb5)) - Jeremy Delgado
- (**auth**) add change-password UI modal - ([865f21c](https://github.com/PixiBixi/freshrss-summary/commit/865f21c8da91ccf61f5793c6a28b7163c6c37b5e)) - Jeremy Delgado
- (**auth**) add change-password feature via UI modal - ([3f47a2d](https://github.com/PixiBixi/freshrss-summary/commit/3f47a2d79d626d5950e157cb8044bb3679b2f5fa)) - Jeremy Delgado
- (**backend**) FastAPI app, FreshRSS client, scorer, DB, CLI - ([a1b4821](https://github.com/PixiBixi/freshrss-summary/commit/a1b482163dd3b706bea78d1a28366a2e54a94d39)) - Jeremy Delgado
- (**db**) add get_unread_ids, sync_articles and fix load_articles columns - ([273f907](https://github.com/PixiBixi/freshrss-summary/commit/273f9070992075a22b7d599e779a476d5428b7e5)) - Jeremy Delgado
- (**db**) add get_feed_weights and set_feed_weights - ([8748215](https://github.com/PixiBixi/freshrss-summary/commit/8748215492c376cca22c6fb39e525d976250914d)) - Jeremy Delgado
- (**deps**) pin all transitive dependencies in uv.lock - ([4e7df71](https://github.com/PixiBixi/freshrss-summary/commit/4e7df710c7bd18acb4bd7074bade43bb76f067b8)) - Jeremy Delgado
- (**docker**) add Telegram env vars to docker-compose - ([daf8cd7](https://github.com/PixiBixi/freshrss-summary/commit/daf8cd74146e3750954b5d1b0a799db537faab3d)) - Jeremy Delgado
- (**docker**) add Dockerfile - ([b8b52db](https://github.com/PixiBixi/freshrss-summary/commit/b8b52dbb55657ef0084e3e24159d754ff68cc51d)) - Jeremy Delgado
- (**freshrss_client**) add fetch_unread_ids and fetch_articles_by_ids - ([7bbb7c8](https://github.com/PixiBixi/freshrss-summary/commit/7bbb7c8d8b95f6bb672cc42dfba5ffcc9c01a8d2)) - Jeremy Delgado
- (**helm**) Kubernetes Helm chart - ([faf0e55](https://github.com/PixiBixi/freshrss-summary/commit/faf0e5528f55548f6c56ea03aaa5e210ddc3ce28)) - Jeremy Delgado
- (**i18n**) add cfg.tabTopics, cfg.tabFeeds, cfg.noFeeds for all 6 languages - ([3f856ff](https://github.com/PixiBixi/freshrss-summary/commit/3f856ff99dabf877df33fb23fb6c725fbd3ae8e5)) - Jeremy Delgado
- (**pipeline**) add fetch_and_score_incremental_iter - ([fd53854](https://github.com/PixiBixi/freshrss-summary/commit/fd53854b3f72aa0c0d7de21bf5a06a32f5bbbf59)) - Jeremy Delgado
- (**render**) show feed_weight multiplier in score tooltip - ([6aa05d6](https://github.com/PixiBixi/freshrss-summary/commit/6aa05d662e621937ac583da3bb3e034f0efd729f)) - Jeremy Delgado
- (**scheduler**) add auto-refresh via APScheduler - ([94025cc](https://github.com/PixiBixi/freshrss-summary/commit/94025ccac99d06dc80981dcba49e45a5a95a4796)) - Jeremy Delgado
- (**scorer**) add feed_weights multiplier to score_article and score_articles - ([1c0cf48](https://github.com/PixiBixi/freshrss-summary/commit/1c0cf480c9cd26af96de21f3f8bf6e522507b432)) - Jeremy Delgado
- (**telegram**) wire scheduler, webhook endpoint, and config into app - ([f338a66](https://github.com/PixiBixi/freshrss-summary/commit/f338a6664080294be94e7d0fdf8f858b9cfeaad0)) - Jeremy Delgado
- (**telegram**) add telegram_digest module with full test coverage - ([eaea1f6](https://github.com/PixiBixi/freshrss-summary/commit/eaea1f66fcad0114212440b153fbcc74756ba2b3)) - Jeremy Delgado
- (**tests**) add CLI handler and route tests for coverage gaps - ([03f4ecd](https://github.com/PixiBixi/freshrss-summary/commit/03f4ecd6bf8bfebfd6027a1ef1971bf55054c0d2)) - Jeremy Delgado
- (**types**) propagate ConfigDict across app, cli, db and telegram_digest - ([38eba67](https://github.com/PixiBixi/freshrss-summary/commit/38eba671752c1465d49a18ecf13084dec1642dc6)) - Jeremy Delgado
- (**types**) add ArticleDict TypedDict and update ScoredArticle.to_dict return type - ([3330b6c](https://github.com/PixiBixi/freshrss-summary/commit/3330b6cf34981bc295c7bfd524ae23e59bf84aad)) - Jeremy Delgado
- (**ui**) add SVG favicon to all pages - ([fe81f45](https://github.com/PixiBixi/freshrss-summary/commit/fe81f455839f7be0502956b9b9faba1fd5d7d05b)) - Jeremy Delgado
- (**ui**) mark-as-read actions remove articles from page immediately - ([d84c256](https://github.com/PixiBixi/freshrss-summary/commit/d84c2561b85aab40224fd358c2c57fac9f0d73d3)) - Jeremy Delgado
- (**ui**) add Topics/Feeds tabs to scoring modal with feed weight rows - ([5f0aa27](https://github.com/PixiBixi/freshrss-summary/commit/5f0aa274a6bbe5582b2721ec94a4814a1805af57)) - Jeremy Delgado
- (**ui**) implement quick win improvements - ([4bdf1b9](https://github.com/PixiBixi/freshrss-summary/commit/4bdf1b9586d2f07e725a97ae22a23ac5a562bf72)) - Jeremy Delgado
- (**ui**) minimal/editorial redesign - ([b176df6](https://github.com/PixiBixi/freshrss-summary/commit/b176df69034471ae0f88609a0660cd17773bf38d)) - Jeremy Delgado
- (**ui**) web interface with i18n (fr/en/de/es/it/pt) - ([0e47ea1](https://github.com/PixiBixi/freshrss-summary/commit/0e47ea139b83ef691f92ef17f374c6c6a3fe2bc8)) - Jeremy Delgado
- make /api/articles and /api/status public (read-only view without login) - ([be62222](https://github.com/PixiBixi/freshrss-summary/commit/be622226556079ce7fa0fec3a5cc1831760d22ae)) - Jeremy Delgado
- snooze reminders, trending alerts, cli digest command - ([db95d9f](https://github.com/PixiBixi/freshrss-summary/commit/db95d9fe9a600a7741174b3c34b6ceb98ab71715)) - Jeremy Delgado
#### Bug Fixes
- (**app**) lazy-evaluate load_config() in get_scoring to avoid crash without credentials - ([a956680](https://github.com/PixiBixi/freshrss-summary/commit/a956680f20b98220867caea53ddd688d9afb28ae)) - Jeremy Delgado
- (**app**) remove require_auth from /api/status (public cache endpoint) - ([70aa690](https://github.com/PixiBixi/freshrss-summary/commit/70aa690306915cce1dadb6e9bb075383d84dc2f6)) - Jeremy Delgado
- (**app**) trust X-Forwarded-For from Traefik for real client IPs - ([8803a23](https://github.com/PixiBixi/freshrss-summary/commit/8803a230a04bed9c2a78e961b057798ce9acaf5b)) - Jeremy Delgado
- (**app**) update TemplateResponse to new Starlette API (request first arg) - ([cc3c9c6](https://github.com/PixiBixi/freshrss-summary/commit/cc3c9c6b076ffb63f63889e4f2d1cc817a4ca8e9)) - Jeremy Delgado
- (**auth**) preserve DB password over ADMIN_PASSWORD env var on restart - ([eee9367](https://github.com/PixiBixi/freshrss-summary/commit/eee93670100831c0b63b4c9e211dec516611b923)) - Jeremy Delgado
- (**auth**) protect /api/status; drop unused dep pins; rename _run_ helpers - ([61c0fdc](https://github.com/PixiBixi/freshrss-summary/commit/61c0fdc465023d0032a1392bcd5851461507873e)) - Jeremy Delgado
- (**cd**) trigger on master instead of main - ([f67578e](https://github.com/PixiBixi/freshrss-summary/commit/f67578e21f252747568ded372941adcdaf531522)) - Jeremy Delgado
- (**ci**) push Helm chart to charts/ subpath to avoid collision with Docker image - ([0a4439a](https://github.com/PixiBixi/freshrss-summary/commit/0a4439a5cd1027a09cc587cc965b21ebd32527b0)) - Jeremy Delgado
- (**ci**) lowercase GHCR owner for Helm OCI push - ([dcdcdb1](https://github.com/PixiBixi/freshrss-summary/commit/dcdcdb1f49e5cfa55cc6969b26638ea23b46e8a4)) - Jeremy Delgado
- (**ci**) build versioned Docker image in release workflow - ([58637f3](https://github.com/PixiBixi/freshrss-summary/commit/58637f3ac8368ae98e1931412f6fca92ddbf5454)) - Jeremy Delgado
- (**ci**) drop redundant uv venv step — setup-uv already creates it - ([10fa38a](https://github.com/PixiBixi/freshrss-summary/commit/10fa38ae7c287c10fbb5d6a5db4e4d9ceef4798e)) - Jeremy Delgado
- (**ci**) use uv venv to avoid externally-managed-environment error - ([fc25f74](https://github.com/PixiBixi/freshrss-summary/commit/fc25f741d58cd27bc3725102532baf609faf2628)) - Jeremy Delgado
- (**db**) raise on unexpected migration errors; remove DEFAULT_TOPICS import; extract _article_to_row helper - ([2dce77b](https://github.com/PixiBixi/freshrss-summary/commit/2dce77be474b168c8d020e4ec0b23b394601f38a)) - Jeremy Delgado
- (**db**) exclude read articles from load_for_rescore to prevent UNIQUE constraint failure - ([bc75de6](https://github.com/PixiBixi/freshrss-summary/commit/bc75de6ed5168d2267dd8c36ce1378195b26afba)) - Jeremy Delgado
- (**deps**) add missing python-multipart for Form data support - ([b3f6559](https://github.com/PixiBixi/freshrss-summary/commit/b3f6559b473b703fc9bdad3cb14646303d88359f)) - Jeremy Delgado
- (**deps**) add missing itsdangerous dependency for SessionMiddleware - ([7f95783](https://github.com/PixiBixi/freshrss-summary/commit/7f95783edee78acb17044509baaf706208809b39)) - Jeremy Delgado
- (**deps**) re-add python-multipart — required by FastAPI Form() - ([dc0e05f](https://github.com/PixiBixi/freshrss-summary/commit/dc0e05faac02141f66646448c8c87af83621f9b6)) - Jeremy Delgado
- (**deps**) re-add itsdangerous — required by starlette SessionMiddleware - ([d230444](https://github.com/PixiBixi/freshrss-summary/commit/d23044487f356036086da4ffcefb79ac6f1cac9f)) - Jeremy Delgado
- (**docker**) COPY . . with proper .dockerignore — avoids missing file errors - ([78c428b](https://github.com/PixiBixi/freshrss-summary/commit/78c428b6f61b4220387b6bf7286a58a21f8b80b7)) - Jeremy Delgado
- (**docker**) add telegram_digest.py to Dockerfile COPY - ([8110cde](https://github.com/PixiBixi/freshrss-summary/commit/8110cde8f74c63846a2648f9457c9ff6271a7181)) - Jeremy Delgado
- (**docker**) use explicit UID/GID 1000 for app user - ([067b2d0](https://github.com/PixiBixi/freshrss-summary/commit/067b2d058fda6cefe18da7caa124d369faee2f10)) - Jeremy Delgado
- (**docker**) run as root — bind mount on /root/files requires it - ([82ab55f](https://github.com/PixiBixi/freshrss-summary/commit/82ab55fa0dfbe87681337d1c57b3626370829300)) - Jeremy Delgado
- (**docker**) add static/ to Dockerfile COPY - ([ef50eaf](https://github.com/PixiBixi/freshrss-summary/commit/ef50eafae03aff013d1a20b2249c076afd38fdc3)) - Jeremy Delgado
- (**error-boundaries**) add logger.exception() at async boundaries and improve exception specificity - ([f255d91](https://github.com/PixiBixi/freshrss-summary/commit/f255d91155285333982f3a8ea539790d96a2cf5e)) - Jeremy Delgado
- (**helm**) correct repo URL and default image registry - ([ac96dca](https://github.com/PixiBixi/freshrss-summary/commit/ac96dca85810d7f93fac0908826dc9f6292a5217)) - Jeremy Delgado
- (**js**) redirect to login on 401 from /api/articles instead of crashing - ([fe67f23](https://github.com/PixiBixi/freshrss-summary/commit/fe67f23c36bd6272d2b684cdc291199460659a09)) - Jeremy Delgado
- (**scoring**) raise feed_weight limit to 10 and surface API error in toast - ([8e5816a](https://github.com/PixiBixi/freshrss-summary/commit/8e5816adf4058b8f6a642dff3ed4b38effbc0456)) - Jeremy Delgado
- (**scoring**) seed DB from built-in defaults when no config.yaml (Docker) - ([8ff2b73](https://github.com/PixiBixi/freshrss-summary/commit/8ff2b733a8b8f3683be042ab0bcf75aef70c3337)) - Jeremy Delgado
- (**security**) rate limit login, fix session fixation, show_read behind auth, remove /api/me - ([cdbc18e](https://github.com/PixiBixi/freshrss-summary/commit/cdbc18e50b196fdba691fc7e01dd1de200656a3a)) - Jeremy Delgado
- (**security**) protect /api/status and /metrics with auth - ([acb61b4](https://github.com/PixiBixi/freshrss-summary/commit/acb61b456bc07a2365257b20a21e0a721f0b9bb8)) - Jeremy Delgado
- (**telegram**) cleaner digest format — score prefix, no feed name - ([e8a17fd](https://github.com/PixiBixi/freshrss-summary/commit/e8a17fdfe4946fff78719ed011754a7fe6609eef)) - Jeremy Delgado
- (**tests**) close unawaited coroutines in asyncio.run mocks to silence RuntimeWarnings - ([c9e10ef](https://github.com/PixiBixi/freshrss-summary/commit/c9e10ef7e0dc842ca4687d2341de4a30942f903f)) - Jeremy Delgado
- (**types**) add typed annotations to remaining bare dict sites - ([2d41b7f](https://github.com/PixiBixi/freshrss-summary/commit/2d41b7f1a445183f80afaafcb52d2d9950d659f1)) - Jeremy Delgado
- (**types**) annotate bare dict → dict[str, Any] throughout codebase - ([e6084b7](https://github.com/PixiBixi/freshrss-summary/commit/e6084b7983e81c63e9e6cf1d1a265664d6910a4e)) - Jeremy Delgado
- (**types**) parametrize bare dict annotations in scorer, freshrss_client, telegram_digest - ([4ccc605](https://github.com/PixiBixi/freshrss-summary/commit/4ccc605fee8de3e249116d0120a18090c7928fe1)) - Jeremy Delgado
- (**types,tests**) fix bare dict annotations and add pipeline/endpoint tests - ([da7fa50](https://github.com/PixiBixi/freshrss-summary/commit/da7fa503ef45324be265734e875cdf50279be902)) - Jeremy Delgado
- (**ui**) load all articles on init, merge SSE increments to fix new-tab state - ([b144b79](https://github.com/PixiBixi/freshrss-summary/commit/b144b79dfa4b83b97fb38a434544cb52c5b57bd9)) - Jeremy Delgado
- (**ui**) graduated feed weight colors — 3 boost levels + 2 malus levels - ([b8cb9ab](https://github.com/PixiBixi/freshrss-summary/commit/b8cb9ab2477c9c06f85f7261a6ade700bc1cb153)) - Jeremy Delgado
- (**ui**) differentiate boost (accent) vs malus (red) feed weight colors - ([dea0c06](https://github.com/PixiBixi/freshrss-summary/commit/dea0c06247d713787d3b615103f9356a4eee1103)) - Jeremy Delgado
- (**ui**) cleaner feed weight rows — muted inputs for defaults, compact rows, proper separator - ([6f8d0d6](https://github.com/PixiBixi/freshrss-summary/commit/6f8d0d65284c1a1fee0e7bbe200bea2e5c96ddfb)) - Jeremy Delgado
- (**ui**) hide reset button on default feeds, add custom/default section separator - ([6bae802](https://github.com/PixiBixi/freshrss-summary/commit/6bae802b890e804450330ccd4688a10309e31440)) - Jeremy Delgado
- (**ui**) sort feed weight rows by multiplier descending, then alphabetically - ([573c80a](https://github.com/PixiBixi/freshrss-summary/commit/573c80ac60b02192a65d0eeb2ba847e853050f36)) - Jeremy Delgado
- (**ui**) show all feeds from DB instead of only currently loaded articles - ([38b46e2](https://github.com/PixiBixi/freshrss-summary/commit/38b46e2013ad4ac0646b5b4147d433d048496f14)) - Jeremy Delgado
- (**ui**) mark-as-read broken in compact mode - ([5500c67](https://github.com/PixiBixi/freshrss-summary/commit/5500c678c0ed7583a0c1fd93d927d9a8c00dffed)) - Jeremy Delgado
- (**ui**) restore 'Summary' in logo text - ([e14dfba](https://github.com/PixiBixi/freshrss-summary/commit/e14dfba9dc1d4d44d1a6bd139a626e39d6e32491)) - Jeremy Delgado
- (**ui**) extend min-score slider range to 0-200 (step 5) - ([120e4d8](https://github.com/PixiBixi/freshrss-summary/commit/120e4d8395866043d037590aaf6d52f99777cabc)) - Jeremy Delgado
- (**ui**) icônes en double dans la palette — supprimer le préfixe c.icon redondant - ([cd41465](https://github.com/PixiBixi/freshrss-summary/commit/cd414651fcc9c3921e406764173cbd2617136c6b)) - Jeremy Delgado
- (**ui**) tooltip score au hover en mode compact - ([eef4c67](https://github.com/PixiBixi/freshrss-summary/commit/eef4c67fa6140d69c2e7f183b3022e0303c3b561)) - Jeremy Delgado
- (**ui**) actions toujours visibles — plus besoin de hover/expand pour Lu et Favoris - ([92748b3](https://github.com/PixiBixi/freshrss-summary/commit/92748b3ca0fb9338995cfe428634832de2eeff8f)) - Jeremy Delgado
- (**ui**) larger text + visible hover (#f0f4f5 on white) - ([b3543a8](https://github.com/PixiBixi/freshrss-summary/commit/b3543a8a2b018ea9a1814d147dafff42d1d2f3c1)) - Jeremy Delgado
- type annotations, docstrings, and logic clarity - ([4624d4b](https://github.com/PixiBixi/freshrss-summary/commit/4624d4b45c2b6b5297f40bba4e5baf7db07618aa)) - Jeremy Delgado
- apply quick-win review findings from holistic review - ([dd009aa](https://github.com/PixiBixi/freshrss-summary/commit/dd009aa35b3ac5873e9ee1a4dbd7e916cfd83e39)) - Jeremy Delgado
#### Performance Improvements
- (**ci**) add GitHub Actions layer cache to Docker build - ([9ecc1cc](https://github.com/PixiBixi/freshrss-summary/commit/9ecc1cc7e5767eafded748531faad309194fde76)) - Jeremy Delgado
#### Revert
- (**security**) keep /api/status public for unauthenticated status visibility - ([3963521](https://github.com/PixiBixi/freshrss-summary/commit/39635215453cbc36e9d57a6e22de3dc90ade7988)) - Jeremy Delgado
#### Documentation
- (**claude**) fix JS file map, add auth model, pre-commit hook note - ([64c45ac](https://github.com/PixiBixi/freshrss-summary/commit/64c45ac0d39bf23eb31a78c4a60b4fe47359de60)) - Jeremy Delgado
- (**readme**) add Code Quality section with scorecard - ([1425936](https://github.com/PixiBixi/freshrss-summary/commit/1425936418b0e2d9967255412b7076ae818fcedb)) - Jeremy Delgado
- (**readme**) update for feed weights and mark-as-read UX - ([95c333b](https://github.com/PixiBixi/freshrss-summary/commit/95c333bca3719464d412cd0b787273d366cdcf05)) - Jeremy Delgado
- feed weights implementation plan - ([880a310](https://github.com/PixiBixi/freshrss-summary/commit/880a31006f896332f1e061b0bdcd28da470eaf07)) - Jeremy Delgado
- feed weights design spec - ([e406fa4](https://github.com/PixiBixi/freshrss-summary/commit/e406fa4657fa1ce5ad2a317b2138a0ddbd593510)) - Jeremy Delgado
- update README — show_read requires auth, login rate limiting - ([77385e1](https://github.com/PixiBixi/freshrss-summary/commit/77385e1d7c541be5db35578f5ea5df6f38ec94cb)) - Jeremy Delgado
- add Telegram digest implementation plan - ([2064fad](https://github.com/PixiBixi/freshrss-summary/commit/2064fadca921795be4c12af9e99a8958af51e6bf)) - Jeremy Delgado
- add Telegram digest design spec - ([49d89af](https://github.com/PixiBixi/freshrss-summary/commit/49d89af411d2f533b980ceffa96d6b0ad41e905f)) - Jeremy Delgado
- UI redesign spec — minimal/editorial direction - ([546b3d7](https://github.com/PixiBixi/freshrss-summary/commit/546b3d794d083ce746df8e203629c7275293f325)) - Jeremy Delgado
- document auto-refresh scheduler in README - ([ac28629](https://github.com/PixiBixi/freshrss-summary/commit/ac28629e45ddddfe2adf77c6735fcc68fe5e5e4f)) - Jeremy Delgado
- README, architecture notes, CLAUDE context - ([a705a2a](https://github.com/PixiBixi/freshrss-summary/commit/a705a2a14279f8427cc57327e8c7a65552809b59)) - Jeremy Delgado
#### Tests
- (**app**) add TestRefreshStream covering SSE fetch→score→stream paths - ([02bfd76](https://github.com/PixiBixi/freshrss-summary/commit/02bfd76e7d4e5c8e82b40a6f7a01563d863292f5)) - Jeremy Delgado
- (**integration**) add set_engine_for_testing helper and roundtrip test - ([0f508b9](https://github.com/PixiBixi/freshrss-summary/commit/0f508b95420a58dcdab188d71650053b9d4680cc)) - Jeremy Delgado
- add coverage for /api/config/scoring, /api/change-password, /api/feeds, /metrics - ([277cd5d](https://github.com/PixiBixi/freshrss-summary/commit/277cd5d88f5b4b2d49675cf90761a0b2a8669d59)) - Jeremy Delgado
- add route handler and CLI command tests - ([75166ea](https://github.com/PixiBixi/freshrss-summary/commit/75166ea856c1636be81a588b79d4e4c223ab04c9)) - Jeremy Delgado
- unit tests — 114 tests across scorer, db, client, app, cli - ([a107236](https://github.com/PixiBixi/freshrss-summary/commit/a1072365390639f5102b6132985feb03ead56118)) - Jeremy Delgado
#### Continuous Integration
- (**release**) add multi-arch build (linux/amd64 + linux/arm64) via QEMU - ([b57ce69](https://github.com/PixiBixi/freshrss-summary/commit/b57ce6960649883958baea3e7ce3e98ca8301c9b)) - Jeremy Delgado
- (**release**) push Helm chart to GHCR OCI on release - ([e5f3e3f](https://github.com/PixiBixi/freshrss-summary/commit/e5f3e3f648f67405821433e5d13d0958a631416a)) - Jeremy Delgado
- add release-please semver workflow - ([3f3052e](https://github.com/PixiBixi/freshrss-summary/commit/3f3052e7cb0f13d9abd02035f74e71f932f66d1e)) - Jeremy Delgado
- add lint and test workflows - ([95ceff4](https://github.com/PixiBixi/freshrss-summary/commit/95ceff4c6b5ccd718efeffa1b904074a005acf0a)) - Jeremy Delgado
#### Refactoring
- (**app**) decompose monolith — extract metrics.py, scheduler.py, logging_config.py - ([361a7eb](https://github.com/PixiBixi/freshrss-summary/commit/361a7ebc5f9abfa051a3416fb8b9d33542aff4eb)) - Jeremy Delgado
- (**app**) fix design coherence — naming, factory, SSE state routing - ([dfb91fa](https://github.com/PixiBixi/freshrss-summary/commit/dfb91fadb005dbb1a61b5ded8ebf5ad3bddee754)) - Jeremy Delgado
- (**app**) remove _get_or_seed_scoring_config thin wrapper - ([64d9b75](https://github.com/PixiBixi/freshrss-summary/commit/64d9b75a11286d5da442e301078cb4ec7ce945f2)) - Jeremy Delgado
- (**app**) lazy Prometheus singleton and deferred session key reading - ([4e0c4a1](https://github.com/PixiBixi/freshrss-summary/commit/4e0c4a15d3d9ddd54c557ecb29c24a4b9cbdb660)) - Jeremy Delgado
- (**app**) decouple module-scope init and thread-pool side effects - ([caf3f80](https://github.com/PixiBixi/freshrss-summary/commit/caf3f80c06c10003edbf4261cc7bea3287c982d6)) - Jeremy Delgado
- (**arch**) extract auth helpers to auth.py - ([285f3fc](https://github.com/PixiBixi/freshrss-summary/commit/285f3fcd3ecfee32eae698c3e0ea90994ffe0bce)) - Jeremy Delgado
- (**arch**) extract Article domain model to models.py - ([cea984e](https://github.com/PixiBixi/freshrss-summary/commit/cea984eb346c4ced44b0561f510782320dbc8b00)) - Jeremy Delgado
- (**cli**) collapse thin DB wrappers and unify DB-first topic resolution - ([0f72296](https://github.com/PixiBixi/freshrss-summary/commit/0f72296bf0103b985d85b89987260b2567d5acb9)) - Jeremy Delgado
- (**config**) route get_secret_key through config.py instead of raw yaml - ([fe6e684](https://github.com/PixiBixi/freshrss-summary/commit/fe6e6849e2b82259d990061fc8667d28e2355fe3)) - Jeremy Delgado
- (**pipeline**) extract shared fetch-score-rescore layer - ([11b8308](https://github.com/PixiBixi/freshrss-summary/commit/11b830890ed874e9df9a57deb576785ddbdade4c)) - Jeremy Delgado
- (**pipeline**) extract _persist_and_populate to eliminate duplication - ([032c651](https://github.com/PixiBixi/freshrss-summary/commit/032c6513be96de03e51ef292f8fa4ad8ce486d06)) - Jeremy Delgado
- (**scheduler**) replace APScheduler with asyncio-native task loops - ([eb2e95e](https://github.com/PixiBixi/freshrss-summary/commit/eb2e95e63d583511b71da4664f885451fcb8d1e9)) - Jeremy Delgado
- hygiene-batch, type-safety, cli-quality, contract-cleanup fixes - ([dba70a2](https://github.com/PixiBixi/freshrss-summary/commit/dba70a21d3b10d87bbc02da3feca182a079afb28)) - Jeremy Delgado
- add FreshRSSConfig TypedDict to config.py - ([e636bfd](https://github.com/PixiBixi/freshrss-summary/commit/e636bfd07c6bd9c02766eb93f605d9448caf4d25)) - Jeremy Delgado
- move DEFAULT_TOPICS from config.py to scorer.py - ([47aaa8b](https://github.com/PixiBixi/freshrss-summary/commit/47aaa8b43851ced0c8aa9c2f65fb30552b02db63)) - Jeremy Delgado
- telegram-api-fix and app-decomposition-v3 partial - ([c6ac147](https://github.com/PixiBixi/freshrss-summary/commit/c6ac1475121e4f00aa72c70f7c7e9670d029ea58)) - Jeremy Delgado
- naming/logic quick-wins and api consistency fixes - ([5f76a02](https://github.com/PixiBixi/freshrss-summary/commit/5f76a02982d753ca438b179836092f16b9bc75ae)) - Jeremy Delgado
- TelegramConfig dataclass + cache.initialized guard - ([a46465a](https://github.com/PixiBixi/freshrss-summary/commit/a46465a666cff46c615c900be7478b9fb2e7682c)) - Jeremy Delgado
- multiple elegance and clarity improvements - ([d0b6693](https://github.com/PixiBixi/freshrss-summary/commit/d0b66930fe38afa7f5ae9b45e154c9085e77e3fc)) - Jeremy Delgado
- extract fetch/score generator, db public API, move DEFAULT_TOPICS - ([1729f17](https://github.com/PixiBixi/freshrss-summary/commit/1729f176017c4e12e2a085ddc495c89116f78a75)) - Jeremy Delgado
- extract shared config module, fix auth gaps, fix api signatures - ([6c44d4e](https://github.com/PixiBixi/freshrss-summary/commit/6c44d4e21fbd5aceaac4d1d7ccd5531f1df6ee99)) - Jeremy Delgado
#### Miscellaneous Chores
- (**ci**) remove cd.yml — image build handled by release.yml on tags only - ([ed9670a](https://github.com/PixiBixi/freshrss-summary/commit/ed9670a4c1618e1d6a5eeb36c36dc2b7bd91cded)) - Jeremy Delgado
- (**deps**) update uv.lock - ([bf54a94](https://github.com/PixiBixi/freshrss-summary/commit/bf54a940218eb955a1f689240d339481c6ea2076)) - Jeremy Delgado
- (**deps**) pin greenlet==3.5.0 - ([15653a2](https://github.com/PixiBixi/freshrss-summary/commit/15653a21fde182d993abb5a1a69f9e1ba27ac047)) - Jeremy Delgado
- (**master**) release 1.7.1 - ([94a8260](https://github.com/PixiBixi/freshrss-summary/commit/94a8260e930648c8f213d422198962f8a15aa32d)) - github-actions[bot]
- (**master**) release 1.7.0 - ([f6cdb33](https://github.com/PixiBixi/freshrss-summary/commit/f6cdb338bf24a11b3d48eaa4ae85cb5b611f9a80)) - github-actions[bot]
- (**master**) release 1.6.3 - ([38c191b](https://github.com/PixiBixi/freshrss-summary/commit/38c191b4f96df9a6e9f0e084153bc045770232f6)) - github-actions[bot]
- (**master**) release 1.6.2 - ([2b40716](https://github.com/PixiBixi/freshrss-summary/commit/2b407160f0ee18ddd95a55d1e1632586d4c9fb2d)) - github-actions[bot]
- (**master**) release 1.6.1 - ([85c4c49](https://github.com/PixiBixi/freshrss-summary/commit/85c4c495d8a8ecd82831e6771c342639ff4ff125)) - github-actions[bot]
- (**master**) release 1.6.0 - ([e4d067d](https://github.com/PixiBixi/freshrss-summary/commit/e4d067d0f52c851494bc569fad2b764579cd67de)) - github-actions[bot]
- (**master**) release 1.5.0 - ([706b422](https://github.com/PixiBixi/freshrss-summary/commit/706b422993f0d4d391779ff4c5a77854d9d89d48)) - github-actions[bot]
- (**master**) release 1.4.1 - ([670abb0](https://github.com/PixiBixi/freshrss-summary/commit/670abb06a806a1016b74e5c91d8e24816189d329)) - github-actions[bot]
- (**master**) release 1.4.0 - ([54ef0ee](https://github.com/PixiBixi/freshrss-summary/commit/54ef0ee628db360fa20f8e9527ec3fd8acb9772a)) - github-actions[bot]
- (**master**) release 1.3.2 - ([d8e9c0d](https://github.com/PixiBixi/freshrss-summary/commit/d8e9c0db0c6c4c876136330c6b74e5ecd07dc57b)) - github-actions[bot]
- (**master**) release 1.3.1 - ([d29f948](https://github.com/PixiBixi/freshrss-summary/commit/d29f9483d99a0d561f53bc369601918c079f4856)) - github-actions[bot]
- (**master**) release 1.3.0 - ([2e7ab3c](https://github.com/PixiBixi/freshrss-summary/commit/2e7ab3ca4a22dbb918aa877e71e9ad74c9fd6db8)) - github-actions[bot]
- (**master**) release 1.2.1 - ([966b91e](https://github.com/PixiBixi/freshrss-summary/commit/966b91e5577d8273c2d36f80fd3fb6f0cc6e9363)) - github-actions[bot]
- (**master**) release 1.2.0 - ([badb879](https://github.com/PixiBixi/freshrss-summary/commit/badb8790017c8603851fb81c8572df4c3d84122f)) - github-actions[bot]
- (**master**) release 1.1.0 - ([ca2865e](https://github.com/PixiBixi/freshrss-summary/commit/ca2865ec57f9ed28aad7421488ec86ded9d7cf1c)) - github-actions[bot]
- (**master**) release 1.0.2 - ([6c78424](https://github.com/PixiBixi/freshrss-summary/commit/6c78424089f98a4072db2c1409ac416da869743d)) - github-actions[bot]
- (**master**) release 1.0.1 - ([cd4db06](https://github.com/PixiBixi/freshrss-summary/commit/cd4db06132747f49593fea009f39243444e8e84b)) - github-actions[bot]
- (**master**) release 1.0.0 - ([2e207d8](https://github.com/PixiBixi/freshrss-summary/commit/2e207d8e56ab9e389bd805c1371fbf64460b49c5)) - github-actions[bot]
- (**pre-commit**) exclude helm templates from check-yaml - ([406fa67](https://github.com/PixiBixi/freshrss-summary/commit/406fa67e77f373375b3987676b728c3fea55c7bb)) - Jeremy Delgado
- (**ui**) track favicon.svg in version control - ([8b04c77](https://github.com/PixiBixi/freshrss-summary/commit/8b04c779c8ab3d0a954aed3406ac7d037a413599)) - Jeremy Delgado
- remove .claude/ from tracking and add to .gitignore - ([734beb2](https://github.com/PixiBixi/freshrss-summary/commit/734beb269e6211544d3c67280e848a3f0b51ea51)) - Jeremy Delgado
- update scorecard and add greenlet to requirements - ([5b20d7e](https://github.com/PixiBixi/freshrss-summary/commit/5b20d7e836460d2950688a0b1d5ee42bc2f515d7)) - Jeremy Delgado
- untrack internal design specs from git - ([5d5aa28](https://github.com/PixiBixi/freshrss-summary/commit/5d5aa28757c077c7c2d50cf3202ce401ad1dbb1d)) - Jeremy Delgado
- project setup — Python tooling, linting, pre-commit, uv - ([51e2bb7](https://github.com/PixiBixi/freshrss-summary/commit/51e2bb70d9d61993ffe453e76137088c5343a931)) - Jeremy Delgado
