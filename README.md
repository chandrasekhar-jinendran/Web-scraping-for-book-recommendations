# Book Recommendation Scraper

A Python tool that aggregates book data from 7 free sources in parallel and generates rich HTML reports. Two modes: **Trending 30** (hottest books this month) and **Book Deep-Dive** (full data on a specific title).

Available as a **CLI tool** or a **Flask web app**.

---

## What it does

Runs all scrapers concurrently and merges the results into a single HTML report. No database — every run scrapes live data.

| Source | What it provides | Auth required |
|---|---|---|
| [Open Library](https://openlibrary.org) | 36M books — metadata, ratings, subjects, covers | None |
| [Google Books](https://books.google.com) | Descriptions, categories, preview links | None (key optional for higher quota) |
| [Project Gutenberg](https://gutendex.com) | Public domain availability, download links | None |
| [Hacker News](https://news.ycombinator.com) | Tech/non-fiction discussion threads (Algolia API) | None |
| [Reddit](https://reddit.com) | r/books, r/suggestmeabook, r/fantasy hot posts | None (PRAW credentials optional) |
| [NYT Books](https://developer.nytimes.com/docs/books-product/1/overview) | Weekly bestseller lists (fiction, nonfiction, YA…) | Free API key (optional) |
| [Goodreads](https://goodreads.com) | Community ratings, reviews, "Best Books This Month" | None (web scrape, rate-limited) |

---

## Modes

### Trending 30 (default)

Fetches trending signals from all sources, scores and ranks by cross-source popularity, and outputs the 30 hottest books of the month.

```bash
python main.py
python main.py --output trending_june.html
```

Each book is scored using a composite formula:
- **NYT**: rank-based score (1st place = 100), +20 bonus if on multiple lists
- **Reddit**: `log10(upvotes+1) × 10 + log10(comments+1) × 5`, with freshness decay for posts older than 30 days
- **Open Library**: position in the monthly trending feed
- **HN**: `log10(points+1) × 15`
- **Cross-source multiplier**: books found on N sources get `score × (1 + 0.2 × (N−1))`

### Book Deep-Dive

Full metadata, ratings from every source, community discussions, similar books, and bestseller history for one title.

```bash
python main.py "Dune"
python main.py "Clean Code" --author "Robert Martin"
python main.py "Atomic Habits" --output atomic_habits.html
```

---

## Web App

A minimal Flask UI wraps both modes. The same HTML report is served in the browser with an added navigation bar.

```bash
python app.py
# Open http://localhost:5000
```

Routes:

| Route | What it does |
|---|---|
| `GET /` | Home page — search form + Trending 30 link |
| `GET /trending` | Runs trending scrape, returns report |
| `GET /book?title=Dune&author=Herbert` | Runs book deep-dive, returns report |

---

## Installation

**Requirements:** Python 3.11+

```bash
git clone https://github.com/chandrasekhar-jinendran/Web-scraping-for-book-recommendations
cd Web-scraping-for-book-recommendations
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to add any optional API keys (see Configuration below).

---

## Configuration

All scrapers work without any keys. Keys unlock additional data or higher rate limits.

```env
# NYT Books — current bestseller lists
# Get free key at: https://developer.nytimes.com/accounts/create
NYT_API_KEY=

# Reddit — richer data via PRAW (falls back to public JSON feed without this)
# Create an app at: https://www.reddit.com/prefs/apps
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=BookScraper/1.0 by /u/yourusername

# Google Books — increases daily quota from 1,000 to 10,000+ requests
# Get key at: https://console.cloud.google.com → Enable Books API
GOOGLE_BOOKS_API_KEY=

# Flask — set this in production, any random string works
FLASK_SECRET_KEY=change-this-in-production
```

---

## Deployment on Render.com

> **Why not Netlify?** Netlify only hosts static sites and serverless functions with a 10-second free-tier timeout. Scraping 7 sources takes 20–60 seconds — it will always time out. Render.com supports long-running Python web services on its free tier.

### Steps

1. Push the repo to GitHub (already done)
2. Go to **[render.com](https://render.com) → New → Web Service**
3. Connect your GitHub repository
4. Render auto-detects `render.yaml` — click **Apply**
5. Under **Environment Variables**, add your optional keys (`NYT_API_KEY`, etc.)
6. Click **Deploy** — you'll get a public `https://your-app.onrender.com` URL in ~2 minutes

The `render.yaml` in the repo configures everything automatically:
- Python 3.11 runtime
- `gunicorn` with a 120-second request timeout
- Auto-generated `FLASK_SECRET_KEY`

> **Free tier note:** Render spins down free instances after 15 minutes of inactivity. The first request after spin-down takes ~30 seconds before scraping even begins. Upgrade to the $7/month Starter plan to keep it always-on.

---

## Project structure

```
├── app.py              Flask web app (routes: /, /trending, /book)
├── main.py             CLI entry point
├── config.py           Env vars, rate-limit constants, source toggles
├── aggregator.py       Merges scraper results — dedup, scoring, metadata priority
├── renderer.py         Jinja2 → HTML (file output or in-memory string)
├── requirements.txt
├── Procfile            gunicorn start command for Render
├── render.yaml         Render.com one-click deployment config
├── runtime.txt         Python 3.11
├── .env.example        Template for API keys
├── scrapers/
│   ├── base.py         Data models + BaseScraper (async HTTP, rate limiting, retries)
│   ├── openlibrary.py
│   ├── googlebooks.py
│   ├── gutenberg.py
│   ├── hackernews.py
│   ├── reddit.py       PRAW if credentials present, public JSON fallback otherwise
│   ├── nyt.py          Skipped if NYT_API_KEY not set
│   └── goodreads.py    Web scrape — 0.3 RPS, graceful WAF failure
└── templates/
    ├── index.html      Web app home page
    └── report.html.j2  Jinja2 report template (CLI + web)
```

---

## Adding a REST API

The scraper pipeline is already structured to return data as Python dataclasses. Exposing a JSON API requires adding endpoints to `app.py` and a serialization helper.

### Suggested endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/trending` | Top 30 trending books as JSON |
| `GET` | `/api/book?title=Dune&author=Herbert` | Full book data as JSON |
| `GET` | `/api/health` | Uptime check — returns `{"status":"ok"}` |

### Implementation sketch

**1. Add a `to_dict()` helper in `aggregator.py` or a new `api.py`:**

```python
from dataclasses import asdict
from scrapers.base import AggregatedReport

def report_to_dict(report: AggregatedReport) -> dict:
    """Convert a report to a JSON-serialisable dict."""
    return {
        "mode": report.mode,
        "generated_at": report.generated_at,
        "trending_books": [
            {
                "rank": i + 1,
                "title": b.metadata.title,
                "authors": b.metadata.authors,
                "year": b.metadata.published_year,
                "cover_url": b.metadata.cover_url,
                "description": b.metadata.description,
                "genres": b.metadata.genres,
                "trend_score": b.trend_score,
                "sources": b.sources_found_in,
                "rating": b.ratings_summary.normalized_average if b.ratings_summary else None,
                "rating_count": b.ratings_summary.total_rating_count if b.ratings_summary else 0,
                "bestseller": [
                    {"list": s.list_name, "rank": s.rank}
                    for s in b.bestseller_statuses
                ],
            }
            for i, b in enumerate(report.trending_books)
        ] if report.mode == "trending" else None,
        "book": {
            "title": report.canonical_metadata.title,
            "authors": report.canonical_metadata.authors,
            "isbn_13": report.canonical_metadata.isbn_13,
            "year": report.canonical_metadata.published_year,
            "publisher": report.canonical_metadata.publisher,
            "description": report.canonical_metadata.description,
            "cover_url": report.canonical_metadata.cover_url,
            "genres": report.canonical_metadata.genres,
            "pages": report.canonical_metadata.page_count,
            "rating": report.ratings_summary.normalized_average if report.ratings_summary else None,
            "rating_count": report.ratings_summary.total_rating_count if report.ratings_summary else 0,
            "ratings_by_source": [
                {"source": r.source, "rating": r.rating, "count": r.rating_count}
                for r in (report.ratings_summary.sources if report.ratings_summary else [])
            ],
            "similar_books": [
                {"title": s.title, "authors": s.authors}
                for s in report.similar_books[:10]
            ],
            "discussions": [
                {"source": d.source, "title": d.title, "url": d.url, "score": d.score}
                for d in report.discussions[:10]
            ],
        } if report.mode == "book" else None,
        "warnings": report.warnings,
    }
```

**2. Add JSON routes to `app.py`:**

```python
from flask import jsonify
from api import report_to_dict   # the helper above

@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})

@app.route("/api/trending")
def api_trending():
    report = asyncio.run(_run_trending())
    return jsonify(report_to_dict(report))

@app.route("/api/book")
def api_book():
    title = request.args.get("title", "").strip()
    author = request.args.get("author", "").strip() or None
    if not title:
        return jsonify({"error": "title parameter required"}), 400
    report = asyncio.run(_run_book(title, author))
    return jsonify(report_to_dict(report))
```

**3. Example API calls:**

```bash
# Health check
curl http://localhost:5000/api/health

# Trending 30
curl http://localhost:5000/api/trending | python -m json.tool

# Book deep-dive
curl "http://localhost:5000/api/book?title=Dune&author=Herbert" | python -m json.tool
```

### Caching (recommended before exposing publicly)

Each scrape takes 20–60 seconds. Add `flask-caching` to cache responses:

```python
# pip install flask-caching
from flask_caching import Cache

cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 3600})

@app.route("/api/trending")
@cache.cached(timeout=3600)   # cache for 1 hour
def api_trending():
    ...
```

### Authentication (if exposing publicly)

For a simple API key gate, add a decorator to the JSON routes:

```python
import functools
from flask import request, jsonify
import os

def require_api_key(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != os.getenv("API_SECRET_KEY"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/api/trending")
@require_api_key
def api_trending():
    ...
```

Set `API_SECRET_KEY=your-secret` in `.env` and include it in requests:

```bash
curl -H "X-API-Key: your-secret" http://localhost:5000/api/trending
```

### Other API ideas

- **`GET /api/sources`** — return which scrapers are enabled/disabled and why (useful for debugging)
- **`GET /api/book/batch`** with `?titles[]=Dune&titles[]=Foundation` — scrape multiple books in one call
- **WebSocket `/ws/book`** — stream scraper progress events as each source completes, so the client can show partial results in real time without waiting 60 seconds for the full response

---

## Rate limits and fair use

All scraping is done politely:
- Per-scraper rate limits (0.3–2 RPS depending on source)
- Exponential backoff on 429/5xx responses
- Browser-like headers to avoid trivial bot detection
- Goodreads: 0.3 RPS with WAF detection — falls back gracefully if blocked

This tool is for personal and developer use. Do not hammer any source aggressively or deploy it as a high-traffic public service without checking each site's ToS.
