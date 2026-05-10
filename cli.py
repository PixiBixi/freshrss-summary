#!/usr/bin/env python3
"""FreshRSS Summary — CLI."""

import argparse
import asyncio
import datetime
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from freshrss_client import FreshRSSClient

import yaml

from config import CONFIG_PATH, load_config

logger = logging.getLogger(__name__)

# ── ANSI ───────────────────────────────────────────────────────────────────


def _ansi(code: str) -> str:
    return f"\033[{code}m" if sys.stdout.isatty() else ""


RESET = _ansi("0")
BOLD = _ansi("1")
DIM = _ansi("2")
GREEN = _ansi("32")
YELLOW = _ansi("33")
CYAN = _ansi("36")
RED = _ansi("31")


def ok(msg: str) -> str:
    return f"{GREEN}✓{RESET}  {msg}"


def warn(msg: str) -> str:
    return f"{YELLOW}⚠{RESET}  {msg}"


def err(msg: str) -> str:
    return f"{RED}✗{RESET}  {msg}"


def info(msg: str) -> str:
    return f"{CYAN}·{RESET}  {msg}"


# ── Config ─────────────────────────────────────────────────────────────────


def make_client(cfg: dict[str, Any]) -> "FreshRSSClient":
    from freshrss_client import FreshRSSClient

    fr = cfg["freshrss"]
    return FreshRSSClient(fr["url"], fr["username"], fr["api_password"])


# ── DB helpers (async) ─────────────────────────────────────────────────────


async def _init_db(cfg: dict[str, Any]) -> None:
    from db import DEFAULT_DB_URL, init_db

    db_url = cfg.get("database", {}).get("url", DEFAULT_DB_URL)
    await init_db(db_url)


async def _db_stats(cfg: dict[str, Any]) -> dict[str, Any]:
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


async def _run_fetch(
    cfg: dict[str, Any], save: bool
) -> tuple[list[dict[str, Any]], int, list[tuple[int, int]]]:
    """Init DB, fetch topics (DB-first), fetch+score, optionally save. Returns (articles, total_fetched, batch_info)."""
    from config import DEFAULT_TOPICS
    from db import get_or_seed_scoring_config, save_articles
    from pipeline import fetch_and_score_iter
    from scorer import build_topics

    await _init_db(cfg)
    topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
    topics = build_topics(topics_cfg)

    all_articles: list[dict[str, Any]] = []
    batch_info: list[tuple[int, int]] = []
    total_fetched, prev_fetched = 0, 0

    for scored_batch, total_fetched in fetch_and_score_iter(cfg, topics):
        batch_count = total_fetched - prev_fetched
        prev_fetched = total_fetched
        batch_info.append((batch_count, len(scored_batch)))
        all_articles.extend(scored_batch)

    if save and all_articles:
        await save_articles(all_articles, total_fetched)

    return all_articles, total_fetched, batch_info


