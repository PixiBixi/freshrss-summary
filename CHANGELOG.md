# Changelog

## [1.2.1](https://github.com/PixiBixi/freshrss-summary/compare/v1.2.0...v1.2.1) (2026-04-26)


### Bug Fixes

* **docker:** add telegram_digest.py to Dockerfile COPY ([8110cde](https://github.com/PixiBixi/freshrss-summary/commit/8110cde8f74c63846a2648f9457c9ff6271a7181))

## [1.2.0](https://github.com/PixiBixi/freshrss-summary/compare/v1.1.0...v1.2.0) (2026-04-26)


### Features

* **auth:** gate mark-as-read and bookmark actions behind authentication ([5971f9e](https://github.com/PixiBixi/freshrss-summary/commit/5971f9eeda5299fa6f7e549edc733a2c8171bfb5))
* **docker:** add Telegram env vars to docker-compose ([daf8cd7](https://github.com/PixiBixi/freshrss-summary/commit/daf8cd74146e3750954b5d1b0a799db537faab3d))
* **telegram:** add telegram_digest module with full test coverage ([eaea1f6](https://github.com/PixiBixi/freshrss-summary/commit/eaea1f66fcad0114212440b153fbcc74756ba2b3))
* **telegram:** wire scheduler, webhook endpoint, and config into app ([f338a66](https://github.com/PixiBixi/freshrss-summary/commit/f338a6664080294be94e7d0fdf8f858b9cfeaad0))
* **ui:** implement quick win improvements ([4bdf1b9](https://github.com/PixiBixi/freshrss-summary/commit/4bdf1b9586d2f07e725a97ae22a23ac5a562bf72))
* **ui:** minimal/editorial redesign ([b176df6](https://github.com/PixiBixi/freshrss-summary/commit/b176df69034471ae0f88609a0660cd17773bf38d))


### Bug Fixes

* **ui:** actions toujours visibles — plus besoin de hover/expand pour Lu et Favoris ([92748b3](https://github.com/PixiBixi/freshrss-summary/commit/92748b3ca0fb9338995cfe428634832de2eeff8f))
* **ui:** extend min-score slider range to 0-200 (step 5) ([120e4d8](https://github.com/PixiBixi/freshrss-summary/commit/120e4d8395866043d037590aaf6d52f99777cabc))
* **ui:** icônes en double dans la palette — supprimer le préfixe c.icon redondant ([cd41465](https://github.com/PixiBixi/freshrss-summary/commit/cd414651fcc9c3921e406764173cbd2617136c6b))
* **ui:** larger text + visible hover (#f0f4f5 on white) ([b3543a8](https://github.com/PixiBixi/freshrss-summary/commit/b3543a8a2b018ea9a1814d147dafff42d1d2f3c1))
* **ui:** restore 'Summary' in logo text ([e14dfba](https://github.com/PixiBixi/freshrss-summary/commit/e14dfba9dc1d4d44d1a6bd139a626e39d6e32491))
* **ui:** tooltip score au hover en mode compact ([eef4c67](https://github.com/PixiBixi/freshrss-summary/commit/eef4c67fa6140d69c2e7f183b3022e0303c3b561))

## [1.1.0](https://github.com/PixiBixi/freshrss-summary/compare/v1.0.2...v1.1.0) (2026-04-26)


### Features

* **scheduler:** add auto-refresh via APScheduler ([94025cc](https://github.com/PixiBixi/freshrss-summary/commit/94025ccac99d06dc80981dcba49e45a5a95a4796))

## [1.0.2](https://github.com/PixiBixi/freshrss-summary/compare/v1.0.1...v1.0.2) (2026-04-26)


### Bug Fixes

* **app:** trust X-Forwarded-For from Traefik for real client IPs ([8803a23](https://github.com/PixiBixi/freshrss-summary/commit/8803a230a04bed9c2a78e961b057798ce9acaf5b))

## [1.0.1](https://github.com/PixiBixi/freshrss-summary/compare/v1.0.0...v1.0.1) (2026-04-26)


### Bug Fixes

* **ci:** build versioned Docker image in release workflow ([58637f3](https://github.com/PixiBixi/freshrss-summary/commit/58637f3ac8368ae98e1931412f6fca92ddbf5454))

## 1.0.0 (2026-04-26)


### Features

* **auth:** add change-password feature via UI modal ([3f47a2d](https://github.com/PixiBixi/freshrss-summary/commit/3f47a2d79d626d5950e157cb8044bb3679b2f5fa))
* **auth:** add change-password UI modal ([865f21c](https://github.com/PixiBixi/freshrss-summary/commit/865f21c8da91ccf61f5793c6a28b7163c6c37b5e))
* **backend:** FastAPI app, FreshRSS client, scorer, DB, CLI ([a1b4821](https://github.com/PixiBixi/freshrss-summary/commit/a1b482163dd3b706bea78d1a28366a2e54a94d39))
* **docker:** add Dockerfile ([b8b52db](https://github.com/PixiBixi/freshrss-summary/commit/b8b52dbb55657ef0084e3e24159d754ff68cc51d))
* **helm:** Kubernetes Helm chart ([faf0e55](https://github.com/PixiBixi/freshrss-summary/commit/faf0e5528f55548f6c56ea03aaa5e210ddc3ce28))
* **ui:** web interface with i18n (fr/en/de/es/it/pt) ([0e47ea1](https://github.com/PixiBixi/freshrss-summary/commit/0e47ea139b83ef691f92ef17f374c6c6a3fe2bc8))


### Bug Fixes

* **app:** update TemplateResponse to new Starlette API (request first arg) ([cc3c9c6](https://github.com/PixiBixi/freshrss-summary/commit/cc3c9c6b076ffb63f63889e4f2d1cc817a4ca8e9))
* **cd:** trigger on master instead of main ([f67578e](https://github.com/PixiBixi/freshrss-summary/commit/f67578e21f252747568ded372941adcdaf531522))
* **ci:** drop redundant uv venv step — setup-uv already creates it ([10fa38a](https://github.com/PixiBixi/freshrss-summary/commit/10fa38ae7c287c10fbb5d6a5db4e4d9ceef4798e))
* **ci:** use uv venv to avoid externally-managed-environment error ([fc25f74](https://github.com/PixiBixi/freshrss-summary/commit/fc25f741d58cd27bc3725102532baf609faf2628))
* **docker:** add static/ to Dockerfile COPY ([ef50eaf](https://github.com/PixiBixi/freshrss-summary/commit/ef50eafae03aff013d1a20b2249c076afd38fdc3))
* **docker:** run as root — bind mount on /root/files requires it ([82ab55f](https://github.com/PixiBixi/freshrss-summary/commit/82ab55fa0dfbe87681337d1c57b3626370829300))
* **docker:** use explicit UID/GID 1000 for app user ([067b2d0](https://github.com/PixiBixi/freshrss-summary/commit/067b2d058fda6cefe18da7caa124d369faee2f10))
* **helm:** correct repo URL and default image registry ([ac96dca](https://github.com/PixiBixi/freshrss-summary/commit/ac96dca85810d7f93fac0908826dc9f6292a5217))
* **scoring:** seed DB from built-in defaults when no config.yaml (Docker) ([8ff2b73](https://github.com/PixiBixi/freshrss-summary/commit/8ff2b733a8b8f3683be042ab0bcf75aef70c3337))
