from math import log2

import pandas as pd
from scipy.stats import percentileofscore

from collectors import PlatformMetrics
from config import (
    SCORING_WEIGHTS,
    CATEGORY_FIT,
    INTENT_ABSENT_SCORE_CAP,
    BREAKOUT_BONUS_MAX_PTS,
)


class ICPScorer:
    """Scores brands on Zelf ICP-readiness (0–100) across 4 dimensions.

    Dimensions:
      creator_reach     (30 pts) — total views on creator content; percentile-based
      creator_ecosystem (25 pts) — unique creator count (percentile) + breakout bonus (absolute)
      content_intent    (25 pts) — review keyword ratio + purchase intent score; absolute
      category_fit      (20 pts) — static Zelf ICP alignment; absolute lookup

    Scoring philosophy:
      - reach and ecosystem are percentile-based: they rank brands relative to
        each other, so the distribution is always meaningful regardless of cohort.
      - content_intent is percentile-based: ranks brands relative to each other
        on a composite of review keyword ratio + purchase intent score.
      - category_fit is absolute: static Zelf ICP alignment lookup.
      - Intent gate: if a brand has zero review AND purchase signals, its final
        score is capped at INTENT_ABSENT_SCORE_CAP (default 60). High-volume brands
        with no creator intentionality are not strong Zelf leads.
    """

    def __init__(self):
        self.weights = SCORING_WEIGHTS

    def score_brands(self, brand_data: list[dict]) -> pd.DataFrame:
        """Score all brands from aggregated platform metrics.

        Args:
            brand_data: list of dicts with keys:
                brand_name, category, platforms (dict[platform] -> metrics dict)

        Returns:
            DataFrame sorted by icp_score descending, with rank column.
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

        # --- Creator Reach (percentile-based) ---
        df["creator_reach_score"] = self._percentile_score(
            df["total_views"], self.weights["creator_reach"]
        )

        # --- Creator Ecosystem (percentile base + absolute breakout bonus) ---
        df["creator_ecosystem_score"] = (
            self._percentile_score(df["unique_creators"], max_pts=self.weights["creator_ecosystem"] - BREAKOUT_BONUS_MAX_PTS)
            + df["breakout_ratio"].apply(self._breakout_bonus)
        ).clip(upper=self.weights["creator_ecosystem"])

        # --- Content Intent (percentile-based, review intent only) ---
        # Purchase intent (comments on 1 video) is too noisy to include in scoring.
        # It remains visible in the evidence trail for qualitative context.
        df["content_intent_score"] = self._percentile_score(
            df["review_intent_ratio"], self.weights["content_intent"]
        )

        # --- Category Fit (static lookup) ---
        df["category_fit_score"] = df["category"].map(
            lambda c: CATEGORY_FIT.get(c, 0.3) * self.weights["category_fit"]
        )

        # --- ICP Score ---
        raw_score = (
            df["creator_reach_score"]
            + df["creator_ecosystem_score"]
            + df["content_intent_score"]
            + df["category_fit_score"]
        )

        # Intent gate: brands with zero review intent get capped
        intent_absent = df["review_intent_ratio"] == 0
        df["icp_score"] = raw_score.where(
            ~intent_absent,
            raw_score.clip(upper=INTENT_ABSENT_SCORE_CAP)
        ).round(1)

        # Round sub-scores for display
        for col in ["creator_reach_score", "creator_ecosystem_score",
                    "content_intent_score", "category_fit_score"]:
            df[col] = df[col].round(1)

        df = df.sort_values("icp_score", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        return df

    # ---------------------------------------------------------------------- #
    # Private helpers                                                         #
    # ---------------------------------------------------------------------- #

    def _aggregate_platforms(self, brand: dict) -> dict:
        """Aggregate metrics across all active platforms for a single brand."""
        platforms = brand.get("platforms", {})
        total_views = 0
        total_likes = 0
        total_comments = 0
        total_videos = 0
        active_platforms = 0
        engagement_rates = []

        # Creator ecosystem signals (take max/union across platforms)
        unique_creators = 0
        breakout_ratio = 0.0
        review_intent_ratio = 0.0
        purchase_intent_score = 0.0

        for platform_name, metrics in platforms.items():
            if metrics.get("data_source") == "unavailable":
                continue
            active_platforms += 1

            total_views    += metrics.get("total_views", 0)
            total_likes    += metrics.get("total_likes", 0)
            total_comments += metrics.get("total_comments", 0)
            total_videos   += metrics.get("videos_last_90d", 0)

            er = metrics.get("engagement_rate", 0.0)
            if er > 0:
                engagement_rates.append(er)

            # Ecosystem signals: take the platform-level values
            # (currently single-platform; extend naturally when more platforms added)
            unique_creators      = max(unique_creators,      metrics.get("unique_creators", 0))
            breakout_ratio       = max(breakout_ratio,       metrics.get("breakout_ratio", 0.0))
            review_intent_ratio  = max(review_intent_ratio,  metrics.get("review_intent_ratio", 0.0))
            purchase_intent_score = max(purchase_intent_score, metrics.get("purchase_intent_score", 0.0))

        avg_er = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0.0

        return {
            "platforms_active":      active_platforms,
            "total_views":           total_views,
            "total_likes":           total_likes,
            "total_comments":        total_comments,
            "total_videos":          total_videos,
            "avg_engagement_rate":   avg_er,
            "unique_creators":       unique_creators,
            "breakout_ratio":        breakout_ratio,
            "review_intent_ratio":   review_intent_ratio,
            "purchase_intent_score": purchase_intent_score,
        }

    def _percentile_score(self, series: pd.Series, max_pts: float) -> pd.Series:
        """Convert raw values to percentile-based scores (0 to max_pts).

        Brands at equal values share the same percentile. When all values are
        identical, every brand gets max_pts / 2 (mid-point, not zero).
        """
        if series.max() == series.min():
            return pd.Series([max_pts / 2] * len(series), index=series.index)
        return series.apply(
            lambda x: percentileofscore(series, x, kind="rank") / 100 * max_pts
        )

    def _breakout_bonus(self, breakout_ratio: float) -> float:
        """Log-scaled bonus points for viral potential (0 to BREAKOUT_BONUS_MAX_PTS).

        A breakout_ratio of 1 (flat, no outlier) → 0 pts.
        A breakout_ratio of 8 (one video 8× the average) → ~3 pts.
        A breakout_ratio of 64+ → capped at BREAKOUT_BONUS_MAX_PTS.
        """
        if breakout_ratio <= 1:
            return 0.0
        return min(log2(breakout_ratio) / 3 * BREAKOUT_BONUS_MAX_PTS, BREAKOUT_BONUS_MAX_PTS)
