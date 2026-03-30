#!/usr/bin/env python3
"""FreshRSS Summary — CLI."""

import argparse
import asyncio
import datetime
import json
import os
import sys
import time
from pathlib import Path

import yaml

# ── ANSI ───────────────────────────────────────────────────────────────────


def _c(code: str) -> str:
    return f"\033[{code}m" if sys.stdout.isatty() else ""


RESET = _c("0")
BOLD = _c("1")
DIM = _c("2")
GREEN = _c("32")
YELLOW = _c("33")
CYAN = _c("36")
RED = _c("31")


def ok(msg: str) -> str:
    return f"{GREEN}✓{RESET}  {msg}"


def warn(msg: str) -> str:
    return f"{YELLOW}⚠{RESET}  {msg}"


def err(msg: str) -> str:
    return f"{RED}✗{RESET}  {msg}"


def info(msg: str) -> str:
    return f"{CYAN}·{RESET}  {msg}"


# ── Config ─────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
    else:
        print(warn("config.yaml not found — relying on environment variables"))

    fr = cfg.setdefault("freshrss", {})
    if v := os.environ.get("FRESHRSS_URL"):
        fr["url"] = v
    if v := os.environ.get("FRESHRSS_USERNAME"):
        fr["username"] = v
    if v := os.environ.get("FRESHRSS_API_PASSWORD"):
        fr["api_password"] = v

    db = cfg.setdefault("database", {})
    if v := os.environ.get("DATABASE_URL"):
        db["url"] = v

    missing = [k for k in ("url", "username", "api_password") if not fr.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing FreshRSS config: {', '.join(missing)}. "
            "Set them in config.yaml (freshrss.url / username / api_password) "
            "or via FRESHRSS_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
        )
    return cfg


def make_client(cfg: dict):
    from freshrss_client import FreshRSSClient

    fr = cfg["freshrss"]
    return FreshRSSClient(fr["url"], fr["username"], fr["api_password"])


# ── DB helpers (async) ─────────────────────────────────────────────────────


async def _init_db(cfg: dict) -> None:
    from db import DEFAULT_DB_URL, init_db

    db_url = cfg.get("database", {}).get("url", DEFAULT_DB_URL)
    await init_db(db_url)


async def _db_stats(cfg: dict) -> dict:
    from db import get_bookmarked_ids, load_articles

    await _init_db(cfg)
    articles, last_refresh, total_fetched = await load_articles()
    bookmarks = await get_bookmarked_ids()
    return {
        "articles": len(articles),
        "total_fetched": total_fetched,
        "last_refresh": last_refresh,
        "bookmarks": len(bookmarks),
        "topics": sorted({t for a in articles for t in a["matched_topics"]}),
    }


async def _save(cfg: dict, articles: list[dict], total_fetched: int) -> None:
    from db import save_articles

    await _init_db(cfg)
    await save_articles(articles, total_fetched)


async def _load_for_rescore(cfg: dict) -> list[dict]:
    from db import load_for_rescore

    await _init_db(cfg)
    return await load_for_rescore()


async def _upsert_articles(cfg: dict, articles: list[dict]) -> None:
    """Insert-or-replace articles without wiping the full table."""
    import json as _json

    from sqlalchemy import delete, insert

    from db import articles_table, get_engine

    await _init_db(cfg)
    now = int(time.time())
    rows = [
        {
            "id": a["id"],
            "title": a["title"],
            "url": a["url"],
            "feed_title": a["feed_title"],
            "published": a["published"],
            "score": a["score"],
            "matched_topics": _json.dumps(a["matched_topics"]),
            "matched_keywords": _json.dumps(a["matched_keywords"]),
            "top_topic": a.get("top_topic"),
            "summary": a["summary"],
            "content": a.get("_content", a["summary"]),
            "fetched_at": now,
        }
        for a in articles
    ]
    ids = [r["id"] for r in rows]
    async with get_engine().begin() as conn:
        await conn.execute(delete(articles_table).where(articles_table.c.id.in_(ids)))
        if rows:
            await conn.execute(insert(articles_table), rows)


