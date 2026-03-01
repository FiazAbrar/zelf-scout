import logging
import re
from datetime import datetime, timedelta, timezone
from math import log2

import yt_dlp

from collectors import PlatformMetrics
from config import (
    REVIEW_KEYWORDS,
    PURCHASE_KEYWORDS,
    YOUTUBE_LOOKBACK_DAYS,
    YOUTUBE_MAX_VIDEOS_PER_BRAND,
    YOUTUBE_FULL_FETCH_TOP_N,
    YOUTUBE_COMMENT_SAMPLE_SIZE,
)
from database.db import get_metrics, upsert_metrics, log_collection

logger = logging.getLogger(__name__)

# Precompile keyword regexes once at import time
_REVIEW_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in REVIEW_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_PURCHASE_RE = re.compile(
    r"(" + "|".join(re.escape(k) for k in PURCHASE_KEYWORDS) + r")",
    re.IGNORECASE,
)

# yt-dlp option sets
_YDL_FLAT = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
}
_YDL_FULL = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}
_YDL_COMMENTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "getcomments": True,
    "extractor_args": {
        "youtube": {"max_comments": [str(YOUTUBE_COMMENT_SAMPLE_SIZE)]}
    },
}


class YouTubeCollector:
    """Finds creator videos about each brand via YouTube search.

    Uses yt-dlp — no API key, no quota limits, unlimited runs.

    Collection strategy (hybrid):
      Step 1 — Flat search  : top-N creator videos, view counts + titles + channels  (1 fast request)
      Step 2 — Full fetch   : top-K by views, get likes + comments                   (K requests)
      Step 3 — Comment fetch: top-1 video only, purchase intent keyword analysis     (1 request)

    Signals produced:
      - total_views, engagement_rate         → reach and audience quality
      - unique_creators, breakout_ratio      → ecosystem breadth and viral potential
      - review_intent_ratio                  → creator intentionality (title analysis)
      - purchase_intent_score                → audience purchase signals (comment analysis)
    """

    def collect(self, brand_name: str, channel_id: str = "",
                use_cache: bool = True) -> PlatformMetrics:
        """Collect YouTube creator metrics for a brand.

        Args:
            brand_name: Brand to search for (e.g. "CeraVe").
            channel_id: Ignored — kept for API compatibility with older callers.
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

        # ------------------------------------------------------------------ #
        # Step 1: Flat search — fast, returns view counts + titles + channels #
        # ------------------------------------------------------------------ #
        query = f"ytsearch{YOUTUBE_MAX_VIDEOS_PER_BRAND}:{brand_name}"
        with yt_dlp.YoutubeDL(_YDL_FLAT) as ydl:
            result = ydl.extract_info(query, download=False)

        candidates = []
        channels_seen = set()

        for entry in (result.get("entries") or []):
            if not entry:
                continue

            # Skip the brand's own channel
            channel = (entry.get("channel") or entry.get("uploader") or "").strip()
            brand_lower = brand_name.lower()
            channel_lower = channel.lower()
            if brand_lower in channel_lower or channel_lower.replace(" ", "") == brand_lower.replace(" ", ""):
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
                "title": entry.get("title") or "",
                "channel": channel,
            })
            channels_seen.add(channel.lower())

        if not candidates:
            metrics = PlatformMetrics(
                platform="youtube", brand_name=brand_name, data_source="live_api"
            )
            self._save(brand_name, metrics)
            return metrics

        # Derived signals from flat search (zero extra requests)
        view_counts = [v["view_count"] for v in candidates]
        total_views = sum(view_counts)
        count = len(candidates)
        avg_views = total_views // count if count else 0
        max_views = max(view_counts, default=0)
        breakout_ratio = round(max_views / avg_views, 2) if avg_views > 0 else 0.0
        unique_creators = len(channels_seen)

        titles = [v["title"] for v in candidates]
        review_hits = sum(1 for t in titles if _REVIEW_RE.search(t))
        review_intent_ratio = round(review_hits / len(titles), 3) if titles else 0.0

        # Sort by views; top-K go to full fetch
        candidates.sort(key=lambda v: v["view_count"], reverse=True)
        top = candidates[:YOUTUBE_FULL_FETCH_TOP_N]

        # ------------------------------------------------------------------ #
        # Step 2: Full fetch top-K — get likes + comments                     #
        # ------------------------------------------------------------------ #
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

        top_views = sum(v["view_count"] for v in top)
        engagement_rate = (
            (total_likes + total_comments) / top_views if top_views > 0 else 0.0
        )

        # ------------------------------------------------------------------ #
        # Step 3: Comment fetch on top-1 video — purchase intent analysis     #
        # ------------------------------------------------------------------ #
        purchase_intent_score = 0.0
        if top:
            try:
                with yt_dlp.YoutubeDL(_YDL_COMMENTS) as ydl:
                    comment_info = ydl.extract_info(
                        f"https://www.youtube.com/watch?v={top[0]['id']}", download=False
                    )
                comments = comment_info.get("comments") or []
                if comments:
                    hits = sum(
                        1 for c in comments
                        if _PURCHASE_RE.search(c.get("text") or "")
                    )
                    purchase_intent_score = round(hits / len(comments), 3)
            except Exception as e:
                logger.warning(f"Comment fetch failed for {top[0]['id']}: {e}")

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
            top_video_views=max_views,
            engagement_rate=round(engagement_rate, 4),
            unique_creators=unique_creators,
            max_views=max_views,
            breakout_ratio=breakout_ratio,
            review_intent_ratio=review_intent_ratio,
            purchase_intent_score=purchase_intent_score,
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
            top_video_views=m.get("top_video_views", 0),
            engagement_rate=m.get("engagement_rate", 0.0),
            unique_creators=m.get("unique_creators", 0),
            max_views=m.get("max_views", 0),
            breakout_ratio=m.get("breakout_ratio", 0.0),
            review_intent_ratio=m.get("review_intent_ratio", 0.0),
            purchase_intent_score=m.get("purchase_intent_score", 0.0),
        )

    def _save(self, brand_name: str, metrics: PlatformMetrics):
        upsert_metrics(brand_name, "youtube", metrics.to_dict(), data_source="live_api")
        log_collection(brand_name, "youtube", "success", data_source="live_api")
