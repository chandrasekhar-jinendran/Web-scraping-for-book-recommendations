from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from .base import (
    BaseScraper, BookMetadata, RatingData, Review, ScraperResult,
    SimilarBook, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)
BASE = "https://www.goodreads.com"

# Best Books of the Month community list
BEST_OF_MONTH_URL = f"{BASE}/list/show/167.Best_Books_of_the_Month"
POPULAR_URL = f"{BASE}/book/popular_by_date"

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class GoodreadsScraper(BaseScraper):
    name = "goodreads"
    rate_limit_rps = 0.3   # 1 request per ~3 seconds — conservative

    # ------------------------------------------------------------------
    # Trending mode — "Best Books of the Month" community list
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        for url in (BEST_OF_MONTH_URL, POPULAR_URL):
            try:
                resp = await self._get(url, extra_headers=_BROWSER_HEADERS)
                soup = BeautifulSoup(resp.text, "lxml")

                if self._is_blocked(resp, soup):
                    logger.warning("Goodreads WAF block on %s", url)
                    continue

                entries = self._parse_list_page(soup)
                if entries:
                    return ScraperResult(
                        scraper_name=self.name,
                        success=True,
                        trending_books=entries,
                        raw_data={"source_url": url, "count": len(entries)},
                    )
            except Exception as exc:
                logger.warning("Goodreads trending URL %s failed: %s", url, exc)

        return ScraperResult(
            scraper_name=self.name,
            success=False,
            error_message="Goodreads blocked all requests or returned no data",
        )

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        try:
            query = f"{title} {author}" if author else title
            resp = await self._get(
                f"{BASE}/search",
                params={"q": query},
                extra_headers=_BROWSER_HEADERS,
            )
            soup = BeautifulSoup(resp.text, "lxml")

            if self._is_blocked(resp, soup):
                return ScraperResult(
                    scraper_name=self.name,
                    success=False,
                    error_message="Goodreads blocked the request",
                )

            book_url = self._extract_first_result_url(soup)
            if not book_url:
                return ScraperResult(scraper_name=self.name, success=True,
                                     raw_data={"message": "No results found"})

            # Fetch the book detail page
            book_resp = await self._get(book_url, extra_headers=_BROWSER_HEADERS)
            book_soup = BeautifulSoup(book_resp.text, "lxml")

            if self._is_blocked(book_resp, book_soup):
                return ScraperResult(
                    scraper_name=self.name,
                    success=False,
                    error_message="Goodreads blocked the book page request",
                )

            metadata = self._parse_book_page_metadata(book_soup, book_url)
            ratings = self._parse_ratings(book_soup)
            reviews = self._parse_reviews(book_soup)
            similar = self._parse_similar(book_soup)

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                metadata=metadata,
                ratings=ratings,
                reviews=reviews,
                similar_books=similar,
                raw_data={"book_url": book_url},
            )
        except Exception as exc:
            logger.error("Goodreads book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _is_blocked(self, resp, soup: BeautifulSoup) -> bool:
        if resp.status_code in (403, 503):
            return True
        text_lower = resp.text[:3000].lower()
        indicators = ["captcha", "cf-browser-verification", "robot", "access denied",
                      "automated requests", "unusual traffic"]
        return any(ind in text_lower for ind in indicators)

    def _parse_list_page(self, soup: BeautifulSoup) -> list[TrendingEntry]:
        entries: list[TrendingEntry] = []

        # tableList tr.bookItem — used in list pages
        rows = soup.select("tr.bookItem, div.elementList")
        if not rows:
            # Fallback: generic book title links
            rows = soup.select("div.bookalike")

        for i, row in enumerate(rows[:40]):
            title_el = (
                row.select_one("a.bookTitle span")
                or row.select_one("a.bookTitle")
                or row.select_one(".title a")
                or row.select_one("td:nth-child(3) a")
            )
            author_el = (
                row.select_one("a.authorName span")
                or row.select_one("a.authorName")
                or row.select_one(".author a")
            )
            cover_el = row.select_one("img")

            if not title_el:
                continue

            title_text = title_el.get_text(strip=True)
            authors = [author_el.get_text(strip=True)] if author_el else []
            cover_url = cover_el.get("src") if cover_el else None

            # Rating within the row
            rating_el = row.select_one(".minirating")
            avg_rating: Optional[float] = None
            if rating_el:
                m = re.search(r"(\d+\.\d+)\s+avg", rating_el.get_text())
                if m:
                    avg_rating = float(m.group(1))

            link_el = row.select_one("a.bookTitle, td:nth-child(3) a")
            book_href = link_el.get("href") if link_el else None
            book_url = f"{BASE}{book_href}" if book_href and book_href.startswith("/") else book_href

            metadata = BookMetadata(
                title=title_text,
                authors=authors,
                cover_url=cover_url,
                source=self.name,
                source_url=book_url,
            )
            signal = TrendSignal(
                source=self.name,
                score=max(0.0, 90 - i * 2.2),
                rank=i + 1,
                signal_type="goodreads_best_of_month",
                url=book_url,
            )
            ratings: list[RatingData] = []
            if avg_rating:
                ratings.append(RatingData(
                    source=self.name,
                    rating=avg_rating,
                    raw_rating=avg_rating,
                    raw_scale=5.0,
                ))
            entries.append(TrendingEntry(metadata=metadata, trend_signal=signal, ratings=ratings))

        return entries

    def _extract_first_result_url(self, soup: BeautifulSoup) -> Optional[str]:
        a = soup.select_one("a.bookTitle, table.tableList a.bookTitle")
        if a:
            href = a.get("href", "")
            return f"{BASE}{href}" if href.startswith("/") else href
        return None

    def _parse_book_page_metadata(self, soup: BeautifulSoup, url: str) -> BookMetadata:
        title_el = (
            soup.select_one("h1[data-testid='bookTitle']")
            or soup.select_one("h1#bookTitle")
            or soup.select_one("h1.Text__title1")
        )
        title = title_el.get_text(strip=True) if title_el else "Unknown"

        author_els = soup.select("span.ContributorLink__name, a.authorName span")
        authors = list(dict.fromkeys(a.get_text(strip=True) for a in author_els))[:3]

        desc_el = (
            soup.select_one("div.BookPageMetadataSection__description span.Formatted")
            or soup.select_one("div#description span")
        )
        description = desc_el.get_text(strip=True) if desc_el else None

        cover_el = soup.select_one("img.ResponsiveImage, img#coverImage")
        cover = cover_el.get("src") if cover_el else None

        genre_els = soup.select("a.BookPageMetadataSection__genreButton, a.bookPageGenreLink")
        genres = [g.get_text(strip=True) for g in genre_els[:8]]

        pages: Optional[int] = None
        pages_el = soup.select_one("p[data-testid='pagesFormat']")
        if pages_el:
            m = re.search(r"(\d+)\s+pages", pages_el.get_text())
            if m:
                pages = int(m.group(1))

        return BookMetadata(
            title=title,
            authors=authors,
            description=description,
            cover_url=cover,
            page_count=pages,
            genres=genres,
            source=self.name,
            source_url=url,
        )

    def _parse_ratings(self, soup: BeautifulSoup) -> list[RatingData]:
        # New Goodreads UI
        rating_el = (
            soup.select_one("div.RatingStatistics__rating")
            or soup.select_one("span#avgRating")
            or soup.select_one("div[data-testid='ratingsCount'] span")
        )
        if not rating_el:
            return []

        avg_text = rating_el.get_text(strip=True)
        m = re.search(r"(\d+\.\d+)", avg_text)
        if not m:
            return []

        avg = float(m.group(1))

        # Rating count
        count: Optional[int] = None
        count_el = soup.select_one("span[data-testid='ratingsCount'], span.votes")
        if count_el:
            count_text = count_el.get_text().replace(",", "")
            cm = re.search(r"(\d+)", count_text)
            if cm:
                count = int(cm.group(1))

        return [RatingData(
            source=self.name,
            rating=round(avg, 2),
            raw_rating=avg,
            raw_scale=5.0,
            rating_count=count,
        )]

    def _parse_reviews(self, soup: BeautifulSoup) -> list[Review]:
        review_els = soup.select(
            "section.ReviewText, div.ReviewText__content, div.friendReviews div.bodycol"
        )[:8]
        reviews: list[Review] = []
        for el in review_els:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 50:
                reviews.append(Review(source=self.name, text=text[:800]))
        return reviews

    def _parse_similar(self, soup: BeautifulSoup) -> list[SimilarBook]:
        similar_els = soup.select("div.BookCard, li.cover, div.RelatedWork")[:8]
        similar: list[SimilarBook] = []
        for el in similar_els:
            title_el = el.select_one("div.BookCard__title, .title a, a.bookTitle")
            author_el = el.select_one("div.BookCard__authorName, .author a")
            if title_el:
                similar.append(SimilarBook(
                    title=title_el.get_text(strip=True),
                    authors=[author_el.get_text(strip=True)] if author_el else [],
                    source=self.name,
                    reason="Goodreads 'readers also enjoyed'",
                ))
        return similar