async def _bookmark_all(cfg: dict, ids: list[str]) -> None:
    """Mark a list of article IDs as bookmarked (skip existing)."""
    from sqlalchemy import insert, select

    from db import bookmarks_table, get_engine

    await _init_db(cfg)
    now = int(time.time())
    async with get_engine().begin() as conn:
        existing = {
            r[0]
            for r in (
                await conn.execute(
                    select(bookmarks_table.c.id).where(bookmarks_table.c.id.in_(ids))
                )
            ).all()
        }
        new_ids = [i for i in ids if i not in existing]
        if new_ids:
            await conn.execute(
                insert(bookmarks_table),
                [{"id": i, "bookmarked_at": now} for i in new_ids],
            )


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_check(args, cfg: dict) -> int:
    """Test FreshRSS connection and DB reachability."""
    fr = cfg["freshrss"]
    print(f"\n{BOLD}FreshRSS connection check{RESET}\n")
    print(info(f"URL      : {fr['url']}"))
    print(info(f"Username : {fr['username']}"))
    print()

    try:
        with make_client(cfg) as client:
            client._login()
            print(ok("Auth OK"))

            batch, _ = client._fetch_batch(None, 1)
            print(ok(f"Reading-list API reachable ({len(batch)} article sampled)"))

            starred = client.fetch_starred(max_items=10)
            print(ok(f"Starred stream reachable ({len(starred)} fetched, limited to 10)"))
    except Exception as e:
        print(err(f"FreshRSS error: {e}"))
        return 1

    print()
    try:
        s = asyncio.run(_db_stats(cfg))
        db_url = cfg.get("database", {}).get("url", "sqlite (default)")
        print(info(f"DB URL   : {db_url}"))
        print(ok(f"DB reachable — {s['articles']} articles, {s['bookmarks']} bookmarks"))
    except Exception as e:
        print(warn(f"DB check failed: {e}"))

    print()
    return 0


def cmd_stats(args, cfg: dict) -> int:
    """Show DB statistics."""
    print(f"\n{BOLD}DB statistics{RESET}\n")
    try:
        s = asyncio.run(_db_stats(cfg))
    except Exception as e:
        print(err(f"DB error: {e}"))
        return 1

    print(info(f"Articles stored  : {BOLD}{s['articles']}{RESET}"))
    print(info(f"Total fetched    : {s['total_fetched']}"))
    print(info(f"Bookmarks        : {s['bookmarks']}"))

    if s["last_refresh"]:
        dt = datetime.datetime.fromtimestamp(s["last_refresh"]).strftime("%Y-%m-%d %H:%M:%S")
        print(info(f"Last refresh     : {dt}"))
    else:
        print(info("Last refresh     : never"))

    if s["topics"]:
        print(f"\n{BOLD}Topics in DB:{RESET}")
        for t in s["topics"]:
            print(f"    · {t}")

    print()
    return 0


