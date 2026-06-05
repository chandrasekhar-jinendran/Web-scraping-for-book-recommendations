from __future__ import annotations

import logging
from typing import Optional

from .base import (
    BaseScraper, BookMetadata, ScraperResult,
    SimilarBook, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)
BASE = "https://gutendex.com"


class GutenbergScraper(BaseScraper):
    name = "gutenberg"
    rate_limit_rps = 1.0

    # ------------------------------------------------------------------
    # Trending mode — most-downloaded public-domain books
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        try:
            resp = await self._get(
                f"{BASE}/books/",
                params={"sort": "popular", "languages": "en"},
            )
            data = resp.json()
            results = data.get("results", [])

            entries: list[TrendingEntry] = []
            for i, book in enumerate(results[:32]):
                metadata = self._parse_book(book)
                signal = TrendSignal(
                    source=self.name,
                    score=max(0.0, 65 - i * 2.0),
                    rank=i + 1,
                    signal_type="popular_downloads",
                    url=f"https://www.gutenberg.org/ebooks/{book.get('id')}",
                )
                entries.append(TrendingEntry(metadata=metadata, trend_signal=signal))

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                trending_books=entries,
                raw_data={"total_count": data.get("count"), "returned": len(results)},
            )
        except Exception as exc:
            logger.error("gutenberg trending failed: %s", exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        try:
            search = f"{title} {author}" if author else title
            resp = await self._get(f"{BASE}/books/", params={"search": search})
            data = resp.json()
            results = data.get("results", [])

            if not results:
                return ScraperResult(
                    scraper_name=self.name, success=True,
                    raw_data={"message": "Not found in Gutenberg catalog"},
                )

            metadata = self._parse_book(results[0])
            similar = [
                SimilarBook(
                    title=b.get("title", ""),
                    authors=[a["name"] for a in b.get("authors", [])],
                    source=self.name,
                    reason="also in public-domain catalog",
                )
                for b in results[1:5]
            ]

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                metadata=metadata,
                similar_books=similar,
                raw_data={"book": results[0]},
            )
        except Exception as exc:
            logger.error("gutenberg book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_book(self, book: dict) -> BookMetadata:
        authors = [a.get("name", "") for a in book.get("authors", [])]
        formats = book.get("formats", {})
        cover = formats.get("image/jpeg")
        subjects = (book.get("subjects") or [])[:10]
        bookshelves = (book.get("bookshelves") or [])[:5]
        genres = list(dict.fromkeys(subjects + bookshelves))[:10]

        return BookMetadata(
            title=book.get("title", "Unknown"),
            authors=authors,
            genres=genres,
            language=(book.get("languages") or [None])[0],
            cover_url=cover,
            source=self.name,
            source_url=f"https://www.gutenberg.org/ebooks/{book.get('id')}",
        )
