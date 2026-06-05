from __future__ import annotations

import logging
import math
import re
import unicodedata
from datetime import datetime
from typing import Optional

from scrapers.base import (
    AggregatedReport, BookMetadata, BestsellerStatus, Discussion,
    RatingData, RatingsSummary, Review, ScraperResult, SimilarBook,
    TrendingBook, TrendingEntry, TrendSignal,
)

logger = logging.getLogger(__name__)

# Metadata source priority (higher = preferred when merging)
_META_PRIORITY = {
    "openlibrary": 5,
    "googlebooks": 4,
    "nyt": 3,
    "goodreads": 2,
    "gutenberg": 1,
    "hackernews": 0,
    "reddit": 0,
}


def _norm_title(title: str) -> str:
    """Normalize a book title for deduplication."""
    t = unicodedata.normalize("NFKD", title.lower())
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\b(the|a|an)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _norm_author(authors: list[str]) -> str:
    if not authors:
        return ""
    a = authors[0].lower()
    parts = a.replace(",", " ").split()
    return parts[-1] if parts else a


class BookDataAggregator:
    """Merges ScraperResult objects into a single AggregatedReport."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate_trending(
        self,
        results: list[ScraperResult],
        generated_at: str,
    ) -> AggregatedReport:
        warnings = self._collect_warnings(results)

        # Flatten all TrendingEntry objects from all scrapers
        all_entries: list[TrendingEntry] = []
        for r in results:
            all_entries.extend(r.trending_books)

        # Reddit/HN discussions as context (not book entries)
        discussions = self._merge_discussions(results)

        trending_books = self._build_trending_books(all_entries)

        return AggregatedReport(
            mode="trending",
            generated_at=generated_at,
            trending_books=trending_books,
            discussions=discussions,
            scraper_results=results,
            warnings=warnings,
        )

    def aggregate_book(
        self,
        results: list[ScraperResult],
        query_title: str,
        query_author: Optional[str],
        generated_at: str,
    ) -> AggregatedReport:
        warnings = self._collect_warnings(results)

        all_meta = [r.metadata for r in results if r.metadata]
        canonical = self._pick_canonical_metadata(all_meta)

        return AggregatedReport(
            mode="book",
            generated_at=generated_at,
            query_title=query_title,
            query_author=query_author,
            canonical_metadata=canonical,
            all_metadata=all_meta,
            ratings_summary=self._aggregate_ratings(results),
            reviews=self._merge_reviews(results),
            discussions=self._merge_discussions(results),
            similar_books=self._deduplicate_similar(results),
            bestseller_statuses=self._merge_bestsellers(results),
            scraper_results=results,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Trending helpers
    # ------------------------------------------------------------------

    def _build_trending_books(self, entries: list[TrendingEntry]) -> list[TrendingBook]:
        # Group entries by normalized title+author key
        groups: dict[str, list[TrendingEntry]] = {}
        for entry in entries:
            key = (_norm_title(entry.metadata.title), _norm_author(entry.metadata.authors))
            key_str = f"{key[0]}||{key[1]}"
            if key_str not in groups:
                groups[key_str] = []
            groups[key_str].append(entry)

        books: list[TrendingBook] = []
        for group in groups.values():
            if not group:
                continue

            # Merge metadata — prefer highest-priority source
            all_meta = [e.metadata for e in group]
            metadata = self._pick_canonical_metadata(all_meta) or all_meta[0]

            # Skip obvious junk (very short titles with no author)
            if len(metadata.title) < 2:
                continue

            # Collect signals, ratings, bestseller statuses
            signals = [e.trend_signal for e in group]
            ratings = [r for e in group for r in e.ratings]
            bestsellers = [b for e in group for b in e.bestseller_statuses]
            sources = list(dict.fromkeys(s.source for s in signals))

            # Composite score
            base_score = sum(s.score for s in signals) / len(signals)
            cross_bonus = 1 + 0.25 * (len(sources) - 1)
            trend_score = round(base_score * cross_bonus, 2)

            books.append(TrendingBook(
                metadata=metadata,
                trend_score=trend_score,
                sources_found_in=sources,
                trend_signals=signals,
                ratings=ratings,
                ratings_summary=self._build_ratings_summary(ratings),
                bestseller_statuses=bestsellers,
            ))

        # Sort by composite score descending, return top 30
        books.sort(key=lambda b: -b.trend_score)
        return books[:30]

    # ------------------------------------------------------------------
    # Book-mode helpers
    # ------------------------------------------------------------------

    def _pick_canonical_metadata(self, metas: list[BookMetadata]) -> Optional[BookMetadata]:
        if not metas:
            return None

        sorted_meta = sorted(
            metas,
            key=lambda m: _META_PRIORITY.get(m.source, 0),
            reverse=True,
        )
        base = sorted_meta[0]

        # Fill in gaps from lower-priority sources
        description = base.description
        cover_url = base.cover_url
        genres: list[str] = list(base.genres)

        for m in sorted_meta[1:]:
            if not description and m.description:
                description = m.description
            if not cover_url and m.cover_url:
                cover_url = m.cover_url
            for g in m.genres:
                if g not in genres:
                    genres.append(g)

        return BookMetadata(
            title=base.title,
            authors=base.authors or next((m.authors for m in sorted_meta if m.authors), []),
            isbn_10=base.isbn_10 or next((m.isbn_10 for m in sorted_meta if m.isbn_10), None),
            isbn_13=base.isbn_13 or next((m.isbn_13 for m in sorted_meta if m.isbn_13), None),
            published_year=base.published_year or next(
                (m.published_year for m in sorted_meta if m.published_year), None),
            publisher=base.publisher or next((m.publisher for m in sorted_meta if m.publisher), None),
            description=description,
            cover_url=cover_url,
            page_count=base.page_count or next((m.page_count for m in sorted_meta if m.page_count), None),
            genres=genres[:12],
            language=base.language or next((m.language for m in sorted_meta if m.language), None),
            source=base.source,
            source_url=base.source_url,
        )

    def _aggregate_ratings(self, results: list[ScraperResult]) -> Optional[RatingsSummary]:
        all_ratings = [r for res in results for r in res.ratings]
        return self._build_ratings_summary(all_ratings)

    def _build_ratings_summary(self, ratings: list[RatingData]) -> Optional[RatingsSummary]:
        if not ratings:
            return None

        total_weight = 0.0
        weighted_sum = 0.0
        total_count = 0

        for r in ratings:
            weight = math.log10((r.rating_count or 1) + 1)
            weighted_sum += r.rating * weight
            total_weight += weight
            total_count += r.rating_count or 0

        avg = round(weighted_sum / total_weight, 2) if total_weight > 0 else None
        return RatingsSummary(
            normalized_average=avg,
            sources=ratings,
            total_rating_count=total_count,
        )

    def _merge_reviews(self, results: list[ScraperResult]) -> list[Review]:
        seen: set[tuple] = set()
        reviews: list[Review] = []
        for r in results:
            for review in r.reviews:
                key = (review.source, (review.author_name or "")[:40])
                if key not in seen:
                    seen.add(key)
                    reviews.append(review)

        reviews.sort(key=lambda r: -(r.rating or 0))
        return reviews[:15]

    def _merge_discussions(self, results: list[ScraperResult]) -> list[Discussion]:
        seen: set[str] = set()
        discussions: list[Discussion] = []
        for r in results:
            for d in r.discussions:
                if d.url not in seen:
                    seen.add(d.url)
                    discussions.append(d)

        discussions.sort(key=lambda d: -(d.score or 0))
        return discussions[:20]

    def _deduplicate_similar(self, results: list[ScraperResult]) -> list[SimilarBook]:
        seen: dict[str, int] = {}
        books: list[SimilarBook] = []
        for r in results:
            for book in r.similar_books:
                key = _norm_title(book.title)
                if key not in seen:
                    seen[key] = len(books)
                    books.append(book)

        return books[:20]

    def _merge_bestsellers(self, results: list[ScraperResult]) -> list[BestsellerStatus]:
        statuses: list[BestsellerStatus] = []
        for r in results:
            statuses.extend(r.bestseller_status)
        return statuses

    def _collect_warnings(self, results: list[ScraperResult]) -> list[str]:
        warnings: list[str] = []
        for r in results:
            if not r.success and r.error_message:
                warnings.append(f"[{r.scraper_name}] {r.error_message}")
        return warnings
