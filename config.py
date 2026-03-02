from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# --- Paths ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "zelf_cache.db"

_discovered = DATA_DIR / "discovered_brands.csv"
_seed       = DATA_DIR / "brands_seed.csv"
BRANDS_CSV  = _discovered if _discovered.exists() else _seed

# --- Scoring Weights (max points per dimension, must sum to 100) ---
#
# creator_reach    : total views on creator content  → how much reach does this ecosystem generate?
# creator_ecosystem: unique creator count + breakout → how broad and viral-capable is it?
# content_intent   : review keywords + purchase signals → do creators/audiences show real intent?
# category_fit     : static Zelf ICP alignment        → is this a brand Zelf is built for?
SCORING_WEIGHTS = {
    "creator_reach":     30,
    "creator_ecosystem": 25,
    "content_intent":    25,
    "category_fit":      20,
}

# Cap ICP score at this value when content intent signals are entirely absent.
# Prevents brands with huge view counts but zero creator intentionality from
# appearing as hot leads.
INTENT_ABSENT_SCORE_CAP = 60

# Breakout ratio bonus: up to this many extra points for viral potential.
# Log-scaled so one outlier video doesn't dominate.
BREAKOUT_BONUS_MAX_PTS = 5

# --- Category Fit Multipliers (Zelf ICP alignment by category) ---
CATEGORY_FIT = {
    "Beauty & Skincare": 1.0,
    "Food & Snacks":     1.0,
    "Personal Care":     1.0,
    "Beverage":          0.8,
    "Household":         0.6,
    "Pet Care":          0.4,
    "Other CPG":         0.3,
}

# --- Content Intent Keywords ---
# Matched against video titles (review intent) and top-video comments (purchase intent).

REVIEW_KEYWORDS = [
    "review", "haul", "routine", "unboxing", "unbox",
    "try", "tried", "testing", "tested", "honest",
    "worth it", "first impression", "reaction", "comparison", "vs",
]

PURCHASE_KEYWORDS = [
    "bought", "buy", "purchase", "purchased", "ordered", "order",
    "shopping", "shop", "picked up", "getting this", "need this",
    "on amazon", "at target", "at ulta", "at walmart",
    "discount code", "promo code", "use code", "link",
]

# --- YouTube Collection Settings (yt-dlp, no API key required) ---
YOUTUBE_LOOKBACK_DAYS = 90          # days of creator video history to consider
YOUTUBE_MAX_VIDEOS_PER_BRAND = 50   # flat search result cap per brand
YOUTUBE_FULL_FETCH_TOP_N = 5        # top-N videos to full-fetch for likes + comments
YOUTUBE_COMMENT_SAMPLE_SIZE = 50    # max comments to fetch from top video

# --- Brand Discovery Settings ---
DISCOVERY_QUERIES = {
    "Beauty & Skincare": [
        "skincare routine review",
        "makeup haul",
        "drugstore beauty try",
        "sunscreen review",
        "serum haul",
        "body lotion review",
        "tinted moisturizer review",
        "skincare products I use",
    ],
    "Food & Snacks": [
        "snack haul taste test",
        "grocery haul food review",
        "protein bar review",
        "healthy snack haul",
        "new snacks try",
        "chips review",
    ],
    "Beverage": [
        "energy drink review",
        "healthy drink haul",
        "sparkling water review",
        "prebiotic soda review",
        "protein shake review",
        "sports drink review",
    ],
    "Personal Care": [
        "personal care haul",
        "deodorant review",
        "shampoo conditioner review",
        "body wash review",
        "hair care haul",
        "toothpaste review",
    ],
    "Household": [
        "cleaning products review",
        "household haul",
        "laundry detergent review",
        "dish soap review",
        "all purpose cleaner review",
    ],
    "Pet Care": [
        "dog food review",
        "cat food review",
        "pet treats taste test",
        "pet food haul",
        "best dog food review",
    ],
}

DISCOVERY_VIDEOS_PER_QUERY = 50        # flat search cap per query
DISCOVERY_MIN_MENTIONS = 1             # brand must appear >= N times to be kept
DISCOVERY_MAX_BRANDS_PER_CATEGORY = 15 # cap per category → max ~90 brands total
