import logging
from datetime import datetime, timedelta, timezone

import yt_dlp

from collectors import PlatformMetrics
from config import (
    YOUTUBE_LOOKBACK_DAYS,
    YOUTUBE_MAX_VIDEOS_PER_BRAND,
    YOUTUBE_FULL_FETCH_TOP_N,
)
from database.db import get_metrics, upsert_metrics, log_collection

logger = logging.getLogger(__name__)

# Flat extraction: fast search, returns view counts + basic metadata
_YDL_FLAT = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
}

# Full extraction: individual video page, returns likes + comments
_YDL_FULL = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}


class YouTubeCollector:
    """Finds creator videos about each brand via YouTube search.

    Uses yt-dlp — no API key, no quota limits, unlimited runs.

    Strategy (hybrid):
      1. Flat search  → top 50 creator videos, view counts only (1 fast request)
      2. Full fetch   → top N by view count, get likes + comments (N requests)

    This gives us video volume, total reach, AND a real engagement rate
    without touching the YouTube Data API.
    """

    def collect(self, brand_name: str, channel_id: str = "",
                use_cache: bool = True) -> PlatformMetrics:
        """Collect YouTube creator metrics for a brand.

        Args:
            brand_name: Brand to search for (e.g. "CeraVe").
            channel_id: Ignored — kept for API compatibility.
            use_cache: Return cached DB result if available.
        """
        if use_cache:
            cached = get_metrics(brand_name, "youtube")
            if cached:
                return self._from_dict(brand_name, cached["metrics"], "cache")

        try:
            return self._collect_live(brand_name)
        except Exception as e:
            logger.error(f"YouTube collection failed for {brand_name}: {e}")
            log_collection(brand_name, "youtube", "error", error_message=str(e))
            cached = get_metrics(brand_name, "youtube")
            if cached:
                return self._from_dict(brand_name, cached["metrics"], "cache")
            return PlatformMetrics(
                platform="youtube", brand_name=brand_name,
                data_source="unavailable", error=str(e),
            )

    def _collect_live(self, brand_name: str) -> PlatformMetrics:
        cutoff = datetime.now(timezone.utc) - timedelta(days=YOUTUBE_LOOKBACK_DAYS)

        # --- Step 1: Flat search — fast, gets view counts ---
        query = f"ytsearch{YOUTUBE_MAX_VIDEOS_PER_BRAND}:{brand_name}"
        with yt_dlp.YoutubeDL(_YDL_FLAT) as ydl:
            result = ydl.extract_info(query, download=False)

        candidates = []
        for entry in (result.get("entries") or []):
            if not entry:
                continue

            # Skip the brand's own channel
            channel = (entry.get("channel") or entry.get("uploader") or "").lower()
            brand_lower = brand_name.lower()
            if brand_lower in channel or channel.replace(" ", "") == brand_lower.replace(" ", ""):
                continue

            # Skip videos outside the lookback window (when date is available)
            upload_date = entry.get("upload_date")  # YYYYMMDD or None
            if upload_date:
                try:
                    dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            candidates.append({
                "id": entry.get("id"),
                "view_count": int(entry.get("view_count") or 0),
            })

        if not candidates:
            metrics = PlatformMetrics(
                platform="youtube", brand_name=brand_name, data_source="live_api"
            )
            self._save(brand_name, metrics)
            return metrics

        # Sort by views descending; full-fetch top N for engagement data
        candidates.sort(key=lambda v: v["view_count"], reverse=True)
        top = candidates[:YOUTUBE_FULL_FETCH_TOP_N]

        # --- Step 2: Full fetch top N — gets likes + comments ---
        total_likes = 0
        total_comments = 0
        with yt_dlp.YoutubeDL(_YDL_FULL) as ydl:
            for v in top:
                try:
                    info = ydl.extract_info(
                        f"https://www.youtube.com/watch?v={v['id']}", download=False
                    )
                    total_likes += int(info.get("like_count") or 0)
                    total_comments += int(info.get("comment_count") or 0)
                except Exception as e:
                    logger.warning(f"Full fetch failed for {v['id']}: {e}")

        count = len(candidates)
        total_views = sum(v["view_count"] for v in candidates)
        avg_views = total_views // count if count else 0

        top_views = sum(v["view_count"] for v in top)
        engagement_rate = (
            (total_likes + total_comments) / top_views if top_views > 0 else 0.0
        )

        metrics = PlatformMetrics(
            platform="youtube",
            brand_name=brand_name,
            data_source="live_api",
            videos_last_90d=count,
            shorts_last_90d=count,
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            avg_views=avg_views,
            avg_likes=total_likes // len(top) if top else 0,
            avg_comments=total_comments // len(top) if top else 0,
            engagement_rate=round(engagement_rate, 4),
        )

        self._save(brand_name, metrics)
        return metrics

    def _from_dict(self, brand_name: str, m: dict, source: str) -> PlatformMetrics:
        return PlatformMetrics(
            platform="youtube",
            brand_name=brand_name,
            data_source=source,
            videos_last_90d=m.get("videos_last_90d", 0),
            shorts_last_90d=m.get("shorts_last_90d", 0),
            total_views=m.get("total_views", 0),
            total_likes=m.get("total_likes", 0),
            total_comments=m.get("total_comments", 0),
            avg_views=m.get("avg_views", 0),
            avg_likes=m.get("avg_likes", 0),
            avg_comments=m.get("avg_comments", 0),
            engagement_rate=m.get("engagement_rate", 0.0),
        )

    def _save(self, brand_name: str, metrics: PlatformMetrics):
        upsert_metrics(brand_name, "youtube", metrics.to_dict(), data_source="live_api")
        log_collection(brand_name, "youtube", "success", data_source="live_api")
