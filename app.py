#!/usr/bin/env python3
"""
Flask web app for the book recommendation scraper.

Routes:
  GET /           Home page — search form + trending link
  GET /trending   Trending 30 books of the month
  GET /book       Book deep-dive (?title=...&author=...)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from flask import Flask, redirect, render_template, request, url_for

from aggregator import BookDataAggregator
from renderer import ReportRenderer
from scrapers import (
    GoodreadsScraper,
    GoogleBooksScraper,
    GutenbergScraper,
    HackerNewsScraper,
    NYTScraper,
    OpenLibraryScraper,
    RedditScraper,
)
from scrapers.base import ScraperResult
import config

logger = logging.getLogger(__name__)
app = Flask(__name__)
app.secret_key = config.__dict__.get("FLASK_SECRET_KEY", "dev-secret")


# ---------------------------------------------------------------------------
# Shared scraper helpers
# ---------------------------------------------------------------------------

def _build_scrapers() -> list:
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
    return scrapers


async def _safe_scrape_trending(scraper) -> ScraperResult:
    try:
        async with scraper:
            return await scraper.scrape_trending()
    except Exception as exc:
        logger.warning("Scraper %s failed: %s", scraper.name, exc)
        return ScraperResult(scraper_name=scraper.name, success=False, error_message=str(exc))


async def _safe_scrape_book(scraper, title: str, author: Optional[str]) -> ScraperResult:
    try:
        async with scraper:
            return await scraper.scrape_book(title, author)
    except Exception as exc:
        logger.warning("Scraper %s failed: %s", scraper.name, exc)
        return ScraperResult(scraper_name=scraper.name, success=False, error_message=str(exc))


async def _run_trending():
    scrapers = _build_scrapers()
    results = await asyncio.gather(*[_safe_scrape_trending(s) for s in scrapers])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return BookDataAggregator().aggregate_trending(list(results), generated_at)


async def _run_book(title: str, author: Optional[str]):
    scrapers = _build_scrapers()
    results = await asyncio.gather(*[_safe_scrape_book(s, title, author) for s in scrapers])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return BookDataAggregator().aggregate_book(list(results), title, author, generated_at)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/trending")
def trending():
    report = asyncio.run(_run_trending())
    html = ReportRenderer().render_to_string(report, web_mode=True)
    return html


@app.route("/book")
def book():
    title = request.args.get("title", "").strip()
    author = request.args.get("author", "").strip() or None
    if not title:
        return redirect(url_for("index"))
    report = asyncio.run(_run_book(title, author))
    html = ReportRenderer().render_to_string(report, web_mode=True)
    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
