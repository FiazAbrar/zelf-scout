from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformMetrics:
    """Unified return type for all collectors."""
    platform: str
    brand_name: str
    followers: int = 0
    videos_last_90d: int = 0
    shorts_last_90d: int = 0
    total_views: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    avg_views: int = 0
    avg_likes: int = 0
    avg_comments: int = 0
    top_video_views: int = 0
    engagement_rate: float = 0.0
    data_source: str = "unavailable"  # "live_api", "cache", "sample", "unavailable"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "brand_name": self.brand_name,
            "followers": self.followers,
            "videos_last_90d": self.videos_last_90d,
            "shorts_last_90d": self.shorts_last_90d,
            "total_views": self.total_views,
            "total_likes": self.total_likes,
            "total_comments": self.total_comments,
            "total_shares": self.total_shares,
            "avg_views": self.avg_views,
            "avg_likes": self.avg_likes,
            "avg_comments": self.avg_comments,
            "top_video_views": self.top_video_views,
            "engagement_rate": self.engagement_rate,
            "data_source": self.data_source,
        }

    @property
    def is_available(self) -> bool:
        return self.data_source != "unavailable"
