from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .base import (
    BaseScraper, BookMetadata, RatingData, ScraperResult,
    SimilarBook, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)
BASE = "https://openlibrary.org"


class OpenLibraryScraper(BaseScraper):
    name = "openlibrary"
    rate_limit_rps = 1.0

    # ------------------------------------------------------------------
    # Trending mode
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        try:
            resp = await self._get(f"{BASE}/trending/monthly.json", params={"limit": 40})
            data = resp.json()
            works = data.get("works", [])

            entries: list[TrendingEntry] = []
            rating_tasks = []

            for i, work in enumerate(works[:40]):
                metadata = self._parse_search_doc(work)
                signal = TrendSignal(
                    source=self.name,
                    score=max(0.0, 100 - i * 2.5),
                    rank=i + 1,
                    signal_type="monthly_trending",
                    url=f"{BASE}{work.get('key', '')}",
                )
                entries.append(TrendingEntry(metadata=metadata, trend_signal=signal))
                rating_tasks.append(self._fetch_ratings(work.get("key", "")))

            rating_results = await asyncio.gather(*rating_tasks, return_exceptions=True)
            for entry, result in zip(entries, rating_results):
                if isinstance(result, list):
                    entry.ratings = result

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                trending_books=entries,
                raw_data={"works_count": len(works)},
            )
        except Exception as exc:
            logger.error("openlibrary trending failed: %s", exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        try:
            params: dict = {"title": title, "limit": 5}
            if author:
                params["author"] = author

            resp = await self._get(f"{BASE}/search.json", params=params)
            data = resp.json()
            docs = data.get("docs", [])

            if not docs:
                return ScraperResult(
                    scraper_name=self.name, success=True,
                    raw_data={"numFound": data.get("numFound", 0)},
                )

            best = docs[0]
            metadata = self._parse_search_doc(best)
            work_key = best.get("key", "")

            ratings, similar = await asyncio.gather(
                self._fetch_ratings(work_key),
                self._fetch_similar(best.get("subject", []), title),
                return_exceptions=False,
            )

            for doc in docs[1:5]:
                similar.append(SimilarBook(
                    title=doc.get("title", ""),
                    authors=doc.get("author_name", []),
                    source=self.name,
                    reason="also matched search",
                ))

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                metadata=metadata,
                ratings=ratings,
                similar_books=similar,
                raw_data={"doc": best, "numFound": data.get("numFound", 0)},
            )
        except Exception as exc:
            logger.error("openlibrary book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_search_doc(self, doc: dict) -> BookMetadata:
        cover_url: Optional[str] = None
        if doc.get("cover_i"):
            cover_url = f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-M.jpg"

        isbns = doc.get("isbn", [])
        isbn_10 = next((x for x in isbns if len(x) == 10), None)
        isbn_13 = next((x for x in isbns if len(x) == 13), None)

        return BookMetadata(
            title=doc.get("title", "Unknown"),
            authors=doc.get("author_name", []),
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            published_year=doc.get("first_publish_year"),
            publisher=(doc.get("publisher") or [None])[0],
            cover_url=cover_url,
            page_count=doc.get("number_of_pages_median"),
            genres=(doc.get("subject") or [])[:10],
            language=(doc.get("language") or [None])[0],
            source=self.name,
            source_url=f"{BASE}{doc.get('key', '')}",
        )

    async def _fetch_ratings(self, work_key: str) -> list[RatingData]:
        if not work_key:
            return []
        try:
            resp = await self._get(f"{BASE}{work_key}/ratings.json")
            summary = resp.json().get("summary", {})
            avg = summary.get("average")
            count = summary.get("count", 0)
            if avg and float(avg) > 0:
                return [RatingData(
                    source=self.name,
                    rating=round(float(avg), 2),
                    raw_rating=float(avg),
                    raw_scale=5.0,
                    rating_count=int(count),
                )]
        except Exception:
            pass
        return []

    async def _fetch_similar(self, subjects: list, exclude_title: str) -> list[SimilarBook]:
        if not subjects:
            return []
        try:
            subject = subjects[0]
            resp = await self._get(
                f"{BASE}/search.json",
                params={"subject": subject, "limit": 6, "sort": "rating"},
            )
            similar: list[SimilarBook] = []
            for doc in resp.json().get("docs", []):
                if doc.get("title", "").lower() == exclude_title.lower():
                    continue
                similar.append(SimilarBook(
                    title=doc.get("title", ""),
                    authors=doc.get("author_name", []),
                    source=self.name,
                    reason=f"same subject: {subject}",
                ))
                if len(similar) >= 5:
                    break
            return similar
        except Exception:
            return []
