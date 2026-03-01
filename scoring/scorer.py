import pandas as pd
from scipy.stats import percentileofscore

from collectors import PlatformMetrics
from config import SCORING_WEIGHTS, CATEGORY_FIT


class ICPScorer:
    """Scores brands on Zelf ICP-readiness (0-100) across 5 dimensions."""

    def __init__(self):
        self.weights = SCORING_WEIGHTS

    def score_brands(self, brand_data: list[dict]) -> pd.DataFrame:
        """Score all brands from aggregated platform metrics.

        Args:
            brand_data: list of dicts, each with:
                - brand_name, category
                - platforms: dict[platform_name] -> PlatformMetrics.to_dict()

        Returns:
            DataFrame with scores, sorted by icp_score descending.
        """
        rows = []
        for brand in brand_data:
            agg = self._aggregate_platforms(brand)
            rows.append({
                "brand_name": brand["brand_name"],
                "category": brand["category"],
                **agg,
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        # Compute percentile-based scores
        df["video_volume_score"] = self._percentile_score(
            df["total_shorts"], self.weights["video_volume"]
        )
        df["engagement_scale_score"] = self._percentile_score(
            df["total_engagement"], self.weights["engagement_scale"]
        )
        df["engagement_rate_score"] = self._percentile_score(
            df["avg_engagement_rate"], self.weights["engagement_rate"]
        )
        df["category_fit_score"] = df["category"].map(
            lambda c: CATEGORY_FIT.get(c, 0.3) * self.weights["category_fit"]
        )

        # Total ICP score
        df["icp_score"] = (
            df["video_volume_score"]
            + df["engagement_scale_score"]
            + df["engagement_rate_score"]
            + df["category_fit_score"]
        ).round(1)

        # Round sub-scores
        for col in ["video_volume_score", "engagement_scale_score",
                     "engagement_rate_score", "category_fit_score"]:
            df[col] = df[col].round(1)

        df = df.sort_values("icp_score", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        return df

    def _aggregate_platforms(self, brand: dict) -> dict:
        """Aggregate metrics across all platforms for a single brand."""
        platforms = brand.get("platforms", {})
        total_shorts = 0
        total_views = 0
        total_likes = 0
        total_comments = 0
        total_videos = 0
        active_platforms = 0
        engagement_rates = []

        for platform_name, metrics in platforms.items():
            if metrics.get("data_source") == "unavailable":
                continue
            active_platforms += 1
            shorts = metrics.get("shorts_last_90d", 0)
            views = metrics.get("total_views", 0)
            likes = metrics.get("total_likes", 0)
            comments = metrics.get("total_comments", 0)
            videos = metrics.get("videos_last_90d", 0)

            total_shorts += shorts
            total_views += views
            total_likes += likes
            total_comments += comments
            total_videos += videos

            er = metrics.get("engagement_rate", 0.0)
            if er > 0:
                engagement_rates.append(er)

        avg_er = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0.0

        return {
            "platforms_active": active_platforms,
            "total_shorts": total_shorts,
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_videos": total_videos,
            "total_engagement": total_views + total_likes + total_comments,
            "avg_engagement_rate": avg_er,
        }

    def _percentile_score(self, series: pd.Series, max_points: float) -> pd.Series:
        """Convert raw values to percentile-based scores (0 to max_points)."""
        if series.max() == series.min():
            return pd.Series([max_points / 2] * len(series), index=series.index)
        return series.apply(
            lambda x: percentileofscore(series, x, kind="rank") / 100 * max_points
        )
