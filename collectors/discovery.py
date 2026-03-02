"""Discover CPG brand names organically from YouTube video titles.

Flow per category:
  1. Run all discovery queries via yt-dlp flat search → collect titles
  2. Feed all titles to LLM in one call → returns {brand: mention_count}
  3. Return top DISCOVERY_MAX_BRANDS_PER_CATEGORY results
"""

import logging
import urllib.parse

import yt_dlp

from config import DISCOVERY_VIDEOS_PER_QUERY, DISCOVERY_MAX_BRANDS_PER_CATEGORY
from utils.brand_extractor import extract_brands_from_titles

logger = logging.getLogger(__name__)

_YDL_FLAT = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
    "playlistend": DISCOVERY_VIDEOS_PER_QUERY,
}


class DiscoveryCollector:
    """Discover brand candidates for a category by scanning YouTube titles."""

    def collect_category(self, category: str, queries: list[str]) -> dict[str, int]:
        """Return top {brand: mention_count} for a category.

        Fetches titles for all queries, deduplicates, then makes a single LLM
        call to extract real brand names.
        """
        all_titles: list[str] = []
        seen: set[str] = set()

        for query in queries:
            titles = self._fetch_titles(query)
            logger.info(f"[{category}] '{query}' → {len(titles)} titles")
            for t in titles:
                if t and t not in seen:
                    seen.add(t)
                    all_titles.append(t)

        logger.info(f"[{category}] {len(all_titles)} unique titles → sending to LLM")
        brands = extract_brands_from_titles(all_titles, category)

        top = dict(
            sorted(brands.items(), key=lambda x: x[1], reverse=True)
            [:DISCOVERY_MAX_BRANDS_PER_CATEGORY]
        )
        return top

    def _fetch_titles(self, query: str) -> list[str]:
        # Sort by upload date (most recent first) — same as the main collector
        url = (
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote(query)
            + "&sp=CAI%3D"
        )
        try:
            with yt_dlp.YoutubeDL(_YDL_FLAT) as ydl:
                result = ydl.extract_info(url, download=False)
            entries = result.get("entries") or []
            return [e.get("title") or "" for e in entries if e]
        except Exception as e:
            logger.warning(f"yt-dlp search failed for '{query}': {e}")
            return []
