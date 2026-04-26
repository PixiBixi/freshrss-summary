# Changelog

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
