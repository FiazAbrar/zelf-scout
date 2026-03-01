from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BRANDS_CSV = DATA_DIR / "brands.csv"
DB_PATH = BASE_DIR / "zelf_cache.db"

# --- Scoring Weights (max points per dimension) ---
SCORING_WEIGHTS = {
    "video_volume": 30,
    "engagement_scale": 30,
    "engagement_rate": 25,
    "category_fit": 15,
}

# --- Category Fit Multipliers (Zelf ICP alignment by category) ---
CATEGORY_FIT = {
    "Beauty & Skincare": 1.0,
    "Food & Snacks": 1.0,
    "Personal Care": 1.0,
    "Beverage": 0.8,
    "Household": 0.6,
    "Pet Care": 0.4,
    "Other CPG": 0.3,
}

# --- YouTube Collection Settings (yt-dlp, no API key required) ---
YOUTUBE_LOOKBACK_DAYS = 90        # days of creator video history to consider
YOUTUBE_MAX_VIDEOS_PER_BRAND = 50 # flat search result cap per brand
YOUTUBE_FULL_FETCH_TOP_N = 5      # top-N videos to full-fetch for engagement data
