import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import (
    BRANDS_CSV, SCORING_WEIGHTS,
    CATEGORY_FIT, DB_PATH,
)
from database.db import (
    init_db, get_all_metrics, upsert_metrics, upsert_scores,
    get_all_scores, get_data_freshness, get_data_sources_summary,
)
from collectors.youtube import YouTubeCollector
from scoring.scorer import ICPScorer
from utils.helpers import (
    format_number, score_color, score_tier, score_badge_html,
    platform_badges_html, generate_why_zelf_blurb, engagement_rate_fmt,
)

# --- Page Config ---
st.set_page_config(
    page_title="Zelf ICP Lead Scorer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown("""
<style>
    .score-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-weight: bold;
        color: white;
        font-size: 14px;
    }
    .metric-card {
        background: #f8fafc;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #e2e8f0;
    }
    .brand-header {
        font-size: 24px;
        font-weight: 700;
        margin-bottom: 4px;
    }
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px 16px;
    }
</style>
""", unsafe_allow_html=True)

# --- Init ---
init_db()


@st.cache_data(ttl=60)
def load_brands() -> pd.DataFrame:
    return pd.read_csv(BRANDS_CSV)


def load_all_data() -> tuple[pd.DataFrame, dict]:
    """Load all metrics from DB and organize by brand."""
    brands_df = load_brands()
    all_metrics = get_all_metrics()

    # Organize metrics by brand
    brand_platforms = {}
    for m in all_metrics:
        bn = m["brand_name"]
        if bn not in brand_platforms:
            brand_platforms[bn] = {}
        brand_platforms[bn][m["platform"]] = m["metrics"]

    return brands_df, brand_platforms


def collect_all_data(progress_bar=None):
    """Run all collectors for all brands."""
    brands_df = load_brands()
    yt_collector = YouTubeCollector()
    total = len(brands_df)

    for i, (_, row) in enumerate(brands_df.iterrows()):
        brand = row["brand_name"]
        if progress_bar:
            progress_bar.progress((i + 1) / total, text=f"Collecting: {brand}")
        yt_collector.collect(brand, use_cache=False)


def score_all_brands() -> pd.DataFrame:
    """Score all brands from cached metrics."""
    brands_df, brand_platforms = load_all_data()
    scorer = ICPScorer()

    brand_data = []
    for _, row in brands_df.iterrows():
        bn = row["brand_name"]
        platforms = brand_platforms.get(bn, {})
        brand_data.append({
            "brand_name": bn,
            "category": row["category"],
            "platforms": platforms,
        })

    scores_df = scorer.score_brands(brand_data)

    if not scores_df.empty:
        # Save scores to DB
        score_records = []
        for _, r in scores_df.iterrows():
            score_records.append({
                "brand_name": r["brand_name"],
                "category": r["category"],
                "icp_score": r["icp_score"],
                "creator_reach_score": r["creator_reach_score"],
                "creator_ecosystem_score": r["creator_ecosystem_score"],
                "content_intent_score": r["content_intent_score"],
                "category_fit_score": r["category_fit_score"],
                "platforms_active": r["platforms_active"],
                "total_videos": r["total_videos"],
                "total_views": r["total_views"],
                "total_likes": r["total_likes"],
                "total_comments": r["total_comments"],
                "unique_creators": int(r["unique_creators"]),
                "breakout_ratio": r["breakout_ratio"],
                "review_intent_ratio": r["review_intent_ratio"],
                "purchase_intent_score": r["purchase_intent_score"],
            })
        upsert_scores(score_records)

    return scores_df


# --- Sidebar ---
st.sidebar.title("🎯 Zelf ICP Scorer")
st.sidebar.markdown("*Discover which CPG brands need Zelf the most*")
st.sidebar.divider()

# Data freshness
freshness = get_data_freshness()
if freshness:
    st.sidebar.caption(f"📅 Data last updated: {freshness[:10]}")
else:
    st.sidebar.caption("📅 No data collected yet")

# Data sources
sources = get_data_sources_summary()
if sources:
    source_text = " · ".join(f"{k}: {v}" for k, v in sources.items())
    st.sidebar.caption(f"📊 Sources: {source_text}")

st.sidebar.divider()

# Refresh button
if st.sidebar.button("🔄 Refresh Data", width="stretch"):
    with st.spinner("Collecting data from YouTube..."):
        progress = st.sidebar.progress(0, text="Starting collection...")
        collect_all_data(progress_bar=progress)
        progress.empty()
        st.sidebar.success("Collection complete!")
        st.cache_data.clear()
        st.rerun()

# Seed from sample data if no data exists
if not get_all_metrics():
    with st.spinner("Loading sample data..."):
        collect_all_data()
        st.cache_data.clear()
        st.rerun()

# Score brands
scores_df = score_all_brands()

if scores_df.empty:
    st.warning("No data available. Click 'Refresh Data' in the sidebar to collect metrics.")
    st.stop()

# Load platform data for detail views
brands_df, brand_platforms = load_all_data()

# --- Sidebar Filters ---
st.sidebar.divider()
st.sidebar.subheader("Filters")

categories = sorted(scores_df["category"].unique())
selected_categories = st.sidebar.multiselect(
    "Category", categories, default=categories
)

score_range = st.sidebar.slider(
    "ICP Score Range", 0, 100, (0, 100)
)

platform_filter = st.sidebar.multiselect(
    "Minimum Platforms Active",
    [1, 2, 3],
    default=[1, 2, 3],
)

# Apply filters
filtered_df = scores_df[
    (scores_df["category"].isin(selected_categories))
    & (scores_df["icp_score"] >= score_range[0])
    & (scores_df["icp_score"] <= score_range[1])
    & (scores_df["platforms_active"].isin(platform_filter))
].copy()

# --- Header ---
st.title("Zelf ICP Lead Scorer")
st.markdown("**Discover and rank CPG brands by their creator video ecosystem — "
            "the #1 signal for Zelf-readiness.**")

# --- Summary Cards ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Brands Scored", len(filtered_df))
with col2:
    avg_score = filtered_df["icp_score"].mean() if len(filtered_df) > 0 else 0
    st.metric("Avg ICP Score", f"{avg_score:.1f}")
with col3:
    if len(filtered_df) > 0:
        top_cat = filtered_df.groupby("category")["icp_score"].mean().idxmax()
        st.metric("Top Category", top_cat)
    else:
        st.metric("Top Category", "—")
with col4:
    hot_leads = len(filtered_df[filtered_df["icp_score"] >= 70])
    st.metric("Hot Leads", hot_leads)

st.divider()

# --- Tabs ---
tab_table, tab_charts, tab_detail = st.tabs(["📋 Ranked Table", "📊 Charts", "🔍 Brand Deep Dive"])

# --- Tab 1: Ranked Table ---
with tab_table:
    st.subheader("Lead Ranking")

    # Build display dataframe
    display_data = []
    for _, row in filtered_df.iterrows():
        tier = score_tier(row["icp_score"])
        display_data.append({
            "Rank": int(row["rank"]),
            "Brand": row["brand_name"],
            "Category": row["category"],
            "ICP Score": row["icp_score"],
            "Tier": tier,
            "Reach": row["creator_reach_score"],
            "Ecosystem": row["creator_ecosystem_score"],
            "Intent": row["content_intent_score"],
            "Category Fit": row["category_fit_score"],
            "Creators": int(row["unique_creators"]),
            "Total Views": row["total_views"],
        })

    display_df = pd.DataFrame(display_data)

    if not display_df.empty:
        def color_score(val):
            color = score_color(val)
            return f"background-color: {color}; color: white; font-weight: bold; border-radius: 8px; text-align: center"

        def color_tier(val):
            colors = {"Hot Lead": "#dcfce7", "Warm Lead": "#fef9c3", "Low Priority": "#fee2e2"}
            return f"background-color: {colors.get(val, '#f1f5f9')}"

        styled = display_df.style.map(
            color_score, subset=["ICP Score"]
        ).map(
            color_tier, subset=["Tier"]
        ).format({
            "ICP Score": "{:.1f}",
            "Reach": "{:.1f}",
            "Ecosystem": "{:.1f}",
            "Intent": "{:.1f}",
            "Category Fit": "{:.1f}",
            "Total Views": lambda x: format_number(x),
        })

        st.dataframe(styled, width="stretch", height=600, hide_index=True)

    # Export
    if st.button("📥 Export to CSV"):
        csv = display_df.to_csv(index=False)
        st.download_button("Download CSV", csv, "zelf_icp_scores.csv", "text/csv")

# --- Tab 2: Charts ---
with tab_charts:
    chart_tab1, chart_tab2, chart_tab3, chart_tab4 = st.tabs([
        "Score Distribution", "Category Comparison", "Platform Heatmap", "Top 10 Leads"
    ])

    with chart_tab1:
        st.subheader("ICP Score Distribution")
        fig = px.histogram(
            filtered_df, x="icp_score", nbins=20,
            color_discrete_sequence=["#6366f1"],
            labels={"icp_score": "ICP Score"},
        )
        fig.add_vrect(x0=70, x1=100, fillcolor="green", opacity=0.1,
                       annotation_text="Hot Leads", annotation_position="top right")
        fig.add_vrect(x0=40, x1=70, fillcolor="yellow", opacity=0.1,
                       annotation_text="Warm", annotation_position="top right")
        fig.add_vrect(x0=0, x1=40, fillcolor="red", opacity=0.05,
                       annotation_text="Low Priority", annotation_position="top left")
        fig.update_layout(yaxis_title="Number of Brands", bargap=0.1)
        st.plotly_chart(fig, width="stretch")

    with chart_tab2:
        st.subheader("Average ICP Score by Category")
        cat_scores = filtered_df.groupby("category")["icp_score"].mean().sort_values(ascending=True)
        fig = px.bar(
            x=cat_scores.values, y=cat_scores.index,
            orientation="h",
            color=cat_scores.values,
            color_continuous_scale="RdYlGn",
            labels={"x": "Average ICP Score", "y": "Category"},
        )
        fig.update_layout(showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")

    with chart_tab3:
        st.subheader("Sub-Score Heatmap")
        heatmap_data = filtered_df.set_index("brand_name")[
            ["creator_reach_score", "creator_ecosystem_score",
             "content_intent_score", "category_fit_score"]
        ].rename(columns={
            "creator_reach_score": "Reach",
            "creator_ecosystem_score": "Ecosystem",
            "content_intent_score": "Intent",
            "category_fit_score": "Category Fit",
        })
        # Show top 20 for readability
        heatmap_data = heatmap_data.head(20)
        fig = px.imshow(
            heatmap_data,
            color_continuous_scale="RdYlGn",
            aspect="auto",
            labels={"color": "Score"},
        )
        fig.update_layout(height=600)
        st.plotly_chart(fig, width="stretch")

    with chart_tab4:
        st.subheader("Top 10 Leads")
        top10 = filtered_df.head(10)
        fig = px.bar(
            top10, x="icp_score", y="brand_name",
            orientation="h",
            color="icp_score",
            color_continuous_scale="RdYlGn",
            labels={"icp_score": "ICP Score", "brand_name": "Brand"},
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            showlegend=False,
            coloraxis_showscale=False,
            height=400,
        )
        st.plotly_chart(fig, width="stretch")

# --- Tab 3: Brand Deep Dive ---
with tab_detail:
    st.subheader("Brand Deep Dive")

    brand_names = filtered_df["brand_name"].tolist()
    selected_brand = st.selectbox("Select a brand", brand_names)

    if selected_brand:
        brand_row = filtered_df[filtered_df["brand_name"] == selected_brand].iloc[0]
        brand_metrics = brand_platforms.get(selected_brand, {})

        # Header
        col_head, col_score = st.columns([3, 1])
        with col_head:
            st.markdown(f"### {selected_brand}")
            st.caption(f"{brand_row['category']} · {score_tier(brand_row['icp_score'])} · "
                        f"{int(brand_row['platforms_active'])} platform{'s' if brand_row['platforms_active'] != 1 else ''} active")
        with col_score:
            color = score_color(brand_row["icp_score"])
            st.markdown(
                f'<div style="text-align:center;padding:10px;">'
                f'<div style="font-size:48px;font-weight:bold;color:{color};">'
                f'{brand_row["icp_score"]:.0f}</div>'
                f'<div style="color:#6b7280;font-size:14px;">ICP Score</div></div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # Radar chart + metrics side by side
        col_radar, col_metrics = st.columns([1, 1])

        with col_radar:
            st.markdown("**Score Breakdown**")
            dimensions = ["Reach", "Ecosystem", "Intent", "Category Fit"]
            max_vals = [
                SCORING_WEIGHTS["creator_reach"],
                SCORING_WEIGHTS["creator_ecosystem"],
                SCORING_WEIGHTS["content_intent"],
                SCORING_WEIGHTS["category_fit"],
            ]
            values = [
                brand_row["creator_reach_score"],
                brand_row["creator_ecosystem_score"],
                brand_row["content_intent_score"],
                brand_row["category_fit_score"],
            ]
            # Normalize to 0-1 for radar
            normalized = [v / m if m > 0 else 0 for v, m in zip(values, max_vals)]

            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=normalized + [normalized[0]],
                theta=dimensions + [dimensions[0]],
                fill="toself",
                fillcolor="rgba(99, 102, 241, 0.2)",
                line=dict(color="#6366f1", width=2),
                name=selected_brand,
            ))
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 1], showticklabels=False),
                ),
                showlegend=False,
                height=350,
                margin=dict(t=30, b=30, l=60, r=60),
            )
            st.plotly_chart(fig, width="stretch")

        with col_metrics:
            st.markdown("**Key Metrics**")
            m1, m2 = st.columns(2)
            with m1:
                st.metric("Total Videos", format_number(brand_row["total_videos"]))
                st.metric("Total Views", format_number(brand_row["total_views"]))
            with m2:
                st.metric("Total Likes", format_number(brand_row["total_likes"]))
                st.metric("Total Comments", format_number(brand_row["total_comments"]))

            st.markdown("**Sub-Scores**")
            sub_data = {
                "Dimension": ["Creator Reach", "Creator Ecosystem", "Content Intent", "Category Fit"],
                "Score": [
                    brand_row["creator_reach_score"],
                    brand_row["creator_ecosystem_score"],
                    brand_row["content_intent_score"],
                    brand_row["category_fit_score"],
                ],
                "Max": [30, 25, 25, 20],
            }
            sub_df = pd.DataFrame(sub_data)
            sub_df["% of Max"] = (sub_df["Score"] / sub_df["Max"] * 100).round(0).astype(int)
            st.dataframe(sub_df, hide_index=True, width="stretch")

        # Per-platform breakdown
        st.divider()
        st.markdown("**Platform Breakdown**")
        plat_cols = st.columns(1)

        for i, (platform, icon) in enumerate([
            ("youtube", "▶️ YouTube"),
        ]):
            with plat_cols[i]:
                m = brand_metrics.get(platform)
                if m and m.get("data_source") != "unavailable":
                    source = m.get("data_source", "sample")
                    st.markdown(f"**{icon}** `{source}`")
                    st.caption(f"Followers: {format_number(m.get('followers', 0))}")
                    st.caption(f"Videos (90d): {m.get('shorts_last_90d', m.get('videos_last_90d', 0))}")
                    st.caption(f"Total Views: {format_number(m.get('total_views', 0))}")
                    st.caption(f"Avg Views: {format_number(m.get('avg_views', 0))}")
                    st.caption(f"Avg Likes: {format_number(m.get('avg_likes', 0))}")
                    er = m.get("engagement_rate", 0)
                    st.caption(f"Eng. Rate: {engagement_rate_fmt(er)}")
                else:
                    st.markdown(f"**{icon}** `unavailable`")
                    st.caption("No data collected")

        # Why Zelf blurb
        st.divider()
        st.markdown("**Why This Brand Needs Zelf**")
        blurb = generate_why_zelf_blurb(selected_brand, brand_row.to_dict())
        st.markdown(blurb)

# --- Footer ---
st.divider()
st.caption(
    "Data: creator videos about each brand on YouTube (last 90 days) via yt-dlp — no API quota. "
    "Scoring: Creator Reach (30pts) + Creator Ecosystem (25pts) + Content Intent (25pts) + Category Fit (20pts). "
    "Intent gate: brands with zero review/purchase signals are capped at 60."
)
