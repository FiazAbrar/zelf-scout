import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scoring.scorer import ICPScorer
from config import INTENT_ABSENT_SCORE_CAP


def make_brand(name, category, platforms):
    return {"brand_name": name, "category": category, "platforms": platforms}


def make_platform_metrics(
    platform, shorts=10, views=100000, likes=5000, comments=500,
    followers=50000, source="sample",
    unique_creators=8,
    review_intent_ratio=0.4, purchase_intent_score=0.2,
):
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
        "unique_creators": unique_creators,
        "review_intent_ratio": review_intent_ratio,
        "purchase_intent_score": purchase_intent_score,
    }


def _find(rows, name):
    return next(r for r in rows if r["brand_name"] == name)


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

        rows = self.scorer.score_brands(brands)

        assert len(rows) == 3
        for row in rows:
            assert 0 <= row["icp_score"] <= 100
            assert 0 <= row["creator_reach_score"] <= 30
            assert 0 <= row["creator_ecosystem_score"] <= 25
            assert 0 <= row["content_intent_score"] <= 25
            assert 0 <= row["category_fit_score"] <= 20

    def test_more_active_brand_scores_higher(self):
        brands = [
            make_brand("Active", "Beauty & Skincare", {
                "youtube": make_platform_metrics(
                    "youtube", shorts=100, views=10000000, likes=500000,
                    unique_creators=40, review_intent_ratio=0.7,
                ),
            }),
            make_brand("Inactive", "Other CPG", {
                "youtube": make_platform_metrics(
                    "youtube", shorts=2, views=1000, likes=10,
                    unique_creators=1, review_intent_ratio=0.0, purchase_intent_score=0.0,
                ),
            }),
        ]

        rows = self.scorer.score_brands(brands)
        assert _find(rows, "Active")["icp_score"] > _find(rows, "Inactive")["icp_score"]

    def test_category_fit_scoring(self):
        brands = [
            make_brand("BeautyBrand", "Beauty & Skincare", {
                "youtube": make_platform_metrics("youtube"),
            }),
            make_brand("OtherBrand", "Other CPG", {
                "youtube": make_platform_metrics("youtube"),
            }),
        ]

        rows = self.scorer.score_brands(brands)
        beauty_fit = _find(rows, "BeautyBrand")["category_fit_score"]
        other_fit = _find(rows, "OtherBrand")["category_fit_score"]
        assert beauty_fit > other_fit
        assert beauty_fit == 20.0   # 1.0 × 20
        assert other_fit == 6.0    # 0.3 × 20

    def test_empty_input(self):
        rows = self.scorer.score_brands([])
        assert rows == []

    def test_unavailable_platforms_ignored(self):
        brands = [
            make_brand("PartialBrand", "Food & Snacks", {
                "youtube": make_platform_metrics("youtube"),
                "tiktok": {"data_source": "unavailable"},
            }),
        ]

        rows = self.scorer.score_brands(brands)
        assert rows[0]["platforms_active"] == 1

    def test_rank_assignment(self):
        brands = [
            make_brand(f"Brand{i}", "Food & Snacks", {
                "youtube": make_platform_metrics(
                    "youtube", shorts=i * 10, views=i * 100000,
                    unique_creators=i * 3,
                ),
            })
            for i in range(1, 6)
        ]

        rows = self.scorer.score_brands(brands)
        assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]
        assert rows[0]["icp_score"] >= rows[1]["icp_score"]

    def test_intent_gate_caps_score(self):
        """Brands with zero review and purchase intent should not exceed INTENT_ABSENT_SCORE_CAP."""
        brands = [
            make_brand("NoIntent", "Beauty & Skincare", {
                "youtube": make_platform_metrics(
                    "youtube", views=50000000, unique_creators=100,
                    review_intent_ratio=0.0, purchase_intent_score=0.0,
                ),
            }),
        ]
        rows = self.scorer.score_brands(brands)
        assert rows[0]["icp_score"] <= INTENT_ABSENT_SCORE_CAP

    def test_high_intent_can_exceed_cap(self):
        """Brands with real intent signals should be able to score above the cap."""
        brands = [
            make_brand("WithIntent", "Beauty & Skincare", {
                "youtube": make_platform_metrics(
                    "youtube", views=5000000, unique_creators=30,
                    review_intent_ratio=0.6, purchase_intent_score=0.3,
                ),
            }),
            make_brand("LowBase", "Other CPG", {
                "youtube": make_platform_metrics(
                    "youtube", views=1000, unique_creators=1,
                    review_intent_ratio=0.5, purchase_intent_score=0.1,
                ),
            }),
        ]
        rows = self.scorer.score_brands(brands)
        assert _find(rows, "WithIntent")["icp_score"] > INTENT_ABSENT_SCORE_CAP

    def test_creator_diversity_matters(self):
        """Same views but more unique creators should score higher on ecosystem."""
        brands = [
            make_brand("Organic", "Food & Snacks", {
                "youtube": make_platform_metrics(
                    "youtube", views=1000000, unique_creators=40,
                    review_intent_ratio=0.4, purchase_intent_score=0.1,
                ),
            }),
            make_brand("Concentrated", "Food & Snacks", {
                "youtube": make_platform_metrics(
                    "youtube", views=1000000, unique_creators=2,
                    review_intent_ratio=0.4, purchase_intent_score=0.1,
                ),
            }),
        ]
        rows = self.scorer.score_brands(brands)
        assert _find(rows, "Organic")["creator_ecosystem_score"] > _find(rows, "Concentrated")["creator_ecosystem_score"]
