from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import jinja2

from scrapers.base import AggregatedReport


class ReportRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=jinja2.select_autoescape(["html", "j2"]),
        )
        self._env.filters["stars"] = _stars_filter
        self._env.filters["truncate_smart"] = _truncate_smart
        self._env.filters["fmt_count"] = _fmt_count
        self._env.filters["source_color"] = _source_color
        self._env.filters["score_bar_width"] = lambda s: min(100, max(0, float(s or 0)))
        self._env.globals["to_json"] = _safe_json

    def render(self, report: AggregatedReport, output_path: str) -> None:
        html = self.render_to_string(report)
        Path(output_path).write_text(html, encoding="utf-8")

    def render_to_string(self, report: AggregatedReport, web_mode: bool = False) -> str:
        template = self._env.get_template("report.html.j2")
        return template.render(report=report, web_mode=web_mode)


# ---------------------------------------------------------------------------
# Jinja2 filters
# ---------------------------------------------------------------------------

def _stars_filter(rating: Optional[float]) -> str:
    if rating is None:
        return "N/A"
    full = int(rating)
    half = 1 if (rating - full) >= 0.5 else 0
    empty = 5 - full - half
    return "★" * full + ("½" if half else "") + "☆" * empty + f" ({rating:.2f})"


def _truncate_smart(text: Optional[str], length: int = 200) -> str:
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "…"


def _fmt_count(n: Optional[int]) -> str:
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _source_color(source: str) -> str:
    return {
        "openlibrary": "#e63946",
        "googlebooks":  "#4285f4",
        "gutenberg":    "#06b6d4",
        "hackernews":   "#ff6600",
        "reddit":       "#ff4500",
        "nyt":          "#c8102e",
        "goodreads":    "#553b08",
    }.get(source, "#666")


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        return "{}"
