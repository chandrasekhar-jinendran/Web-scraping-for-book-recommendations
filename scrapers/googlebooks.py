from __future__ import annotations

import logging
from typing import Optional

from .base import (
    BaseScraper, BookMetadata, RatingData, ScraperResult,
    SimilarBook, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)
BASE = "https://www.googleapis.com/books/v1"


class GoogleBooksScraper(BaseScraper):
    name = "googlebooks"
    rate_limit_rps = 1.0

    # ------------------------------------------------------------------
    # Trending mode
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        import config
        queries = [
            ("bestseller 2025", "bestseller"),
            ("new release fiction 2025", "new_fiction"),
            ("must read nonfiction 2025", "new_nonfiction"),
        ]

        entries: list[TrendingEntry] = []
        raw: dict = {}

        for query, qtype in queries:
            try:
                params: dict = {
                    "q": query,
                    "orderBy": "relevance",
                    "maxResults": 15,
                    "printType": "books",
                    "langRestrict": "en",
                }
                if config.GOOGLE_BOOKS_API_KEY:
                    params["key"] = config.GOOGLE_BOOKS_API_KEY

                resp = await self._get(f"{BASE}/volumes", params=params)
                items = resp.json().get("items", [])
                raw[qtype] = len(items)

                for i, item in enumerate(items):
                    vi = item.get("volumeInfo", {})
                    metadata = self._parse_volume(vi, item.get("id"))
                    signal = TrendSignal(
                        source=self.name,
                        score=max(0.0, 75 - i * 4),
                        rank=i + 1,
                        signal_type=qtype,
                        url=vi.get("canonicalVolumeLink"),
                    )
                    ratings = self._extract_ratings(vi)
                    entries.append(TrendingEntry(metadata=metadata, trend_signal=signal, ratings=ratings))

            except Exception as exc:
                raw[f"{qtype}_error"] = str(exc)
                logger.warning("googlebooks trending query '%s' failed: %s", qtype, exc)

        return ScraperResult(
            scraper_name=self.name,
            success=True,
            trending_books=entries,
            raw_data=raw,
        )

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        import config
        q = f"intitle:{title}"
        if author:
            q += f"+inauthor:{author}"

        params: dict = {"q": q, "maxResults": 5, "printType": "books"}
        if config.GOOGLE_BOOKS_API_KEY:
            params["key"] = config.GOOGLE_BOOKS_API_KEY

        try:
            resp = await self._get(f"{BASE}/volumes", params=params)
            items = resp.json().get("items", [])

            if not items:
                return ScraperResult(scraper_name=self.name, success=True, raw_data={})

            best = items[0]
            vi = best.get("volumeInfo", {})
            metadata = self._parse_volume(vi, best.get("id"))
            ratings = self._extract_ratings(vi)

            similar = [
                SimilarBook(
                    title=item.get("volumeInfo", {}).get("title", ""),
                    authors=item.get("volumeInfo", {}).get("authors", []),
                    source=self.name,
                    reason="also matched search",
                )
                for item in items[1:]
            ]

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                metadata=metadata,
                ratings=ratings,
                similar_books=similar,
                raw_data={"volumeInfo": vi},
            )
        except Exception as exc:
            logger.error("googlebooks book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_volume(self, vi: dict, vol_id: Optional[str]) -> BookMetadata:
        cover: Optional[str] = None
        links = vi.get("imageLinks", {})
        if links:
            cover = links.get("thumbnail") or links.get("smallThumbnail")
            if cover:
                cover = cover.replace("http://", "https://")

        isbns = vi.get("industryIdentifiers", [])
        isbn_13 = next((x["identifier"] for x in isbns if x.get("type") == "ISBN_13"), None)
        isbn_10 = next((x["identifier"] for x in isbns if x.get("type") == "ISBN_10"), None)

        year: Optional[int] = None
        pub_date = vi.get("publishedDate", "")
        if pub_date and pub_date[:4].isdigit():
            year = int(pub_date[:4])

        return BookMetadata(
            title=vi.get("title", "Unknown"),
            authors=vi.get("authors", []),
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            published_year=year,
            publisher=vi.get("publisher"),
            description=vi.get("description"),
            cover_url=cover,
            page_count=vi.get("pageCount"),
            genres=vi.get("categories", []),
            language=vi.get("language"),
            source=self.name,
            source_url=vi.get("canonicalVolumeLink") or (
                f"https://books.google.com/books?id={vol_id}" if vol_id else None
            ),
        )

    def _extract_ratings(self, vi: dict) -> list[RatingData]:
        avg = vi.get("averageRating")
        count = vi.get("ratingsCount")
        if avg:
            return [RatingData(
                source=self.name,
                rating=round(float(avg), 2),
                raw_rating=float(avg),
                raw_scale=5.0,
                rating_count=int(count) if count else None,
            )]
        return []