def cmd_fetch(args, cfg: dict) -> int:
    """Fetch unread articles from FreshRSS, score and save to DB."""
    print(f"\n{BOLD}Fetching unread articles{RESET}\n")

    fetch_cfg = cfg.get("fetch", {})
    scoring_cfg = cfg.get("scoring", {})
    batch_size = fetch_cfg.get("batch_size", 1000)
    max_batches = fetch_cfg.get("max_batches", 10)
    title_weight = scoring_cfg.get("title_weight", 3)
    min_score = scoring_cfg.get("min_score", 1.0)

    from scorer import build_topics, score_articles

    topics = build_topics(cfg)
    if not topics:
        print(warn("No topics configured — articles will score 0"))

    all_scored = []
    total_fetched = 0

    try:
        with make_client(cfg) as client:
            for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
                total_fetched += len(batch)
                scored = score_articles(batch, topics, title_weight, min_score=0)
                relevant = sum(1 for a in scored if a.score >= min_score)
                all_scored.extend(scored)
                print(info(f"Batch: {len(batch)} fetched, {relevant} relevant"))
    except Exception as e:
        print(err(f"Fetch error: {e}"))
        return 1

    if total_fetched == 0:
        print(warn("No unread articles"))
        return 0

    relevant = sorted(
        (a for a in all_scored if a.score >= min_score),
        key=lambda a: a.score,
        reverse=True,
    )
    print()
    print(ok(f"{total_fetched} fetched total — {len(relevant)} relevant (score ≥ {min_score})"))

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
        if relevant:
            print(f"\n{BOLD}Top 5:{RESET}")
            for a in relevant[:5]:
                print(f"    [{a.score:.0f}]  {a.article.title[:72]}")
    else:
        try:
            asyncio.run(_save(cfg, [a.to_dict() for a in relevant], total_fetched))
            print(ok("Saved to DB"))
        except Exception as e:
            print(err(f"DB save failed: {e}"))
            return 1

    print()
    return 0


def cmd_rescore(args, cfg: dict) -> int:
    """Rescore DB articles with the current config weights."""
    print(f"\n{BOLD}Rescoring from DB{RESET}\n")

    scoring_cfg = cfg.get("scoring", {})
    title_weight = scoring_cfg.get("title_weight", 3)
    min_score = scoring_cfg.get("min_score", 1.0)

    from freshrss_client import Article
    from scorer import build_topics, score_article

    topics = build_topics(cfg)

    try:
        raw = asyncio.run(_load_for_rescore(cfg))
    except Exception as e:
        print(err(f"DB load failed: {e}"))
        return 1

    if not raw:
        print(warn("No articles in DB — run fetch first"))
        return 0

    print(info(f"Rescoring {len(raw)} articles..."))
    rescored = []
    for r in raw:
        art = Article(
            id=r["id"],
            title=r["title"],
            url=r["url"],
            content=r["content"],
            summary="",
            feed_title=r["feed_title"],
            published=r["published"],
        )
        scored = score_article(art, topics, title_weight)
        if scored.score >= min_score:
            rescored.append(scored.to_dict())

    rescored.sort(key=lambda a: a["score"], reverse=True)
    print(ok(f"{len(rescored)} articles above min_score={min_score}"))

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
    else:
        try:
            asyncio.run(_save(cfg, rescored, len(raw)))
            print(ok("Saved to DB"))
        except Exception as e:
            print(err(f"DB save failed: {e}"))
            return 1

    print()
    return 0


def cmd_import(args, cfg: dict) -> int:
    """Import articles from a JSON file or from FreshRSS starred."""
    if args.starred:
        return _import_starred(args, cfg)
    if not args.file:
        print(err("Provide a JSON file path or use --starred"))
        return 1
    return _import_file(args, cfg)


def _import_starred(args, cfg: dict) -> int:
    """Fetch starred items from FreshRSS, score and import into DB + bookmarks."""
    print(f"\n{BOLD}Importing FreshRSS starred articles{RESET}\n")

    scoring_cfg = cfg.get("scoring", {})
    title_weight = scoring_cfg.get("title_weight", 3)
    max_items = args.limit or 500

    from scorer import build_topics, score_articles

    topics = build_topics(cfg)

    try:
        with make_client(cfg) as client:
            print(info(f"Fetching up to {max_items} starred articles..."))
            starred = client.fetch_starred(max_items=max_items)
    except Exception as e:
        print(err(f"Fetch error: {e}"))
        return 1

    if not starred:
        print(warn("No starred articles found"))
        return 0

    print(ok(f"Fetched {len(starred)} starred articles"))
    scored = score_articles(starred, topics, title_weight, min_score=0)

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
        for a in scored[:5]:
            print(f"    [{a.score:.0f}]  {a.article.title[:72]}")
    else:
        try:
            dicts = [a.to_dict() for a in scored]
            asyncio.run(_upsert_articles(cfg, dicts))
            asyncio.run(_bookmark_all(cfg, [a.article.id for a in scored]))
            print(ok(f"Imported {len(scored)} articles — all bookmarked"))
        except Exception as e:
            print(err(f"DB error: {e}"))
            return 1

    print()
    return 0


