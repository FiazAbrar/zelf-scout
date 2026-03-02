# Zelf ICP Lead Scorer

A Streamlit dashboard that discovers and ranks CPG brands by their **creator video ecosystem** — the strongest signal for whether a brand needs [Zelf](https://www.hellozelf.com/).

**The insight**: Brands with large creator communities (people making videos *about* them) have the most to gain from Zelf's AI-powered social video intelligence. This tool surfaces those brands from YouTube data — no CRM, no manual research.

**No API keys. No quota limits. Runs unlimited times.**
Data is collected via [yt-dlp](https://github.com/yt-dlp/yt-dlp), which searches YouTube directly without the Data API.

---

## How it works

```
brands.csv (name + category)
    ↓
YouTubeCollector (yt-dlp)
    ├── Flat search  → top 50 creator videos, view counts  (1 fast request/brand)
    └── Full fetch   → top 5 by views, likes + comments    (5 requests/brand)
    ↓
SQLite cache  (zelf_cache.db — persists between runs)
    ↓
ICPScorer     (4 dimensions → ICP Score 0–100)
    ↓
Streamlit dashboard  (ranked table + charts + brand deep dive)
```

The YouTube search returns videos *about* each brand — creator reviews, hauls, taste tests, routines — not the brand's own channel content. That's the signal: how much organic creator interest exists around this brand.

---

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Seed the cache (collects live YouTube data — takes ~10 min for 50 brands)
python scripts/seed_cache.py

# 3. Launch dashboard
streamlit run app.py
```

The seed script only needs to run once. After that, the dashboard loads from the SQLite cache instantly. Use the **Refresh Data** button in the sidebar to re-collect.

---

## Scoring methodology — ICP Score (0–100)

| Dimension | Max | What it measures | Method |
|-----------|-----|-----------------|--------|
| **Video Volume** | 30 pts | Count of creator videos about this brand (90 days) | Percentile rank |
| **Engagement Scale** | 30 pts | Total views + likes + comments across creator content | Percentile rank |
| **Engagement Rate** | 25 pts | (likes + comments) / views on top 5 creator videos | Percentile rank |
| **Category Fit** | 15 pts | How aligned the brand's category is with Zelf's ICP | Fixed multiplier |

Percentile-based scoring produces a clean 0–100 distribution regardless of dataset composition and is robust to outliers. A brand at the 90th percentile on video volume scores 27/30 on that dimension.

### Category fit multipliers

| Category | Multiplier |
|----------|-----------|
| Beauty & Skincare | 1.0 (15 pts) |
| Food & Snacks | 1.0 (15 pts) |
| Personal Care | 1.0 (15 pts) |
| Beverage | 0.8 (12 pts) |
| Household | 0.6 (9 pts) |
| Pet Care | 0.4 (6 pts) |
| Other CPG | 0.3 (4.5 pts) |

---

## Dashboard features

- **Ranked table** — color-coded ICP scores, tier labels (Hot Lead / Warm / Low Priority), sub-score breakdown, CSV export
- **Filters** — category, ICP score range
- **Charts** — score distribution, category comparison, sub-score heatmap, top 10 bar chart
- **Brand deep dive** — radar chart, key metrics, per-video engagement data, auto-generated "Why this brand needs Zelf" pitch blurb

---

## Project structure

```
zelf/
├── app.py                  # Streamlit dashboard
├── config.py               # Scoring weights, collection settings
├── data/
│   └── brands.csv          # 50 CPG brands (name + category)
├── collectors/
│   ├── __init__.py         # PlatformMetrics dataclass
│   └── youtube.py          # yt-dlp collector (hybrid flat+full strategy)
├── scoring/
│   └── scorer.py           # ICP scoring engine (percentile-based)
├── database/
│   └── db.py               # SQLite operations (metrics + scores cache)
├── utils/
│   └── helpers.py          # Formatting, score colors, pitch blurb generator
├── scripts/
│   └── seed_cache.py       # One-time cache builder
└── tests/
    └── test_scorer.py      # pytest suite for scoring logic
```

---

## Running tests

```bash
pytest tests/ -v
```