async def _run_rescore(
    cfg: dict[str, Any], save: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Init DB, fetch topics (DB-first), rescore DB articles, optionally save. Returns (raw, rescored)."""
    from config import DEFAULT_TOPICS
    from db import get_or_seed_scoring_config, load_for_rescore, save_articles
    from pipeline import rescore_articles
    from scorer import build_topics

    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))

    await _init_db(cfg)
    raw = await load_for_rescore()
    if not raw:
        return [], []
    topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
    topics = build_topics(topics_cfg)
    rescored = rescore_articles(raw, topics, title_weight, min_score)
    if save:
        await save_articles(rescored, len(raw))
    return raw, rescored


async def _run_import(
    cfg: dict[str, Any], articles: list[dict[str, Any]], bookmark_ids: list[str] | None = None
) -> None:
    """Init DB, upsert articles, optionally bookmark them (single DB session)."""
    from db import bookmark_articles, upsert_articles

    await _init_db(cfg)
    await upsert_articles(articles)
    if bookmark_ids:
        await bookmark_articles(bookmark_ids)


async def _get_active_topics(cfg: dict[str, Any]) -> dict[str, Any]:
    """Init DB and return active topics (DB-first, YAML fallback)."""
    from config import DEFAULT_TOPICS
    from db import get_or_seed_scoring_config

    await _init_db(cfg)
    return await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_check(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Test FreshRSS connection and DB reachability."""
    fr = cfg["freshrss"]
    print(f"\n{BOLD}FreshRSS connection check{RESET}\n")
    print(info(f"URL      : {fr['url']}"))
    print(info(f"Username : {fr['username']}"))
    print()

    try:
        with make_client(cfg) as client:
            count = client.sample_one()
            print(ok(f"Auth OK — reading-list API reachable ({count} article sampled)"))

            starred = client.fetch_starred(max_items=10)
            print(ok(f"Starred stream reachable ({len(starred)} fetched, limited to 10)"))
    except Exception as e:
        logger.exception("check: FreshRSS connection failed")
        print(err(f"FreshRSS error: {e}"))
        return 1

    print()
    try:
        s = asyncio.run(_db_stats(cfg))
        db_url = cfg.get("database", {}).get("url", "sqlite (default)")
        print(info(f"DB URL   : {db_url}"))
        print(ok(f"DB reachable — {s['articles']} articles, {s['bookmarks']} bookmarks"))
    except Exception as e:
        logger.exception("check: DB stats failed")
        print(warn(f"DB check failed: {e}"))

    print()
    return 0


def cmd_stats(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Show DB statistics."""
    print(f"\n{BOLD}DB statistics{RESET}\n")
    try:
        s = asyncio.run(_db_stats(cfg))
    except Exception as e:
        logger.exception("stats: DB query failed")
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


def cmd_fetch(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Fetch unread articles from FreshRSS, score and save to DB."""
    print(f"\n{BOLD}Fetching unread articles{RESET}\n")

    min_score = float(cfg.get("scoring", {}).get("min_score", 1.0))

    try:
        all_articles, total_fetched, batch_info = asyncio.run(
            _run_fetch(cfg, save=not args.dry_run)
        )
    except Exception as e:
        logger.exception("fetch: failed")
        print(err(f"Fetch error: {e}"))
        return 1

    for batch_count, relevant in batch_info:
        print(info(f"Batch: {batch_count} fetched, {relevant} relevant"))

    if total_fetched == 0:
        print(warn("No unread articles"))
        return 0

    print()
    print(ok(f"{total_fetched} fetched total — {len(all_articles)} relevant (score ≥ {min_score})"))

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
        if all_articles:
            print(f"\n{BOLD}Top 5:{RESET}")
            for a in all_articles[:5]:
                print(f"    [{a['score']:.0f}]  {a['title'][:72]}")
    else:
        print(ok("Saved to DB"))

    print()
    return 0


def cmd_rescore(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Rescore DB articles with the current config weights."""
    print(f"\n{BOLD}Rescoring from DB{RESET}\n")

    min_score = float(cfg.get("scoring", {}).get("min_score", 1.0))

    try:
        raw, rescored = asyncio.run(_run_rescore(cfg, save=not args.dry_run))
    except Exception as e:
        logger.exception("rescore: failed")
        print(err(f"Rescore failed: {e}"))
        return 1

    if not raw:
        print(warn("No articles in DB — run fetch first"))
        return 0

    print(info(f"Rescoring {len(raw)} articles..."))
    print(ok(f"{len(rescored)} articles above min_score={min_score}"))

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
    else:
        print(ok("Saved to DB"))

    print()
    return 0


def cmd_import(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Import articles from a JSON file or from FreshRSS starred."""
    if args.starred:
        return _import_starred(args, cfg)
    if not args.file:
        print(err("Provide a JSON file path or use --starred"))
        return 1
    return _import_file(args, cfg)


async def _score_and_import_starred(cfg: dict[str, Any], starred: list, title_weight: int) -> list:
    """Score starred articles against active topics and upsert+bookmark them in DB. Returns scored list."""
    from scorer import build_topics, score_articles

    topics = build_topics(await _get_active_topics(cfg))
    scored = score_articles(starred, topics, title_weight, min_score=0)
    await _run_import(
        cfg,
        [a.to_dict() for a in scored],
        bookmark_ids=[a.article.id for a in scored],
    )
    return scored


def _import_starred(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Fetch starred items from FreshRSS, score and import into DB + bookmarks."""
    print(f"\n{BOLD}Importing FreshRSS starred articles{RESET}\n")

    title_weight = cfg.get("scoring", {}).get("title_weight", 3)
    max_items = args.limit or 500

    try:
        with make_client(cfg) as client:
            print(info(f"Fetching up to {max_items} starred articles..."))
            starred = client.fetch_starred(max_items=max_items)
    except Exception as e:
        logger.exception("import-starred: FreshRSS fetch failed")
        print(err(f"Fetch error: {e}"))
        return 1

    if not starred:
        print(warn("No starred articles found"))
        return 0

    print(ok(f"Fetched {len(starred)} starred articles"))

    if args.dry_run:
        from scorer import build_topics, score_articles

        topics = build_topics(asyncio.run(_get_active_topics(cfg)))
        scored = score_articles(starred, topics, title_weight, min_score=0)
        print(warn("--dry-run: not saving to DB"))
        for a in scored[:5]:
            print(f"    [{a.score:.0f}]  {a.article.title[:72]}")
    else:
        try:
            scored = asyncio.run(_score_and_import_starred(cfg, starred, title_weight))
            print(ok(f"Imported {len(scored)} articles — all bookmarked"))
        except Exception as e:
            logger.exception("import-starred: DB upsert/bookmark failed")
            print(err(f"DB error: {e}"))
            return 1

    print()
    return 0


def _import_file(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Import articles from a JSON file (list of article objects)."""
    path = Path(args.file)
    print(f"\n{BOLD}Importing from {path.name}{RESET}\n")

    if not path.exists():
        print(err(f"File not found: {path}"))
        return 1

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        logger.exception("import-file: JSON parse failed")
        print(err(f"JSON parse error: {e}"))
        return 1

    if not isinstance(data, list):
        print(err("JSON must be a list of article objects"))
        return 1

    from models import Article
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
    topics = build_topics(asyncio.run(_get_active_topics(cfg)))
    scored = score_articles(articles, topics, title_weight, min_score=0)

    if args.dry_run:
        print(warn("--dry-run: not saving to DB"))
        for a in scored[:5]:
            print(f"    [{a.score:.0f}]  {a.article.title[:72]}")
    else:
        try:
            asyncio.run(_run_import(cfg, [a.to_dict() for a in scored]))
            print(ok(f"Imported {len(scored)} articles"))
        except Exception as e:
            logger.exception("import-file: DB upsert failed")
            print(err(f"DB error: {e}"))
            return 1

    print()
    return 0


def cmd_tune(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """
    Analyze FreshRSS starred articles and suggest weight adjustments.

    The idea: articles you star in FreshRSS are implicit positive signals.
    If topic X appears in 60% of your favorites, its weight probably deserves a boost.
    Formula: suggested = current * (1 + 0.5 * hit_rate)
    """
    print(f"\n{BOLD}Scoring tune — analyzing your starred articles{RESET}\n")

    from scorer import analyze_favorites, build_topics

    topics = build_topics(asyncio.run(_get_active_topics(cfg)))
    max_items = args.limit or 200

    if not topics:
        print(err("No topics configured in config.yaml"))
        return 1

    try:
        with make_client(cfg) as client:
            print(info(f"Fetching up to {max_items} starred articles..."))
            starred = client.fetch_starred(max_items=max_items)
    except Exception as e:
        logger.exception("tune: FreshRSS fetch failed")
        print(err(f"Fetch error: {e}"))
        return 1

    if not starred:
        print(warn("No starred articles found — star some articles in FreshRSS first!"))
        return 0

    print(ok(f"Fetched {len(starred)} starred articles"))
    print()

    scoring_cfg = cfg.get("scoring", {})
    title_weight = scoring_cfg.get("title_weight", 3)
    feed_weights = cfg.get("feed_weights", {})
    analysis = analyze_favorites(starred, topics, title_weight, feed_weights=feed_weights or None)

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
            logger.exception("tune: failed to write config")
            print(err(f"Failed to write config: {e}"))
            return 1
    else:
        print(info("Pass --apply to write these suggestions to config.yaml"))

    print()
    return 0


async def _load_articles_for_digest(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from db import load_articles

    await _init_db(cfg)
    articles, _, _ = await load_articles()
    return articles


def cmd_digest(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Build and print the Telegram digest from DB articles. Optionally send it."""
    from telegram_digest import TelegramConfig, build_digest, send_message

    try:
        articles = asyncio.run(_load_articles_for_digest(cfg))
    except Exception as e:
        logger.exception("digest: DB load failed")
        print(err(f"DB error: {e}"))
        return 1

    text = build_digest(articles)
    print(text)

    if args.send:
        tg_cfg = TelegramConfig.from_dict(cfg.get("telegram", {}))
        if not tg_cfg.is_configured():
            print(err("Telegram bot_token or chat_id not configured"))
            return 1
        try:
            asyncio.run(send_message(tg_cfg, text))
            print(ok("Digest sent via Telegram"))
        except Exception as e:
            logger.exception("digest: Telegram send failed")
            print(err(f"Send failed: {e}"))
            return 1

    print()
    return 0


def _apply_weights(cfg: dict[str, Any], suggestions: dict[str, Any]) -> None:
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
  digest             Build and print the digest  |  --send : push via Telegram

{BOLD}examples:{RESET}
  python cli.py check
  python cli.py fetch --dry-run
  python cli.py import --starred --limit 300
  python cli.py tune --apply
  python cli.py import articles.json
  python cli.py digest
  python cli.py digest --send
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

    p = sub.add_parser("digest", help="Build and print the Telegram digest (--send to push)")
    p.add_argument("--send", action="store_true", help="Send the digest via Telegram")

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
        "digest": cmd_digest,
    }
    return dispatch[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
