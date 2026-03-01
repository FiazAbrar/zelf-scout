import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scoring.scorer import ICPScorer


def make_brand(name, category, platforms):
    return {"brand_name": name, "category": category, "platforms": platforms}


def make_platform_metrics(platform, shorts=10, views=100000, likes=5000,
                          comments=500, followers=50000, source="sample"):
    return {
        "platform": platform,
        "data_source": source,
        "followers": followers,
        "videos_last_90d": shorts,
        "shorts_last_90d": shorts,
        "total_views": views,
        "total_likes": likes,
        "total_comments": comments,
        "avg_views": views // max(shorts, 1),
        "avg_likes": likes // max(shorts, 1),
        "avg_comments": comments // max(shorts, 1),
        "engagement_rate": (likes + comments) / max(views, 1),
    }


class TestICPScorer:
    def setup_method(self):
        self.scorer = ICPScorer()

    def test_scores_within_range(self):
        brands = [
            make_brand("BrandA", "Beauty & Skincare", {
                "youtube": make_platform_metrics("youtube", shorts=50, views=5000000),
            }),
            make_brand("BrandB", "Household", {
                "youtube": make_platform_metrics("youtube", shorts=5, views=50000),
            }),
            make_brand("BrandC", "Food & Snacks", {
                "youtube": make_platform_metrics("youtube", shorts=20, views=500000),
            }),
        ]

        df = self.scorer.score_brands(brands)

        assert len(df) == 3
        for _, row in df.iterrows():
            assert 0 <= row["icp_score"] <= 100
            assert 0 <= row["video_volume_score"] <= 30
            assert 0 <= row["engagement_scale_score"] <= 30
            assert 0 <= row["engagement_rate_score"] <= 25
            assert 0 <= row["category_fit_score"] <= 15

    def test_more_active_brand_scores_higher(self):
        brands = [
            make_brand("Active", "Beauty & Skincare", {
                "youtube": make_platform_metrics("youtube", shorts=100, views=10000000, likes=500000),
            }),
            make_brand("Inactive", "Other CPG", {
                "youtube": make_platform_metrics("youtube", shorts=2, views=1000, likes=10),
            }),
        ]

        df = self.scorer.score_brands(brands)
        active_score = df[df["brand_name"] == "Active"]["icp_score"].iloc[0]
        inactive_score = df[df["brand_name"] == "Inactive"]["icp_score"].iloc[0]
        assert active_score > inactive_score

    def test_category_fit_scoring(self):
        brands = [
            make_brand("BeautyBrand", "Beauty & Skincare", {
                "youtube": make_platform_metrics("youtube"),
            }),
            make_brand("OtherBrand", "Other CPG", {
                "youtube": make_platform_metrics("youtube"),
            }),
        ]

        df = self.scorer.score_brands(brands)
        beauty_fit = df[df["brand_name"] == "BeautyBrand"]["category_fit_score"].iloc[0]
        other_fit = df[df["brand_name"] == "OtherBrand"]["category_fit_score"].iloc[0]
        assert beauty_fit > other_fit
        assert beauty_fit == 15.0  # 1.0 * 15
        assert other_fit == 4.5   # 0.3 * 15

    def test_empty_input(self):
        df = self.scorer.score_brands([])
        assert df.empty

    def test_unavailable_platforms_ignored(self):
        brands = [
            make_brand("PartialBrand", "Food & Snacks", {
                "youtube": make_platform_metrics("youtube"),
                "tiktok": {"data_source": "unavailable"},
            }),
        ]

        df = self.scorer.score_brands(brands)
        assert df.iloc[0]["platforms_active"] == 1

    def test_rank_assignment(self):
        brands = [
            make_brand(f"Brand{i}", "Food & Snacks", {
                "youtube": make_platform_metrics("youtube", shorts=i * 10, views=i * 100000),
            })
            for i in range(1, 6)
        ]

        df = self.scorer.score_brands(brands)
        assert list(df["rank"]) == [1, 2, 3, 4, 5]
        assert df.iloc[0]["icp_score"] >= df.iloc[1]["icp_score"]
