"""Seed the SQLite cache by collecting YouTube creator data for all brands.

Run once to build the cache — the dashboard then loads instantly.
Uses yt-dlp, so no API key or quota limits.

Usage:
    python scripts/seed_cache.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from config import BRANDS_CSV
from database.db import init_db
from collectors.youtube import YouTubeCollector
from scoring.scorer import ICPScorer
from database.db import upsert_scores


def main():
    print("Initializing database...")
    init_db()

    brands_df = pd.read_csv(BRANDS_CSV)
    print(f"Found {len(brands_df)} brands in {BRANDS_CSV}")

    yt = YouTubeCollector()
    brand_data = []

    for i, (_, row) in enumerate(brands_df.iterrows()):
        brand = row["brand_name"]
        print(f"[{i + 1}/{len(brands_df)}] Collecting: {brand}")

        yt_metrics = yt.collect(brand, use_cache=True)

        platforms = {}
        if yt_metrics.is_available:
            platforms[yt_metrics.platform] = yt_metrics.to_dict()

        brand_data.append({
            "brand_name": brand,
            "category": row["category"],
            "platforms": platforms,
        })

        print(f"  youtube={yt_metrics.data_source} | videos={yt_metrics.videos_last_90d} | views={yt_metrics.total_views:,}")

    # Score all brands
    print("\nScoring brands...")
    scorer = ICPScorer()
    scores_df = scorer.score_brands(brand_data)

    if not scores_df.empty:
        score_records = []
        for _, r in scores_df.iterrows():
            score_records.append({
                "brand_name": r["brand_name"],
                "category": r["category"],
                "icp_score": r["icp_score"],
                "video_volume_score": r["video_volume_score"],
                "engagement_scale_score": r["engagement_scale_score"],
                "engagement_rate_score": r["engagement_rate_score"],
                "category_fit_score": r["category_fit_score"],
                "platforms_active": r["platforms_active"],
                "total_videos": r["total_videos"],
                "total_views": r["total_views"],
                "total_likes": r["total_likes"],
                "total_comments": r["total_comments"],
            })
        upsert_scores(score_records)

    print("\n--- Top 10 Leads ---")
    for _, r in scores_df.head(10).iterrows():
        print(f"  {r['rank']:>2}. {r['brand_name']:<20} {r['icp_score']:>5.1f}  ({r['category']})")

    print(f"\nDone! Cache saved to zelf_cache.db")
    print(f"Total brands scored: {len(scores_df)}")


if __name__ == "__main__":
    main()
