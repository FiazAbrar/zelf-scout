"""Collect fresh YouTube metrics for all brands in BRANDS_CSV.

Usage:
    python scripts/collect.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from config import BRANDS_CSV
from collectors.youtube import YouTubeCollector


def main() -> None:
    df = pd.read_csv(BRANDS_CSV)
    yt = YouTubeCollector()
    print(f"Collecting {len(df)} brands...\n")

    for i, row in df.iterrows():
        brand = row["brand_name"]
        category = row.get("category", "")
        print(f"[{i+1}/{len(df)}] {brand}", end="", flush=True)
        try:
            m = yt.collect(brand, use_cache=False, category=category)
            print(f"  {m.total_views:>14,} views  {m.unique_creators:>3} creators")
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nDone. Restart the dashboard to see updated scores.")


if __name__ == "__main__":
    main()
