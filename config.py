import os
import logging
from dotenv import load_dotenv

load_dotenv()

NYT_API_KEY = os.getenv("NYT_API_KEY")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "BookScraper/1.0")
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

HTTP_TIMEOUT = 20
MAX_RETRIES = 2

# Mimics a real browser to reduce bot-blocking on scraped sites
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SOURCES = {
    "openlibrary": {"enabled": True,              "rate_limit_rps": 1.0},
    "googlebooks":  {"enabled": True,              "rate_limit_rps": 1.0},
    "gutenberg":    {"enabled": True,              "rate_limit_rps": 1.0},
    "hackernews":   {"enabled": True,              "rate_limit_rps": 2.0},
    "reddit":       {"enabled": True,              "rate_limit_rps": 0.5},
    "nyt":          {"enabled": bool(NYT_API_KEY), "rate_limit_rps": 0.5},
    "goodreads":    {"enabled": True,              "rate_limit_rps": 0.3},
}

BOOK_SUBREDDITS = ["books", "suggestmeabook", "fantasy", "printSF", "nonfictionbooks"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
