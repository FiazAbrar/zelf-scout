"""Discover CPG brands organically from YouTube video titles.

Searches YouTube with category-specific queries, extracts brand candidates
from video titles by frequency, deduplicates across categories, and writes
data/discovered_brands.csv.

Usage:
    python scripts/discover_brands.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
from collections import defaultdict

import pandas as pd

from config import (
    DATA_DIR,
    DISCOVERY_QUERIES,
    DISCOVERY_MIN_MENTIONS,
    DISCOVERY_MAX_BRANDS_PER_CATEGORY,
)
from collectors.discovery import DiscoveryCollector

OUTPUT_CSV = DATA_DIR / "discovered_brands.csv"
SEED_CSV   = DATA_DIR / "brands_seed.csv"


def _load_seed_brands() -> dict[str, str]:
    """Return {brand_name: category} from the seed CSV."""
    try:
        df = pd.read_csv(SEED_CSV)
        return dict(zip(df["brand_name"], df["category"]))
    except Exception:
        return {}


def main() -> None:
    collector = DiscoveryCollector()

    # {category: {brand: mention_count}}
    category_results: dict[str, dict[str, int]] = {}

    for category, queries in DISCOVERY_QUERIES.items():
        print(f"\nDiscovering: {category} ({len(queries)} queries)...")
        raw = collector.collect_category(category, queries)

        # LLM already returns only real brands; apply minimum mention threshold
        filtered = {b: c for b, c in raw.items() if c >= DISCOVERY_MIN_MENTIONS}
        category_results[category] = filtered
        print(f"  {len(raw)} brands from LLM → {len(filtered)} above threshold (≥{DISCOVERY_MIN_MENTIONS} mentions)")

    # Cross-category dedup: assign brand to category with highest mention count
    brand_best: dict[str, tuple[str, int]] = {}  # brand → (category, count)
    for category, brands in category_results.items():
        for brand, count in brands.items():
            if brand not in brand_best or count > brand_best[brand][1]:
                brand_best[brand] = (category, count)

    # Rebuild per-category lists respecting DISCOVERY_MAX_BRANDS_PER_CATEGORY
    final: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for brand, (category, count) in brand_best.items():
        final[category].append((brand, count))

    for category in final:
        final[category].sort(key=lambda x: x[1], reverse=True)
        final[category] = final[category][:DISCOVERY_MAX_BRANDS_PER_CATEGORY]

    # Fall back to seed brands for categories with too few results
    seed_brands = _load_seed_brands()
    for category in DISCOVERY_QUERIES:
        discovered_count = len(final.get(category, []))
        if discovered_count < 3:
            print(f"\n  [{category}] Only {discovered_count} brands found — falling back to seed brands.")
            seed_for_cat = [(b, 0) for b, c in seed_brands.items() if c == category]
            existing = {b for b, _ in final.get(category, [])}
            for brand, count in seed_for_cat:
                if brand not in existing:
                    final[category].append((brand, count))

    # Write CSV
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for category, brands in final.items():
        for brand, _ in brands:
            rows.append({"brand_name": brand, "category": category})

    rows.sort(key=lambda r: (r["category"], r["brand_name"]))

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["brand_name", "category"])
        writer.writeheader()
        writer.writerows(rows)

    # Print summary table
    total = len(rows)
    print(f"\n{'='*55}")
    print(f"  Discovered brands written to: {OUTPUT_CSV}")
    print(f"  Total brands: {total}")
    print(f"{'='*55}")
    print(f"  {'Category':<25} {'Brands':>6}")
    print(f"  {'-'*35}")
    for category in sorted(final):
        count = len(final[category])
        print(f"  {category:<25} {count:>6}")
    print(f"  {'-'*35}")
    print(f"  {'TOTAL':<25} {total:>6}")
    print(f"{'='*55}")

    print("\nSample (first 10):")
    for row in rows[:10]:
        print(f"  {row['brand_name']:<25} {row['category']}")


if __name__ == "__main__":
    main()
