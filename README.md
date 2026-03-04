# Brand Signal

Ranks CPG brands by organic YouTube creator activity — built to identify warm leads for [Zelf](https://www.hellozelf.com/).

**The idea:** brands with lots of independent creators making videos about them already have an engaged audience that Zelf can activate. This tool finds those brands from YouTube data and scores them — no CRM, no manual research.

---

## What it does

1. **Discovers brands** by searching YouTube for category-specific queries ("skincare routine review", "snack haul taste test") and extracting brand names from video titles using an LLM
2. **Collects signals** for each brand via `yt-dlp` — no API key, no quota, runs unlimited times
3. **Scores brands 0–100** across four dimensions and ranks them in a Streamlit dashboard

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Add your SambaNova API key (free at cloud.sambanova.ai)
echo "SAMBANOVA_API_KEY=your_key_here" > .env

# Collect YouTube data for all brands (~45 min for 86 brands)
python scripts/collect.py

# Launch dashboard
streamlit run app.py
```

If you skip collection, the committed `zelf_cache.db` has pre-collected data ready to go.

---

## Scoring — ICP Score (0–100)

| Dimension | Weight | Signal | Method |
|---|---|---|---|
| **Creator Reach** | 30 pts | Total views on creator content (90 days) | Percentile vs. cohort |
| **Creator Ecosystem** | 25 pts | Unique creator count | Percentile vs. cohort |
| **Content Intent** | 25 pts | % of video titles with review/haul keywords | Percentile vs. cohort |
| **Category Fit** | 20 pts | Zelf ICP alignment by category | Fixed multiplier |

**Percentile-based** means brands are ranked against each other, not against an absolute scale. A brand at the 80th percentile on reach scores 24/30 on that dimension.

**Intent gate:** if a brand has zero review-keyword titles (creators mention it incidentally, but no one is actively reviewing it), the final score is capped at 60. High reach with no creator intentionality is not a Zelf lead.

**Breakout bonus:** up to 5 extra points if one video significantly outperforms the average (log-scaled, capped). Signals viral potential in the creator ecosystem.

### Category fit multipliers

| Category | Multiplier | Points |
|---|---|---|
| Beauty & Skincare | 1.0 | 20 |
| Food & Snacks | 1.0 | 20 |
| Personal Care | 1.0 | 20 |
| Beverage | 0.8 | 16 |
| Household | 0.6 | 12 |
| Pet Care | 0.4 | 8 |

---

## How data is collected

For each brand, three steps:

**Step 1 — Flat search** (1 request): searches YouTube sorted by recency, grabs up to 50 creator videos. Extracts view counts, titles, channel names. Skips the brand's own channel.

**Step 2 — Full fetch** (up to 5 requests): fetches the top 5 videos by views individually to get likes, comments, and description.

**Step 3 — Comment fetch** (1 request): pulls 50 comments from the top evidence video to check for purchase-intent language ("bought", "ordering this", "use code"…).

**False positive filtering:** the "evidence video" shown in the dashboard is LLM-validated — the model confirms the video is actually about the brand (not a music video or unrelated content that matched the search). Music videos are caught by title fingerprints before the LLM is even called.

---

## How brands are discovered

Instead of a hand-curated list, brands are discovered from YouTube organically:

```bash
python scripts/discover_brands.py
```

This searches YouTube for category queries, collects video titles, and sends them to Llama 4 Maverick (SambaNova free tier) to extract real CPG brand names by frequency. Results are written to `data/discovered_brands.csv`. The app uses this file automatically; `data/brands_seed.csv` is the fallback if discovery hasn't been run.

---

## Project structure

```
zelf/
├── app.py                      # Streamlit dashboard
├── config.py                   # Weights, keywords, collection settings, discovery queries
├── data/
│   ├── brands_seed.csv         # Hand-curated fallback brand list
│   └── discovered_brands.csv   # Auto-discovered brands (86 brands, 6 categories)
├── collectors/
│   ├── __init__.py             # PlatformMetrics dataclass
│   ├── youtube.py              # yt-dlp collector (flat search + full fetch + comments)
│   └── discovery.py            # Brand discovery collector
├── scoring/
│   └── scorer.py               # ICP scoring engine — pure Python, no pandas
├── database/
│   └── db.py                   # SQLite cache (zelf_cache.db)
├── utils/
│   ├── helpers.py              # Formatting, score tiers, pitch blurb generator
│   └── brand_extractor.py      # LLM brand extraction + video validation (SambaNova)
└── scripts/
    ├── collect.py              # Collect fresh YouTube data for all brands
    └── discover_brands.py      # Discover brands from YouTube and write discovered_brands.csv
```

---

## Limitations

- **YouTube only** — no TikTok, Instagram, or Shorts. For many CPG brands, a big slice of creator activity is on TikTok and is not captured here.
- **50 videos per brand** — for large brands this is a narrow slice. For smaller brands it's closer to the full picture.
- **Organic vs. paid** — there's no way to tell from the data whether a video is sponsored or organic.
- **Scores are relative** — the percentile system means scores shift as the brand cohort changes. A score of 75 means "top quartile in this dataset", not an absolute measure.