def _import_file(args, cfg: dict) -> int:
    """Import articles from a JSON file (list of article objects)."""
    path = Path(args.file)
    print(f"\n{BOLD}Importing from {path.name}{RESET}\n")

    if not path.exists():
        print(err(f"File not found: {path}"))
        return 1

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(err(f"JSON parse error: {e}"))
        return 1

    if not isinstance(data, list):
        print(err("JSON must be a list of article objects"))
        return 1

    from freshrss_client import Article
    from scorer import build_topics, score_articles

    articles, skipped = [], 0
    for item in data:
        if "id" not in item:
            skipped += 1
            continue
        articles.append(
            Article(
                id=item["id"],
                title=item.get("title", "(no title)"),
                url=item.get("url", ""),
                content=item.get("content", item.get("_content", "")),
                summary=item.get("summary", ""),
                feed_title=item.get("feed_title", "imported"),
                published=item.get("published", 0),
            )
        )

    if skipped:
        print(warn(f"Skipped {skipped} items without 'id' field"))
    print(info(f"Parsed {len(articles)} articles"))

    scoring_cfg = cfg.get("scoring", {})
    title_weight = scoring_cfg.get("title_weight", 3)
    topics = build_topics(cfg)
    scored = score_articles(articles, topics, title_weight, min_score=0)

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
        for a in scored[:5]:
            print(f"    [{a.score:.0f}]  {a.article.title[:72]}")
    else:
        try:
            asyncio.run(_upsert_articles(cfg, [a.to_dict() for a in scored]))
            print(ok(f"Imported {len(scored)} articles"))
        except Exception as e:
            print(err(f"DB error: {e}"))
            return 1

    print()
    return 0


def cmd_tune(args, cfg: dict) -> int:
    """
    Analyze FreshRSS starred articles and suggest weight adjustments.

    The idea: articles you star in FreshRSS are implicit positive signals.
    If topic X appears in 60% of your favorites, its weight probably deserves a boost.
    Formula: suggested = current * (1 + 0.5 * hit_rate)
    """
    print(f"\n{BOLD}Scoring tune — analyzing your starred articles{RESET}\n")

    from scorer import analyze_favorites, build_topics

    topics = build_topics(cfg)
    max_items = args.limit or 200

    if not topics:
        print(err("No topics configured in config.yaml"))
        return 1

    try:
        with make_client(cfg) as client:
            print(info(f"Fetching up to {max_items} starred articles..."))
            starred = client.fetch_starred(max_items=max_items)
    except Exception as e:
        print(err(f"Fetch error: {e}"))
        return 1

    if not starred:
        print(warn("No starred articles found — star some articles in FreshRSS first!"))
        return 0

    print(ok(f"Fetched {len(starred)} starred articles"))
    print()

    scoring_cfg = cfg.get("scoring", {})
    title_weight = scoring_cfg.get("title_weight", 3)
    analysis = analyze_favorites(starred, topics, title_weight)

    # ── Top keywords ──────────────────────────────────────────────────────
    print(f"{BOLD}Top keywords in your favorites:{RESET}")
    max_count = analysis["top_keywords"][0][1] if analysis["top_keywords"] else 1
    for kw, count in analysis["top_keywords"][:15]:
        bar_len = max(1, round(count / max_count * 20))
        bar = "█" * bar_len
        print(f"    {kw:<22}  {DIM}{bar:<20}{RESET}  {count}")

    print()

    # ── Weight table ──────────────────────────────────────────────────────
    print(f"{BOLD}Weight suggestions  (sample: {analysis['total_starred']} starred){RESET}")
    print()
    print(f"    {'Topic':<24}  {'Current':>8}  {'Starred%':>8}  {'Suggested':>9}  Δ")
    print(f"    {'-' * 24}  {'-' * 8}  {'-' * 8}  {'-' * 9}  {'-' * 6}")

    has_changes = False
    for topic_name, s in sorted(
        analysis["suggestions"].items(),
        key=lambda x: -x[1]["starred_rate"],
    ):
        current = s["current"]
        suggested = s["suggested"]
        rate = s["starred_rate"]
        delta = suggested - current

        if delta > 0.05:
            delta_str = f"{GREEN}+{delta:.2f}{RESET}"
            has_changes = True
        else:
            delta_str = f"{DIM}{delta:+.2f}{RESET}"

        flag = f"  {YELLOW}← boost{RESET}" if delta > 0.1 else ""
        print(
            f"    {topic_name:<24}  {current:>8.2f}  {rate:>7.1f}%  {suggested:>9.2f}  {delta_str}{flag}"
        )

    print()

    if not has_changes:
        print(ok("Weights look well-calibrated — no significant adjustments suggested"))
        return 0

    if args.apply:
        try:
            _apply_weights(cfg, analysis["suggestions"])
            print(ok(f"Weights written to {CONFIG_PATH}"))
            print(info("Run  python cli.py rescore  to apply new weights to existing DB articles"))
        except Exception as e:
            print(err(f"Failed to write config: {e}"))
            return 1
    else:
        print(info("Pass --apply to write these suggestions to config.yaml"))

    print()
    return 0


