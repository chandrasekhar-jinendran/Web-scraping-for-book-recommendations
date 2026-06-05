from __future__ import annotations

import logging
from typing import Optional

from .base import (
    BaseScraper, BookMetadata, BestsellerStatus, RatingData,
    ScraperResult, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)
BASE = "https://api.nytimes.com/svc/books/v3"

# Lists to pull for trending — covers the major categories
LISTS = [
    "hardcover-fiction",
    "hardcover-nonfiction",
    "trade-fiction-paperback",
    "paperback-nonfiction",
    "young-adult-hardcover",
    "series-books",
]


class NYTScraper(BaseScraper):
    name = "nyt"
    rate_limit_rps = 0.5

    def __init__(self) -> None:
        super().__init__()
        import config
        self._api_key = config.NYT_API_KEY

    def _is_enabled(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Trending mode — current bestseller lists
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        if not self._is_enabled():
            return ScraperResult(
                scraper_name=self.name,
                success=False,
                error_message="NYT_API_KEY not configured — skipping NYT scraper",
            )

        entries: list[TrendingEntry] = []
        raw: dict = {}

        for list_name in LISTS:
            try:
                resp = await self._get(
                    f"{BASE}/lists/current/{list_name}.json",
                    params={"api-key": self._api_key},
                )
                data = resp.json()
                books = data.get("results", {}).get("books", [])
                raw[list_name] = len(books)
                pub_date = data.get("results", {}).get("bestsellers_date", "")

                for book in books:
                    rank = book.get("rank", 0)
                    metadata = BookMetadata(
                        title=book.get("title", ""),
                        authors=[book.get("author", "")] if book.get("author") else [],
                        isbn_13=book.get("primary_isbn13"),
                        isbn_10=book.get("primary_isbn10"),
                        publisher=book.get("publisher"),
                        description=book.get("description"),
                        cover_url=book.get("book_image"),
                        source=self.name,
                        source_url=book.get("amazon_product_url"),
                    )
                    signal = TrendSignal(
                        source=self.name,
                        score=max(0.0, 100 - (rank - 1) * 6.5),
                        rank=rank,
                        signal_type=f"nyt_{list_name}",
                        url=book.get("amazon_product_url"),
                    )
                    bestseller = BestsellerStatus(
                        source=self.name,
                        list_name=list_name.replace("-", " ").title(),
                        rank=rank,
                        weeks_on_list=book.get("weeks_on_list"),
                        date=pub_date,
                    )
                    entries.append(TrendingEntry(
                        metadata=metadata,
                        trend_signal=signal,
                        bestseller_statuses=[bestseller],
                    ))

            except Exception as exc:
                raw[f"{list_name}_error"] = str(exc)
                logger.warning("NYT list '%s' failed: %s", list_name, exc)

        return ScraperResult(
            scraper_name=self.name,
            success=True,
            trending_books=entries,
            raw_data=raw,
        )

    # ------------------------------------------------------------------
    # Book deep-dive mode — bestseller history search
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        if not self._is_enabled():
            return ScraperResult(
                scraper_name=self.name,
                success=False,
                error_message="NYT_API_KEY not configured",
            )

        try:
            params: dict = {"title": title, "api-key": self._api_key}
            if author:
                params["author"] = author

            resp = await self._get(f"{BASE}/lists/best-sellers/history.json", params=params)
            data = resp.json()
            results = data.get("results", [])

            if not results:
                return ScraperResult(scraper_name=self.name, success=True,
                                     raw_data={"message": "Not found in NYT bestseller history"})

            best = results[0]
            metadata = BookMetadata(
                title=best.get("title", ""),
                authors=[best.get("author", "")] if best.get("author") else [],
                isbn_13=best.get("primary_isbn13"),
                isbn_10=best.get("primary_isbn10"),
                publisher=best.get("publisher"),
                description=best.get("description"),
                source=self.name,
            )

            bestseller_statuses: list[BestsellerStatus] = []
            for rank_info in best.get("ranks_history", [])[:5]:
                bestseller_statuses.append(BestsellerStatus(
                    source=self.name,
                    list_name=rank_info.get("list_name", ""),
                    rank=rank_info.get("rank"),
                    weeks_on_list=rank_info.get("weeks_on_list"),
                    date=rank_info.get("bestsellers_date"),
                ))

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                metadata=metadata,
                bestseller_status=bestseller_statuses,
                raw_data={"result": best},
            )
        except Exception as exc:
            logger.error("NYT book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))
