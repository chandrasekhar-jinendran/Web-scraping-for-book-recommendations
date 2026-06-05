from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BookMetadata:
    title: str
    authors: list[str] = field(default_factory=list)
    isbn_10: Optional[str] = None
    isbn_13: Optional[str] = None
    published_year: Optional[int] = None
    publisher: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    page_count: Optional[int] = None
    genres: list[str] = field(default_factory=list)
    language: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None


@dataclass
class RatingData:
    source: str
    rating: float          # normalized 0-5
    raw_rating: float
    raw_scale: float
    rating_count: Optional[int] = None
    review_count: Optional[int] = None


@dataclass
class Review:
    source: str
    text: str
    author_name: Optional[str] = None
    rating: Optional[float] = None   # normalized 0-5
    url: Optional[str] = None
    date: Optional[str] = None


@dataclass
class Discussion:
    source: str
    title: str
    url: str
    score: Optional[int] = None
    comment_count: Optional[int] = None
    subreddit: Optional[str] = None
    top_comments: list[str] = field(default_factory=list)


@dataclass
class SimilarBook:
    title: str
    authors: list[str] = field(default_factory=list)
    source: str = ""
    reason: Optional[str] = None


@dataclass
class BestsellerStatus:
    source: str
    list_name: str
    rank: Optional[int] = None
    weeks_on_list: Optional[int] = None
    date: Optional[str] = None


@dataclass
class TrendSignal:
    source: str
    score: float           # 0-100
    rank: Optional[int] = None
    signal_type: str = ""
    url: Optional[str] = None


@dataclass
class TrendingEntry:
    metadata: BookMetadata
    trend_signal: TrendSignal
    ratings: list[RatingData] = field(default_factory=list)
    bestseller_statuses: list[BestsellerStatus] = field(default_factory=list)


@dataclass
class RatingsSummary:
    normalized_average: Optional[float]
    sources: list[RatingData]
    total_rating_count: int


@dataclass
class TrendingBook:
    metadata: BookMetadata
    trend_score: float
    sources_found_in: list[str] = field(default_factory=list)
    trend_signals: list[TrendSignal] = field(default_factory=list)
    ratings: list[RatingData] = field(default_factory=list)
    ratings_summary: Optional[RatingsSummary] = None
    bestseller_statuses: list[BestsellerStatus] = field(default_factory=list)


@dataclass
class ScraperResult:
    scraper_name: str
    success: bool
    error_message: Optional[str] = None
    # Book-mode fields
    metadata: Optional[BookMetadata] = None
    ratings: list[RatingData] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    discussions: list[Discussion] = field(default_factory=list)
    similar_books: list[SimilarBook] = field(default_factory=list)
    bestseller_status: list[BestsellerStatus] = field(default_factory=list)
    # Trending-mode field
    trending_books: list[TrendingEntry] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


@dataclass
class AggregatedReport:
    mode: str              # "trending" or "book"
    generated_at: str
    query_title: Optional[str] = None
    query_author: Optional[str] = None
    # Trending mode
    trending_books: list[TrendingBook] = field(default_factory=list)
    # Book deep-dive mode
    canonical_metadata: Optional[BookMetadata] = None
    all_metadata: list[BookMetadata] = field(default_factory=list)
    ratings_summary: Optional[RatingsSummary] = None
    reviews: list[Review] = field(default_factory=list)
    discussions: list[Discussion] = field(default_factory=list)
    similar_books: list[SimilarBook] = field(default_factory=list)
    bestseller_statuses: list[BestsellerStatus] = field(default_factory=list)
    # Common
    scraper_results: list[ScraperResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base scraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    name: str = "base"
    rate_limit_rps: float = 1.0

    def __init__(self) -> None:
        from config import HTTP_TIMEOUT, USER_AGENT
        self._client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
            follow_redirects=True,
        )
        self._last_request_time: float = 0.0

    async def _get(
        self,
        url: str,
        params: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ) -> httpx.Response:
        elapsed = time.monotonic() - self._last_request_time
        min_interval = 1.0 / self.rate_limit_rps
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        from config import MAX_RETRIES
        for attempt in range(MAX_RETRIES + 1):
            try:
                self._last_request_time = time.monotonic()
                resp = await self._client.get(url, params=params, headers=extra_headers or {})

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                    if attempt < MAX_RETRIES:
                        logger.warning("%s: 429 – retrying in %ss", self.name, wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                elif resp.status_code >= 500:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(2 ** (attempt + 1))
                        continue
                    resp.raise_for_status()
                else:
                    resp.raise_for_status()
                return resp

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                raise

        raise RuntimeError(f"{self.name}: exhausted retries for {url}")

    @abstractmethod
    async def scrape_trending(self) -> ScraperResult:
        """Return trending books of the month from this source."""

    @abstractmethod
    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        """Deep-scrape a specific book by title (and optional author)."""

    async def __aenter__(self) -> "BaseScraper":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()
