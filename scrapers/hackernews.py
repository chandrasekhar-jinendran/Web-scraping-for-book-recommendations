from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

from bs4 import BeautifulSoup

from .base import BaseScraper, Discussion, ScraperResult

logger = logging.getLogger(__name__)
ALGOLIA = "https://hn.algolia.com/api/v1"


class HackerNewsScraper(BaseScraper):
    name = "hackernews"
    rate_limit_rps = 1.5

    # ------------------------------------------------------------------
    # Trending mode — "What are you reading" community threads
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        queries = [
            ("what are you reading", "ask_hn"),
            ("book recommendations", "ask_hn"),
            ("best books", "ask_hn"),
        ]

        all_discussions: list[Discussion] = []
        seen_ids: set[str] = set()
        raw: dict = {}

        since = int(time.time()) - 180 * 86400  # last 6 months

        for query, tag in queries:
            try:
                resp = await self._get(
                    f"{ALGOLIA}/search",
                    params={
                        "query": query,
                        "tags": tag,
                        "hitsPerPage": 8,
                        "numericFilters": f"created_at_i>{since}",
                    },
                )
                hits = resp.json().get("hits", [])
                raw[query] = len(hits)

                comment_tasks = []
                valid_hits = []
                for hit in hits:
                    sid = hit.get("objectID", "")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        valid_hits.append(hit)
                        comment_tasks.append(self._fetch_top_comments(sid))

                comment_batches = await asyncio.gather(*comment_tasks, return_exceptions=True)

                for hit, comments in zip(valid_hits, comment_batches):
                    sid = hit.get("objectID", "")
                    all_discussions.append(Discussion(
                        source=self.name,
                        title=hit.get("title", ""),
                        url=f"https://news.ycombinator.com/item?id={sid}",
                        score=hit.get("points"),
                        comment_count=hit.get("num_comments"),
                        top_comments=comments if isinstance(comments, list) else [],
                    ))

            except Exception as exc:
                raw[f"{query}_error"] = str(exc)
                logger.warning("HN query '%s' failed: %s", query, exc)

        return ScraperResult(
            scraper_name=self.name,
            success=True,
            discussions=sorted(all_discussions, key=lambda d: -(d.score or 0))[:15],
            raw_data=raw,
        )

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        query = f"{title} {author}" if author else f"{title} book"
        try:
            resp = await self._get(
                f"{ALGOLIA}/search",
                params={"query": query, "tags": "(story,ask_hn)", "hitsPerPage": 10},
            )
            hits = resp.json().get("hits", [])
            title_lower = title.lower()

            relevant = [
                h for h in hits
                if title_lower in h.get("title", "").lower()
            ]

            discussions: list[Discussion] = []
            for hit in relevant[:5]:
                sid = hit.get("objectID", "")
                comments = await self._fetch_top_comments(sid)
                discussions.append(Discussion(
                    source=self.name,
                    title=hit.get("title", ""),
                    url=f"https://news.ycombinator.com/item?id={sid}",
                    score=hit.get("points"),
                    comment_count=hit.get("num_comments"),
                    top_comments=comments,
                ))

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                discussions=discussions,
                raw_data={"total_hits": len(hits), "relevant": len(relevant)},
            )
        except Exception as exc:
            logger.error("HN book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_top_comments(self, story_id: str) -> list[str]:
        try:
            resp = await self._get(f"{ALGOLIA}/items/{story_id}")
            children = resp.json().get("children", [])
            comments: list[str] = []
            for child in children[:6]:
                text = child.get("text") or ""
                if len(text) > 30:
                    clean = BeautifulSoup(text, "lxml").get_text(separator=" ").strip()
                    clean = re.sub(r"\s+", " ", clean)
                    comments.append(clean[:600])
                if len(comments) >= 3:
                    break
            return comments
        except Exception:
            return []
