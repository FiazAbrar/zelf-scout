import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config as _config


def _db_path(db_path: Path | None = None) -> Path:
    return db_path if db_path is not None else _config.DB_PATH


def get_connection(db_path: Path = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(db_path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path = None):
    conn = get_connection(db_path)

    # Migrate brand_scores schema if old columns exist
    try:
        conn.execute("SELECT creator_reach_score FROM brand_scores LIMIT 1")
    except sqlite3.OperationalError:
        # Old schema (missing column) — drop and recreate
        conn.execute("DROP TABLE IF EXISTS brand_scores")
        conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS brand_metrics (
            brand_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            data_source TEXT NOT NULL DEFAULT 'sample',
            collected_at TEXT NOT NULL,
            PRIMARY KEY (brand_name, platform)
        );

        CREATE TABLE IF NOT EXISTS brand_scores (
            brand_name TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            icp_score REAL NOT NULL,
            creator_reach_score REAL NOT NULL,
            creator_ecosystem_score REAL NOT NULL,
            content_intent_score REAL NOT NULL,
            category_fit_score REAL NOT NULL,
            platforms_active INTEGER NOT NULL,
            total_videos INTEGER NOT NULL,
            total_views INTEGER NOT NULL,
            total_likes INTEGER NOT NULL,
            total_comments INTEGER NOT NULL,
            unique_creators INTEGER NOT NULL DEFAULT 0,
            breakout_ratio REAL NOT NULL DEFAULT 0.0,
            review_intent_ratio REAL NOT NULL DEFAULT 0.0,
            purchase_intent_score REAL NOT NULL DEFAULT 0.0,
            scored_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL,
            data_source TEXT,
            error_message TEXT,
            collected_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def upsert_metrics(brand_name: str, platform: str, metrics: dict,
                   data_source: str = "sample", db_path: Path = None):
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO brand_metrics (brand_name, platform, metrics_json, data_source, collected_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(brand_name, platform) DO UPDATE SET
            metrics_json = excluded.metrics_json,
            data_source = excluded.data_source,
            collected_at = excluded.collected_at
    """, (brand_name, platform, json.dumps(metrics), data_source, _now()))
    conn.commit()
    conn.close()


def get_metrics(brand_name: str, platform: str,
                db_path: Path = None) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT metrics_json, data_source, collected_at FROM brand_metrics WHERE brand_name = ? AND platform = ?",
        (brand_name, platform)
    ).fetchone()
    conn.close()
    if row:
        return {
            "metrics": json.loads(row["metrics_json"]),
            "data_source": row["data_source"],
            "collected_at": row["collected_at"],
        }
    return None


def get_all_metrics(db_path: Path = None) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT brand_name, platform, metrics_json, data_source, collected_at FROM brand_metrics"
    ).fetchall()
    conn.close()
    return [
        {
            "brand_name": r["brand_name"],
            "platform": r["platform"],
            "metrics": json.loads(r["metrics_json"]),
            "data_source": r["data_source"],
            "collected_at": r["collected_at"],
        }
        for r in rows
    ]


def upsert_scores(scores: list[dict], db_path: Path = None):
    conn = get_connection(db_path)
    now = _now()
    for s in scores:
        conn.execute("""
            INSERT INTO brand_scores (
                brand_name, category, icp_score,
                creator_reach_score, creator_ecosystem_score,
                content_intent_score, category_fit_score,
                platforms_active, total_videos, total_views,
                total_likes, total_comments,
                unique_creators, breakout_ratio,
                review_intent_ratio, purchase_intent_score,
                scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(brand_name) DO UPDATE SET
                category = excluded.category,
                icp_score = excluded.icp_score,
                creator_reach_score = excluded.creator_reach_score,
                creator_ecosystem_score = excluded.creator_ecosystem_score,
                content_intent_score = excluded.content_intent_score,
                category_fit_score = excluded.category_fit_score,
                platforms_active = excluded.platforms_active,
                total_videos = excluded.total_videos,
                total_views = excluded.total_views,
                total_likes = excluded.total_likes,
                total_comments = excluded.total_comments,
                unique_creators = excluded.unique_creators,
                breakout_ratio = excluded.breakout_ratio,
                review_intent_ratio = excluded.review_intent_ratio,
                purchase_intent_score = excluded.purchase_intent_score,
                scored_at = excluded.scored_at
        """, (
            s["brand_name"], s["category"], s["icp_score"],
            s["creator_reach_score"], s["creator_ecosystem_score"],
            s["content_intent_score"], s["category_fit_score"],
            s["platforms_active"], s["total_videos"], s["total_views"],
            s["total_likes"], s["total_comments"],
            s["unique_creators"], s["breakout_ratio"],
            s["review_intent_ratio"], s["purchase_intent_score"],
            now,
        ))
    conn.commit()
    conn.close()


def get_all_scores(db_path: Path = None) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM brand_scores ORDER BY icp_score DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_collection(brand_name: str, platform: str, status: str,
                   data_source: str = None, error_message: str = None,
                   db_path: Path = None):
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO collection_log (brand_name, platform, status, data_source, error_message, collected_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (brand_name, platform, status, data_source, error_message, _now()))
    conn.commit()
    conn.close()


def get_data_freshness(db_path: Path = None) -> Optional[str]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT MAX(collected_at) as latest FROM brand_metrics"
    ).fetchone()
    conn.close()
    if row and row["latest"]:
        return row["latest"]
    return None


def get_data_sources_summary(db_path: Path = None) -> dict:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT data_source, COUNT(*) as cnt
        FROM brand_metrics
        GROUP BY data_source
    """).fetchall()
    conn.close()
    return {r["data_source"]: r["cnt"] for r in rows}
