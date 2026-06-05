#!/usr/bin/env python3
"""
Book Recommendation Scraper
============================
Modes:
  python main.py                             → Trending 30 books of the month
  python main.py "Dune"                      → Deep-dive on a specific book
  python main.py "Clean Code" --author "Robert Martin"
  python main.py --output my_report.html
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime
from typing import Optional

from aggregator import BookDataAggregator
from renderer import ReportRenderer
from scrapers.base import ScraperResult
from scrapers import (
    OpenLibraryScraper,
    GoogleBooksScraper,
    GutenbergScraper,
    HackerNewsScraper,
    RedditScraper,
    NYTScraper,
    GoodreadsScraper,
)

logger = logging.getLogger(__name__)


def _sanitize_filename(text: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "_", safe)[:50]


def _build_scrapers() -> list:
    import config
    scrapers = [
        OpenLibraryScraper(),
        GoogleBooksScraper(),
        GutenbergScraper(),
        HackerNewsScraper(),
        RedditScraper(),
        GoodreadsScraper(),
    ]
    if config.SOURCES["nyt"]["enabled"]:
        scrapers.append(NYTScraper())
    else:
        logger.info("NYT scraper disabled — set NYT_API_KEY in .env to enable")
    return scrapers


async def _safe_scrape_trending(scraper) -> ScraperResult:
    try:
        async with scraper:
            return await scraper.scrape_trending()
    except Exception as exc:
        logger.warning("Scraper %s crashed: %s", scraper.name, exc)
        return ScraperResult(
            scraper_name=scraper.name,
            success=False,
            error_message=str(exc),
        )


async def _safe_scrape_book(scraper, title: str, author: Optional[str]) -> ScraperResult:
    try:
        async with scraper:
            return await scraper.scrape_book(title, author)
    except Exception as exc:
        logger.warning("Scraper %s crashed: %s", scraper.name, exc)
        return ScraperResult(
            scraper_name=scraper.name,
            success=False,
            error_message=str(exc),
        )


async def run_trending(output: str) -> None:
    print("🔍  Fetching trending books from all sources in parallel…")
    scrapers = _build_scrapers()

    tasks = [_safe_scrape_trending(s) for s in scrapers]
    results = await asyncio.gather(*tasks)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = BookDataAggregator().aggregate_trending(list(results), generated_at)

    print(f"📊  Aggregated {len(report.trending_books)} unique trending books")
    if report.warnings:
        for w in report.warnings:
            print(f"   ⚠  {w}")

    ReportRenderer().render(report, output)
    print(f"✅  Report saved → {output}")


async def run_book_deepdive(title: str, author: Optional[str], output: str) -> None:
    by_str = f"  by {author}" if author else ""
    print(f'🔍  Searching for "{title}"{by_str}…')
    scrapers = _build_scrapers()

    tasks = [_safe_scrape_book(s, title, author) for s in scrapers]
    results = await asyncio.gather(*tasks)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = BookDataAggregator().aggregate_book(list(results), title, author, generated_at)

    print(f"📊  Found metadata from {sum(1 for r in results if r.success and r.metadata)} source(s)")
    if report.warnings:
        for w in report.warnings:
            print(f"   ⚠  {w}")

    ReportRenderer().render(report, output)
    print(f"✅  Report saved → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Book recommendation scraper — trending 30 or single-book deep-dive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "title",
        nargs="?",
        default=None,
        help="Book title to search (omit for trending-30 mode)",
    )
    parser.add_argument("--author", "-a", default=None, help="Author name (optional)")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output HTML file path (auto-generated if omitted)",
    )
    args = parser.parse_args()

    if args.title:
        default_out = f"book_report_{_sanitize_filename(args.title)}.html"
        output = args.output or default_out
        asyncio.run(run_book_deepdive(args.title, args.author, output))
    else:
        ts = datetime.now().strftime("%Y_%m")
        default_out = f"trending_{ts}.html"
        output = args.output or default_out
        asyncio.run(run_trending(output))


if __name__ == "__main__":
    main()
