import json
import logging
from pathlib import Path

from collectors import PlatformMetrics
from config import SAMPLE_DIR
from database.db import get_metrics, upsert_metrics, log_collection

logger = logging.getLogger(__name__)

INSTAGRAM_SAMPLE_PATH = SAMPLE_DIR / "instagram_sample.json"


class InstagramCollector:
    """Collects Instagram Reels metrics from sample data only.
    Instagram has no free public API for Reels metrics.
    Fallback: cache → sample JSON → unavailable.
    """

    def __init__(self):
        self._sample_data = None

    @property
    def sample_data(self) -> dict:
        if self._sample_data is None:
            if INSTAGRAM_SAMPLE_PATH.exists():
                with open(INSTAGRAM_SAMPLE_PATH) as f:
                    self._sample_data = json.load(f)
            else:
                self._sample_data = {}
        return self._sample_data

    def collect(self, brand_name: str, handle: str,
                use_cache: bool = True) -> PlatformMetrics:
        # Try cache first
        if use_cache:
            cached = get_metrics(brand_name, "instagram")
            if cached:
                m = cached["metrics"]
                return self._metrics_from_dict(brand_name, m, "cache")

        # Try sample data
        if handle in self.sample_data:
            sample = self.sample_data[handle]
            metrics = self._metrics_from_sample(brand_name, sample)
            upsert_metrics(brand_name, "instagram", metrics.to_dict(), data_source="sample")
            log_collection(brand_name, "instagram", "success", data_source="sample")
            return metrics

        # Unavailable
        log_collection(brand_name, "instagram", "unavailable")
        return PlatformMetrics(
            platform="instagram", brand_name=brand_name,
            data_source="unavailable", error="No data available",
        )

    def _metrics_from_sample(self, brand_name: str, sample: dict) -> PlatformMetrics:
        reels = sample.get("reels_last_90d", 0)
        total_views = sample.get("avg_reel_views", 0) * reels
        total_likes = sample.get("avg_reel_likes", 0) * reels
        total_comments = sample.get("avg_reel_comments", 0) * reels
        engagement_rate = 0.0
        if total_views > 0:
            engagement_rate = (total_likes + total_comments) / total_views

        return PlatformMetrics(
            platform="instagram",
            brand_name=brand_name,
            data_source="sample",
            followers=sample.get("followers", 0),
            videos_last_90d=sample.get("posts_last_90d", 0),
            shorts_last_90d=reels,
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            avg_views=sample.get("avg_reel_views", 0),
            avg_likes=sample.get("avg_reel_likes", 0),
            avg_comments=sample.get("avg_reel_comments", 0),
            top_video_views=sample.get("top_reel_views", 0),
            engagement_rate=round(engagement_rate, 4),
        )

    def _metrics_from_dict(self, brand_name: str, m: dict,
                           source: str) -> PlatformMetrics:
        return PlatformMetrics(
            platform="instagram",
            brand_name=brand_name,
            data_source=source,
            followers=m.get("followers", 0),
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
        )
