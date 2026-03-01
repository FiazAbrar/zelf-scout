import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import BRANDS_CSV, SCORING_WEIGHTS, CATEGORY_FIT
from database.db import (
    init_db, get_all_metrics, upsert_scores,
    get_data_freshness, get_data_sources_summary,
)
from collectors.youtube import YouTubeCollector
from scoring.scorer import ICPScorer
from utils.helpers import format_number, score_tier, generate_why_zelf_blurb

st.set_page_config(
    page_title="Zelf ICP Scorer",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

section[data-testid="stSidebar"] { border-right: 1px solid #f1f5f9; }

div[data-testid="stMetric"] {
    background: transparent;
    border: none;
    border-left: 3px solid #6366f1;
    padding: 8px 16px;
}
div[data-testid="stMetricLabel"] > div {
    color: #94a3b8; font-size: 11px; font-weight: 600;
    letter-spacing: .06em; text-transform: uppercase;
}
div[data-testid="stMetricValue"] > div { color: #0f172a; font-size: 26px; font-weight: 700; }

button[data-baseweb="tab"] { font-size: 13px; font-weight: 500; color: #64748b; }
button[data-baseweb="tab"][aria-selected="true"] { color: #6366f1; border-bottom-color: #6366f1; }

div[data-testid="stButton"] > button {
    background: #6366f1; color: white; border: none;
    font-weight: 500; border-radius: 6px; padding: .4rem 1rem;
}
div[data-testid="stButton"] > button:hover { background: #4f46e5; }

div[data-testid="stDownloadButton"] > button {
    background: transparent; color: #6366f1;
    border: 1px solid #6366f1; font-weight: 500; border-radius: 6px;
}

.tier-hot  { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#ecfdf5;color:#059669; }
.tier-warm { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#fffbeb;color:#d97706; }
.tier-low  { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#f8fafc;color:#94a3b8; }

.score-display { text-align:center; }
.score-display .score-num { font-size:52px;font-weight:700;line-height:1;letter-spacing:-2px; }
.score-display .score-label { font-size:10px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.1em;margin-top:4px; }
</style>
""", unsafe_allow_html=True)

PLOTLY_LAYOUT = dict(
    font_family="Inter",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=24, b=24, l=16, r=16),
    xaxis=dict(showgrid=True, gridcolor="#f1f5f9", zeroline=False),
    yaxis=dict(showgrid=True, gridcolor="#f1f5f9", zeroline=False),
)

init_db()


@st.cache_data(ttl=60)
def load_brands() -> pd.DataFrame:
    return pd.read_csv(BRANDS_CSV)


def load_all_data() -> tuple[pd.DataFrame, dict]:
    brands_df = load_brands()
    all_metrics = get_all_metrics()
    brand_platforms = {}
    for m in all_metrics:
        bn = m["brand_name"]
        if bn not in brand_platforms:
            brand_platforms[bn] = {}
        brand_platforms[bn][m["platform"]] = m["metrics"]
    return brands_df, brand_platforms


def collect_all_data(progress_bar=None, brands=None):
    if brands is None:
        brands_df = load_brands()
        brands = [r["brand_name"] for _, r in brands_df.iterrows()]
    yt = YouTubeCollector()
    for i, brand in enumerate(brands):
        if progress_bar:
            progress_bar.progress((i + 1) / len(brands), text=f"Collecting: {brand}")
        yt.collect(brand, use_cache=False)


def score_all_brands() -> pd.DataFrame:
    brands_df, brand_platforms = load_all_data()
    scorer = ICPScorer()
    brand_data = [
        {
            "brand_name": r["brand_name"],
            "category": r["category"],
            "platforms": brand_platforms.get(r["brand_name"], {}),
        }
        for _, r in brands_df.iterrows()
    ]
    scores_df = scorer.score_brands(brand_data)
    if not scores_df.empty:
        upsert_scores([
            {
                "brand_name": r["brand_name"], "category": r["category"],
                "icp_score": r["icp_score"],
                "creator_reach_score": r["creator_reach_score"],
                "creator_ecosystem_score": r["creator_ecosystem_score"],
                "content_intent_score": r["content_intent_score"],
                "category_fit_score": r["category_fit_score"],
                "platforms_active": r["platforms_active"],
                "total_videos": r["total_videos"], "total_views": r["total_views"],
                "total_likes": r["total_likes"], "total_comments": r["total_comments"],
                "unique_creators": int(r["unique_creators"]),
                "breakout_ratio": r["breakout_ratio"],
                "review_intent_ratio": r["review_intent_ratio"],
                "purchase_intent_score": r["purchase_intent_score"],
            }
            for _, r in scores_df.iterrows()
        ])
    return scores_df


def _md(text: str) -> str:
    """Convert **bold** markdown to HTML and split paragraphs."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    return ''.join(
        f'<p style="margin:0 0 12px;line-height:1.65;color:#374151">{p}</p>'
        for p in paras
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("## Zelf ICP Scorer")
st.sidebar.markdown(
    "<span style='color:#94a3b8;font-size:13px'>CPG creator buzz → ranked leads</span>",
    unsafe_allow_html=True,
)
st.sidebar.divider()

freshness = get_data_freshness()
sources   = get_data_sources_summary()
if freshness:
    st.sidebar.caption(f"Updated {freshness[:10]}  ·  {sum(sources.values())} brands")
else:
    st.sidebar.caption("No data yet")

st.sidebar.markdown("")
if st.sidebar.button("Refresh Data", use_container_width=True):
    with st.spinner("Fetching YouTube metrics…"):
        prog = st.sidebar.progress(0, text="Starting…")
        collect_all_data(progress_bar=prog)
        prog.empty()
    st.cache_data.clear()
    st.rerun()

# ── Data ──────────────────────────────────────────────────────────────────────
scores_df = score_all_brands()

if scores_df.empty:
    st.info("No data yet — click **Refresh Data** in the sidebar.")
    st.stop()

brands_df, brand_platforms = load_all_data()

# ── Filters ───────────────────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.markdown(
    "<span style='font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em'>Filters</span>",
    unsafe_allow_html=True,
)
categories = sorted(scores_df["category"].unique())
selected_categories = st.sidebar.multiselect(
    "Category", categories, default=categories, label_visibility="collapsed"
)
score_range = st.sidebar.slider("ICP Score", 0, 100, (0, 100))

filtered_df = scores_df[
    scores_df["category"].isin(selected_categories) &
    scores_df["icp_score"].between(score_range[0], score_range[1])
].copy()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# ICP Lead Scorer")
st.markdown(
    "<span style='color:#64748b;font-size:15px'>"
    "Ranks CPG brands by organic creator activity — the leading signal for Zelf-readiness."
    "</span>",
    unsafe_allow_html=True,
)

# ── Scoring methodology strip ─────────────────────────────────────────────────
st.markdown("""
<div style="display:grid;grid-template-columns:repeat(4,1fr);border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;margin:20px 0 4px">

  <div style="padding:16px 20px;border-right:1px solid #e2e8f0">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;color:#0f172a;text-transform:uppercase">Creator Reach</span>
      <span style="background:#ede9fe;color:#6366f1;font-size:9px;font-weight:700;padding:1px 7px;border-radius:99px;letter-spacing:.04em">30 PTS</span>
    </div>
    <div style="font-size:12px;color:#64748b;line-height:1.55;margin-bottom:8px">
      Total views on creator content over the last 90 days
    </div>
    <div style="font-size:10px;color:#94a3b8;font-style:italic">Percentile rank vs. all brands</div>
  </div>

  <div style="padding:16px 20px;border-right:1px solid #e2e8f0">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;color:#0f172a;text-transform:uppercase">Ecosystem</span>
      <span style="background:#ede9fe;color:#6366f1;font-size:9px;font-weight:700;padding:1px 7px;border-radius:99px;letter-spacing:.04em">25 PTS</span>
    </div>
    <div style="font-size:12px;color:#64748b;line-height:1.55;margin-bottom:8px">
      Unique creator count + viral breakout potential
    </div>
    <div style="font-size:10px;color:#94a3b8;font-style:italic">Percentile + log-scaled breakout bonus</div>
  </div>

  <div style="padding:16px 20px;border-right:1px solid #e2e8f0">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;color:#0f172a;text-transform:uppercase">Content Intent</span>
      <span style="background:#ede9fe;color:#6366f1;font-size:9px;font-weight:700;padding:1px 7px;border-radius:99px;letter-spacing:.04em">25 PTS</span>
    </div>
    <div style="font-size:12px;color:#64748b;line-height:1.55;margin-bottom:8px">
      Review / haul keywords in titles + buy language in comments
    </div>
    <div style="font-size:10px;color:#94a3b8;font-style:italic">Absolute signal · not relative to cohort</div>
  </div>

  <div style="padding:16px 20px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;color:#0f172a;text-transform:uppercase">Category Fit</span>
      <span style="background:#ede9fe;color:#6366f1;font-size:9px;font-weight:700;padding:1px 7px;border-radius:99px;letter-spacing:.04em">20 PTS</span>
    </div>
    <div style="font-size:12px;color:#64748b;line-height:1.55;margin-bottom:8px">
      Static Zelf ICP alignment — Beauty &amp; Food score full points
    </div>
    <div style="font-size:10px;color:#94a3b8;font-style:italic">Fixed multiplier by category type</div>
  </div>

</div>
<div style="font-size:11px;color:#cbd5e1;margin-bottom:24px;padding-left:2px">
  Source: YouTube · collected via yt-dlp (no API key) · 90-day window ·
  brands with zero intent signals are capped at 60
</div>
""", unsafe_allow_html=True)

# ── Summary strip ─────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
hot  = filtered_df[filtered_df["icp_score"] >= 70]
warm = filtered_df[(filtered_df["icp_score"] >= 40) & (filtered_df["icp_score"] < 70)]
avg  = filtered_df["icp_score"].mean() if len(filtered_df) else 0
top_cat = filtered_df.groupby("category")["icp_score"].mean().idxmax() if len(filtered_df) else "—"

c1.metric("Brands", len(filtered_df))
c2.metric("Hot Leads", len(hot))
c3.metric("Avg Score", f"{avg:.0f}")
c4.metric("Top Category", top_cat)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_table, tab_explore, tab_detail = st.tabs(["Ranking", "Explore", "Brand Deep Dive"])


# ── Tab 1: Ranking ────────────────────────────────────────────────────────────
with tab_table:
    rows = []
    for _, r in filtered_df.iterrows():
        rows.append({
            "#": int(r["rank"]),
            "Brand": r["brand_name"],
            "Category": r["category"],
            "Score": r["icp_score"],
            "Reach": r["creator_reach_score"],
            "Ecosystem": r["creator_ecosystem_score"],
            "Intent": r["content_intent_score"],
            "Cat. Fit": r["category_fit_score"],
            "Creators": int(r["unique_creators"]),
            "Views": r["total_views"],
        })

    disp = pd.DataFrame(rows)

    def _shade_score(val):
        if val >= 70: return "color:#059669;font-weight:700"
        if val >= 40: return "color:#d97706;font-weight:700"
        return "color:#94a3b8;font-weight:600"

    styled = (
        disp.style
        .applymap(_shade_score, subset=["Score"])
        .format({
            "Score": "{:.1f}", "Reach": "{:.1f}", "Ecosystem": "{:.1f}",
            "Intent": "{:.1f}", "Cat. Fit": "{:.1f}",
            "Views": lambda x: format_number(x),
        })
        .set_properties(**{"font-size": "13px"})
        .set_table_styles([
            {"selector": "thead th", "props": [
                ("font-size", "10px"), ("font-weight", "700"),
                ("color", "#94a3b8"), ("text-transform", "uppercase"),
                ("letter-spacing", ".07em"), ("border-bottom", "2px solid #e2e8f0"),
            ]},
            {"selector": "tbody tr:hover", "props": [("background-color", "#f8fafc")]},
            {"selector": "td", "props": [
                ("border-bottom", "1px solid #f8fafc"), ("padding", "8px 12px"),
            ]},
        ])
    )

    st.markdown(
        "<div style='font-size:11px;color:#94a3b8;margin-bottom:8px'>"
        "Reach · Ecosystem · Intent · Cat. Fit are sub-scores out of 30 · 25 · 25 · 20"
        "</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(styled, height=560, hide_index=True, use_container_width=True)

    csv = disp.to_csv(index=False)
    st.download_button("Export CSV", csv, "zelf_icp_scores.csv", "text/csv")


# ── Tab 2: Explore ────────────────────────────────────────────────────────────
with tab_explore:
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Opportunity Matrix**")
        st.caption("Reach vs. intent — top-right quadrant = highest priority. Bubble size = creator count.")

        fig = px.scatter(
            filtered_df,
            x="creator_reach_score",
            y="content_intent_score",
            size="unique_creators",
            color="category",
            hover_name="brand_name",
            hover_data={"icp_score": ":.1f", "unique_creators": True,
                        "creator_reach_score": False, "content_intent_score": False},
            size_max=36,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig.add_hline(y=filtered_df["content_intent_score"].median(),
                      line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.add_vline(x=filtered_df["creator_reach_score"].median(),
                      line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.update_layout(
            **PLOTLY_LAYOUT,
            xaxis_title="Creator Reach Score", yaxis_title="Content Intent Score",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=11)),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.markdown("**Top 15 Brands by ICP Score**")
        st.caption("Green = Hot Lead (≥70) · Indigo = Warm (≥40) · Gray = Low Priority")

        top15 = filtered_df.head(15).sort_values("icp_score")
        fig = go.Figure(go.Bar(
            x=top15["icp_score"],
            y=top15["brand_name"],
            orientation="h",
            marker_color=[
                "#059669" if s >= 70 else "#6366f1" if s >= 40 else "#e2e8f0"
                for s in top15["icp_score"]
            ],
            text=top15["icp_score"].round(1),
            textposition="outside",
            textfont=dict(size=11, color="#64748b"),
        ))
        fig.update_layout(
            **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")},
            xaxis=dict(range=[0, 105], showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Average ICP Score by Category**")
    cat_avg = (
        filtered_df.groupby("category")["icp_score"]
        .agg(["mean", "count"])
        .reset_index()
        .sort_values("mean", ascending=True)
    )
    fig = go.Figure(go.Bar(
        x=cat_avg["mean"].round(1),
        y=cat_avg["category"],
        orientation="h",
        marker_color="#6366f1",
        opacity=0.8,
        text=cat_avg.apply(lambda r: f"{r['mean']:.0f}  ({int(r['count'])} brands)", axis=1),
        textposition="outside",
        textfont=dict(size=11, color="#64748b"),
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")},
        xaxis=dict(range=[0, 105], showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False),
        height=280,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Tab 3: Brand Deep Dive ────────────────────────────────────────────────────
with tab_detail:
    brand_names = filtered_df["brand_name"].tolist()
    selected = st.selectbox("", brand_names, label_visibility="collapsed")

    if selected:
        row  = filtered_df[filtered_df["brand_name"] == selected].iloc[0]
        tier = score_tier(row["icp_score"])
        n_brands = len(scores_df)

        # ── Header ────────────────────────────────────────────────────────────
        hcol, scol = st.columns([5, 1])
        with hcol:
            st.markdown(f"### {selected}")
            tier_class = (
                "tier-hot" if row["icp_score"] >= 70
                else "tier-warm" if row["icp_score"] >= 40
                else "tier-low"
            )
            st.markdown(
                f'<span class="{tier_class}">{tier}</span>'
                f'<span style="color:#94a3b8;font-size:13px;margin-left:10px">{row["category"]}</span>',
                unsafe_allow_html=True,
            )
        with scol:
            sc = "#059669" if row["icp_score"] >= 70 else "#d97706" if row["icp_score"] >= 40 else "#94a3b8"
            st.markdown(
                f'<div class="score-display">'
                f'<div class="score-num" style="color:{sc}">{row["icp_score"]:.0f}</div>'
                f'<div class="score-label">ICP Score</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Intent gate notice
        intent_absent = row["review_intent_ratio"] == 0 and row["purchase_intent_score"] == 0
        if intent_absent:
            st.markdown(
                '<div style="background:#fef9c3;border:1px solid #fde68a;border-radius:6px;'
                'padding:8px 14px;font-size:12px;color:#92400e;margin:8px 0">'
                '⚑ Intent gate applied — no creator intent signals detected; score capped at 60'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        left, right = st.columns([1, 1])

        # ── Radar chart ───────────────────────────────────────────────────────
        with left:
            dims  = ["Reach", "Ecosystem", "Intent", "Cat. Fit"]
            maxes = [SCORING_WEIGHTS[k] for k in
                     ["creator_reach", "creator_ecosystem", "content_intent", "category_fit"]]
            vals  = [row[k] for k in
                     ["creator_reach_score", "creator_ecosystem_score",
                      "content_intent_score", "category_fit_score"]]
            norm  = [v / mx if mx else 0 for v, mx in zip(vals, maxes)]

            fig = go.Figure(go.Scatterpolar(
                r=norm + [norm[0]],
                theta=dims + [dims[0]],
                fill="toself",
                fillcolor="rgba(99,102,241,0.10)",
                line=dict(color="#6366f1", width=2),
            ))
            fig.update_layout(
                polar=dict(
                    bgcolor="white",
                    radialaxis=dict(
                        visible=True, range=[0, 1],
                        showticklabels=False, gridcolor="#f1f5f9", linecolor="#f1f5f9",
                    ),
                    angularaxis=dict(gridcolor="#f1f5f9", linecolor="#f1f5f9"),
                ),
                showlegend=False,
                height=300,
                margin=dict(t=16, b=16, l=48, r=48),
                paper_bgcolor="rgba(0,0,0,0)",
                font_family="Inter",
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Score bars with raw signals ───────────────────────────────────────
        with right:
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            fit_mult = CATEGORY_FIT.get(row["category"], 0.3)

            dim_configs = [
                (
                    "Creator Reach",
                    "creator_reach_score", "creator_reach",
                    f"{format_number(int(row['total_views']))} total views · "
                    f"{int(row['total_videos'])} videos found",
                    "percentile rank vs. all brands in cohort",
                ),
                (
                    "Ecosystem",
                    "creator_ecosystem_score", "creator_ecosystem",
                    f"{int(row['unique_creators'])} unique creators · "
                    f"{row['breakout_ratio']:.1f}× breakout ratio",
                    "percentile + log-scaled viral bonus (max +5 pts)",
                ),
                (
                    "Content Intent",
                    "content_intent_score", "content_intent",
                    f"{row['review_intent_ratio']*100:.0f}% review-titled videos · "
                    f"{row['purchase_intent_score']:.2f} purchase score",
                    "absolute · 60% title weight + 40% comment weight",
                ),
                (
                    "Category Fit",
                    "category_fit_score", "category_fit",
                    f"{row['category']} · {fit_mult:.1f}× ICP multiplier",
                    "fixed weight · Beauty / Food / Personal Care = full score",
                ),
            ]

            bars_html = ""
            for label, score_col, weight_key, signal, method in dim_configs:
                val = row[score_col]
                mx  = SCORING_WEIGHTS[weight_key]
                pct = val / mx if mx else 0
                bar_color = (
                    "#6366f1" if pct > 0.65
                    else "#a5b4fc" if pct > 0.35
                    else "#e2e8f0"
                )
                bars_html += f"""
<div style="margin-bottom:18px">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px">
    <span style="font-size:10px;font-weight:700;color:#374151;letter-spacing:.08em;text-transform:uppercase">{label}</span>
    <span style="font-size:13px;font-weight:700;color:#0f172a">{val:.1f}
      <span style="color:#cbd5e1;font-weight:400;font-size:11px"> / {mx}</span>
    </span>
  </div>
  <div style="font-size:11px;color:#64748b;margin-bottom:3px">{signal}</div>
  <div style="font-size:10px;color:#94a3b8;font-style:italic;margin-bottom:7px">{method}</div>
  <div style="background:#f1f5f9;border-radius:99px;height:4px">
    <div style="background:{bar_color};border-radius:99px;height:4px;width:{pct*100:.0f}%"></div>
  </div>
</div>"""

            st.markdown(bars_html, unsafe_allow_html=True)

        # ── Raw stats ─────────────────────────────────────────────────────────
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Videos Found", format_number(row["total_videos"]))
        sc2.metric("Total Views", format_number(row["total_views"]))
        sc3.metric("Unique Creators", int(row["unique_creators"]))
        sc4.metric("Breakout Ratio", f"{row['breakout_ratio']:.1f}×")

        # ── Why Zelf ──────────────────────────────────────────────────────────
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        blurb_html = _md(generate_why_zelf_blurb(selected, row.to_dict()))
        st.markdown(
            f'<div style="background:#f8fafc;border-radius:10px;padding:20px 24px;'
            f'border:1px solid #f1f5f9;font-size:14px">'
            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;'
            f'text-transform:uppercase;margin-bottom:12px">Sales Signal</div>'
            f'{blurb_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)
st.markdown(
    "<span style='color:#cbd5e1;font-size:11px'>"
    "YouTube · yt-dlp · 90-day lookback · "
    "Scoring: Reach 30 + Ecosystem 25 + Intent 25 + Category Fit 20 = 100 pts"
    "</span>",
    unsafe_allow_html=True,
)
