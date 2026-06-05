from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .base import BaseScraper, Discussion, ScraperResult

logger = logging.getLogger(__name__)
REDDIT_BASE = "https://www.reddit.com"

# Headers that mimic a browser — Reddit blocks plain Python UA
_REDDIT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


class RedditScraper(BaseScraper):
    name = "reddit"
    rate_limit_rps = 0.5

    def __init__(self) -> None:
        super().__init__()
        self._use_praw = False
        self._praw_reddit = None

        try:
            import config
            if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
                import praw
                self._praw_reddit = praw.Reddit(
                    client_id=config.REDDIT_CLIENT_ID,
                    client_secret=config.REDDIT_CLIENT_SECRET,
                    user_agent=config.REDDIT_USER_AGENT,
                )
                self._use_praw = True
                logger.info("Reddit: using PRAW")
        except Exception as exc:
            logger.warning("PRAW init failed (%s) — falling back to HTTP", exc)

    # ------------------------------------------------------------------
    # Trending mode
    # ------------------------------------------------------------------

    async def scrape_trending(self) -> ScraperResult:
        import config
        subreddits = config.BOOK_SUBREDDITS[:3]

        all_discussions: list[Discussion] = []
        raw: dict = {}

        for sub in subreddits:
            try:
                if self._use_praw:
                    discussions = await self._praw_top(sub)
                else:
                    discussions = await self._http_top(sub)
                all_discussions.extend(discussions)
                raw[sub] = len(discussions)
            except Exception as exc:
                raw[f"{sub}_error"] = str(exc)
                logger.warning("Reddit r/%s failed: %s", sub, exc)

        return ScraperResult(
            scraper_name=self.name,
            success=True,
            discussions=sorted(all_discussions, key=lambda d: -(d.score or 0))[:20],
            raw_data=raw,
        )

    # ------------------------------------------------------------------
    # Book deep-dive mode
    # ------------------------------------------------------------------

    async def scrape_book(self, title: str, author: Optional[str]) -> ScraperResult:
        query = f"{title} {author}" if author else title
        try:
            resp = await self._get(
                f"{REDDIT_BASE}/search.json",
                params={"q": query, "sort": "relevance", "t": "year", "limit": 10},
                extra_headers=_REDDIT_HEADERS,
            )
            posts = resp.json().get("data", {}).get("children", [])

            title_lower = title.lower()
            discussions: list[Discussion] = []
            for post in posts:
                p = post.get("data", {})
                if title_lower in p.get("title", "").lower():
                    discussions.append(_post_to_discussion(p))

            return ScraperResult(
                scraper_name=self.name,
                success=True,
                discussions=discussions[:10],
                raw_data={"total_posts": len(posts), "relevant": len(discussions)},
            )
        except Exception as exc:
            logger.error("Reddit book '%s' failed: %s", title, exc)
            return ScraperResult(scraper_name=self.name, success=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _http_top(self, subreddit: str) -> list[Discussion]:
        resp = await self._get(
            f"{REDDIT_BASE}/r/{subreddit}/top.json",
            params={"t": "month", "limit": 20},
            extra_headers=_REDDIT_HEADERS,
        )
        posts = resp.json().get("data", {}).get("children", [])
        return [_post_to_discussion(p["data"]) for p in posts]

    async def _praw_top(self, subreddit: str) -> list[Discussion]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._praw_fetch_top, subreddit)

    def _praw_fetch_top(self, subreddit: str) -> list[Discussion]:
        discussions: list[Discussion] = []
        for sub in self._praw_reddit.subreddit(subreddit).top(time_filter="month", limit=20):
            discussions.append(Discussion(
                source=self.name,
                title=sub.title,
                url=f"https://reddit.com{sub.permalink}",
                score=sub.score,
                comment_count=sub.num_comments,
                subreddit=subreddit,
            ))
        return discussions


def _post_to_discussion(p: dict) -> Discussion:
    return Discussion(
        source="reddit",
        title=p.get("title", ""),
        url=f"https://reddit.com{p.get('permalink', '')}",
        score=p.get("score"),
        comment_count=p.get("num_comments"),
        subreddit=p.get("subreddit"),
    )