def _apply_weights(cfg: dict, suggestions: dict) -> None:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.yaml not found")
    with CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    for topic_name, s in suggestions.items():
        if topic_name in raw.get("topics", {}):
            raw["topics"][topic_name]["weight"] = round(s["suggested"], 2)
    with CONFIG_PATH.open("w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── Argparse ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cli",
        description=f"{BOLD}FreshRSS Summary — CLI{RESET}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""\
{BOLD}commands:{RESET}
  check              Test FreshRSS connection and DB status
  stats              Show DB statistics (articles, topics, bookmarks)
  fetch              Fetch unread articles, score, save to DB
  rescore            Rescore DB articles with current config weights
  import [FILE]      Import from JSON file  |  --starred : from FreshRSS starred
  tune               Analyze starred items, suggest weight adjustments  (--apply to save)

{BOLD}examples:{RESET}
  python cli.py check
  python cli.py fetch --dry-run
  python cli.py import --starred --limit 300
  python cli.py tune --apply
  python cli.py import articles.json
""",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Test FreshRSS + DB connectivity")
    sub.add_parser("stats", help="Show DB statistics")

    p = sub.add_parser("fetch", help="Fetch + score + save to DB")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")

    p = sub.add_parser("rescore", help="Rescore DB articles with current weights")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")

    p = sub.add_parser("import", help="Import articles from JSON or FreshRSS starred")
    p.add_argument("file", nargs="?", help="JSON file to import")
    p.add_argument("--starred", action="store_true", help="Import from FreshRSS starred stream")
    p.add_argument("--limit", type=int, help="Max starred items to fetch (default: 500)")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")

    p = sub.add_parser("tune", help="Analyze starred → suggest weight adjustments")
    p.add_argument("--apply", action="store_true", help="Write suggestions to config.yaml")
    p.add_argument("--limit", type=int, help="Max starred items to analyze (default: 200)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"\n{err(str(e))}\n")
        return 1

    dispatch = {
        "check": cmd_check,
        "stats": cmd_stats,
        "fetch": cmd_fetch,
        "rescore": cmd_rescore,
        "import": cmd_import,
        "tune": cmd_tune,
    }
    return dispatch[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
