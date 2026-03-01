import json
import logging
import os

from collectors import PlatformMetrics
from config import SAMPLE_DIR
from database.db import get_metrics, upsert_metrics, log_collection

logger = logging.getLogger(__name__)

TIKTOK_SAMPLE_PATH = SAMPLE_DIR / "tiktok_sample.json"


class TikTokCollector:
    """TikTok collector — sample data fallback only.

    Live TikTok collection is not implemented (bot detection blocks all
    headless/HTTP approaches). Reserved for future implementation.
    Fallback chain: SQLite cache → sample JSON → unavailable
    """

    def __init__(self, ms_token: str = None):
        self._sample_data = None

    @property
    def sample_data(self) -> dict:
        if self._sample_data is None:
            if TIKTOK_SAMPLE_PATH.exists():
                with open(TIKTOK_SAMPLE_PATH) as f:
                    self._sample_data = json.load(f)
            else:
                self._sample_data = {}
        return self._sample_data

    def collect(self, brand_name: str, handle: str,
                use_cache: bool = True) -> PlatformMetrics:
        # Tier 1: SQLite cache
        if use_cache:
            cached = get_metrics(brand_name, "tiktok")
            if cached:
                return self._metrics_from_dict(brand_name, cached["metrics"], "cache")

        # Tier 2: Sample data
        if handle in self.sample_data:
            sample = self.sample_data[handle]
            metrics = self._metrics_from_sample(brand_name, sample)
            upsert_metrics(brand_name, "tiktok", metrics.to_dict(), data_source="sample")
            log_collection(brand_name, "tiktok", "success", data_source="sample")
            return metrics

        # Tier 3: Unavailable
        log_collection(brand_name, "tiktok", "unavailable")
        return PlatformMetrics(
            platform="tiktok", brand_name=brand_name,
            data_source="unavailable", error="No data available",
        )

    def _metrics_from_sample(self, brand_name: str, sample: dict) -> PlatformMetrics:
        count = sample.get("videos_last_90d", 0)
        total_views = sample.get("avg_views", 0) * count
        total_likes = sample.get("avg_likes", 0) * count
        total_comments = sample.get("avg_comments", 0) * count
        engagement_rate = 0.0
        if total_views > 0:
            engagement_rate = (total_likes + total_comments) / total_views

        return PlatformMetrics(
            platform="tiktok",
            brand_name=brand_name,
            data_source="sample",
            followers=sample.get("followers", 0),
            videos_last_90d=count,
            shorts_last_90d=sample.get("shorts_last_90d", count),
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            total_shares=sample.get("avg_shares", 0) * count,
            avg_views=sample.get("avg_views", 0),
            avg_likes=sample.get("avg_likes", 0),
            avg_comments=sample.get("avg_comments", 0),
            top_video_views=sample.get("top_video_views", 0),
            engagement_rate=round(engagement_rate, 4),
        )

    def _metrics_from_dict(self, brand_name: str, m: dict, source: str) -> PlatformMetrics:
        return PlatformMetrics(
            platform="tiktok",
            brand_name=brand_name,
            data_source=source,
            followers=m.get("followers", 0),
            videos_last_90d=m.get("videos_last_90d", 0),
            shorts_last_90d=m.get("shorts_last_90d", 0),
            total_views=m.get("total_views", 0),
            total_likes=m.get("total_likes", 0),
            total_comments=m.get("total_comments", 0),
            total_shares=m.get("total_shares", 0),
            avg_views=m.get("avg_views", 0),
            avg_likes=m.get("avg_likes", 0),
            avg_comments=m.get("avg_comments", 0),
            top_video_views=m.get("top_video_views", 0),
            engagement_rate=m.get("engagement_rate", 0.0),
        )
