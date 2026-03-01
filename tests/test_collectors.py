import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from collectors import PlatformMetrics


class TestPlatformMetrics:
    def test_to_dict(self):
        m = PlatformMetrics(
            platform="youtube",
            brand_name="TestBrand",
            followers=10000,
            videos_last_90d=20,
            shorts_last_90d=15,
            total_views=500000,
            total_likes=25000,
            total_comments=3000,
            data_source="live_api",
        )
        d = m.to_dict()
        assert d["platform"] == "youtube"
        assert d["brand_name"] == "TestBrand"
        assert d["followers"] == 10000
        assert d["total_views"] == 500000
        assert d["data_source"] == "live_api"

    def test_is_available(self):
        available = PlatformMetrics(platform="tiktok", brand_name="Test", data_source="sample")
        unavailable = PlatformMetrics(platform="tiktok", brand_name="Test", data_source="unavailable")
        assert available.is_available is True
        assert unavailable.is_available is False

    def test_default_values(self):
        m = PlatformMetrics(platform="instagram", brand_name="Test")
        assert m.followers == 0
        assert m.total_views == 0
        assert m.engagement_rate == 0.0
        assert m.data_source == "unavailable"
        assert m.error is None


