from config import (
    SCORING_WEIGHTS,
    CATEGORY_FIT,
    INTENT_ABSENT_SCORE_CAP,
)


class ICPScorer:
    """Scores brands on Zelf ICP-readiness (0–100) across 4 dimensions.

    Dimensions:
      creator_reach     (30 pts) — total views on creator content; percentile-based
      creator_ecosystem (25 pts) — unique creator count (percentile)
      content_intent    (25 pts) — review keyword ratio; percentile-based
      category_fit      (20 pts) — static Zelf ICP alignment; absolute lookup

    Scoring philosophy:
      - reach, ecosystem, and intent are percentile-based: brands ranked against each other.
      - category_fit is absolute: static Zelf ICP alignment lookup.
      - Intent gate: if a brand has zero review intent, score is capped at INTENT_ABSENT_SCORE_CAP.
    """

    def __init__(self):
        self.weights = SCORING_WEIGHTS

    def score_brands(self, brand_data: list[dict]) -> list[dict]:
        """Score all brands. Returns list of dicts sorted by icp_score descending."""
        if not brand_data:
            return []

        rows = []
        for brand in brand_data:
            agg = self._aggregate_platforms(brand)
            rows.append({
                "brand_name": brand["brand_name"],
                "category":   brand["category"],
                **agg,
            })

        total_views_vals    = [r["total_views"]        for r in rows]
        unique_creator_vals = [r["unique_creators"]     for r in rows]
        review_intent_vals  = [r["review_intent_ratio"] for r in rows]

        w = self.weights
        for r in rows:
            r["creator_reach_score"] = round(
                self._pct_score(total_views_vals, r["total_views"], w["creator_reach"]), 1
            )
            r["creator_ecosystem_score"] = round(
                self._pct_score(unique_creator_vals, r["unique_creators"], w["creator_ecosystem"]), 1
            )
            r["content_intent_score"] = round(
                self._pct_score(review_intent_vals, r["review_intent_ratio"], w["content_intent"]), 1
            )
            r["category_fit_score"] = round(
                CATEGORY_FIT.get(r["category"], 0.3) * w["category_fit"], 1
            )

            raw = (
                r["creator_reach_score"]
                + r["creator_ecosystem_score"]
                + r["content_intent_score"]
                + r["category_fit_score"]
            )
            if r["review_intent_ratio"] == 0:
                raw = min(raw, INTENT_ABSENT_SCORE_CAP)
            r["icp_score"] = round(raw, 1)

        rows.sort(key=lambda r: r["icp_score"], reverse=True)
        for i, r in enumerate(rows):
            r["rank"] = i + 1

        return rows

    # ---------------------------------------------------------------------- #
    # Private helpers                                                         #
    # ---------------------------------------------------------------------- #

    def _aggregate_platforms(self, brand: dict) -> dict:
        """Aggregate metrics across all active platforms for a single brand."""
        platforms = brand.get("platforms", {})
        total_views = total_likes = total_comments = total_videos = active_platforms = 0
        engagement_rates = []
        unique_creators = 0
        review_intent_ratio = purchase_intent_score = 0.0

        for metrics in platforms.values():
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
            unique_creators       = max(unique_creators,       metrics.get("unique_creators", 0))
            review_intent_ratio   = max(review_intent_ratio,   metrics.get("review_intent_ratio", 0.0))
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
            "review_intent_ratio":   review_intent_ratio,
            "purchase_intent_score": purchase_intent_score,
        }

    def _pct_score(self, values: list[float], x: float, max_pts: float) -> float:
        """Rank-style percentile score (0 to max_pts). Equal values share the same score.

        Equivalent to scipy.stats.percentileofscore(values, x, kind="rank") / 100 * max_pts
        but without the dependency. When all values are identical, returns max_pts / 2.
        """
        if not values or max(values) == min(values):
            return max_pts / 2
        n = len(values)
        below = sum(1 for v in values if v < x)
        equal = sum(1 for v in values if v == x)
        return (below + 0.5 * equal) / n * max_pts

