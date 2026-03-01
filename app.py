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
    background: transparent; border: none;
    border-left: 3px solid #6366f1; padding: 8px 16px;
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
    border: 1px solid #e2e8f0; font-weight: 500; border-radius: 6px;
}
/* Expander */
details summary { font-size: 12px; color: #94a3b8; font-weight: 500; }
.score-display { text-align: center; }
.score-display .score-num { font-size: 52px; font-weight: 700; line-height: 1; letter-spacing: -2px; }
.score-display .score-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }
.tier-hot  { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#ecfdf5;color:#059669; }
.tier-warm { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#fffbeb;color:#d97706; }
.tier-low  { display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;background:#f8fafc;color:#94a3b8; }
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



def score_all_brands() -> tuple[pd.DataFrame, int]:
    """Returns (scores_df, uncollected_count).

    Only brands with actual YouTube data are scored. Uncollected brands are
    excluded so they don't pollute the percentile distribution with zeros.
    """
    brands_df, brand_platforms = load_all_data()
    scorer = ICPScorer()

    collected, uncollected = [], []
    for _, r in brands_df.iterrows():
        entry = {"brand_name": r["brand_name"], "category": r["category"],
                 "platforms": brand_platforms.get(r["brand_name"], {})}
        if brand_platforms.get(r["brand_name"]):
            collected.append(entry)
        else:
            uncollected.append(r["brand_name"])

    brand_data = collected
    uncollected_count = len(uncollected)
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
    return scores_df, uncollected_count


def _md(text: str) -> str:
    """Convert **bold** markdown to HTML paragraphs."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    return ''.join(
        f'<p style="margin:0 0 12px;line-height:1.65;color:#374151">{p}</p>'
        for p in paras
    )


def _quality(pct: float) -> tuple[str, str]:
    """Return (label, color) for a score percentage."""
    if pct >= 0.80: return "exceptional", "#059669"
    if pct >= 0.60: return "strong",      "#10b981"
    if pct >= 0.40: return "moderate",    "#d97706"
    if pct >= 0.20: return "weak",        "#f97316"
    return "minimal", "#94a3b8"


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
    st.sidebar.caption("To refresh: `python scripts/collect.py`")
else:
    st.sidebar.caption("No data — run `python scripts/collect.py`")

# ── Data + filters ────────────────────────────────────────────────────────────
scores_df, uncollected_count = score_all_brands()

if scores_df.empty:
    st.info("No data yet — click **Refresh Data** in the sidebar.")
    st.stop()

brands_df, brand_platforms = load_all_data()

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

# Methodology expander — collapsed by default, clean when opened
with st.expander("How scores are computed"):
    st.markdown("""
**Score = Creator Reach (30) + Ecosystem (25) + Content Intent (25) + Category Fit (20)**

| | Weight | Method | Signal |
|---|---|---|---|
| **Creator Reach** | 30 pts | Percentile vs. cohort | Total views on creator content · 90 days |
| **Ecosystem** | 25 pts | Percentile + log bonus | Unique creators + breakout ratio (top video ÷ avg) |
| **Content Intent** | 25 pts | Absolute (not relative) | 60% review-keyword titles + 40% purchase language in comments |
| **Category Fit** | 20 pts | Fixed multiplier | Beauty / Food / Personal Care → 20 · Beverage → 16 · Household → 12 · Pet → 8 |

**Intent gate:** if a brand has zero review *and* purchase signals, total score is capped at 60 — high view volume alone isn't enough.
**Data:** YouTube · collected via yt-dlp (no API key) · brand's own channel excluded
""")

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── Summary strip ─────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
hot     = filtered_df[filtered_df["icp_score"] >= 70]
avg     = filtered_df["icp_score"].mean() if len(filtered_df) else 0
top_cat = filtered_df.groupby("category")["icp_score"].mean().idxmax() if len(filtered_df) else "—"

c1.metric("Brands", len(filtered_df),
          help="Total brands with YouTube data collected in the current filter.")
c2.metric("Hot Leads", len(hot),
          help="Brands scoring ≥ 70 — strong ICP fit with meaningful creator activity.")
c3.metric("Avg Score", f"{avg:.0f}",
          help="Mean ICP score across all filtered brands.")
c4.metric("Top Category", top_cat,
          help="Category with the highest average ICP score.")

if uncollected_count:
    st.markdown(
        f'<div style="margin-top:16px;padding:10px 16px;background:#fafafa;border:1px solid #e2e8f0;'
        f'border-radius:8px;font-size:13px;color:#64748b">'
        f'<strong style="color:#0f172a">{uncollected_count} brands</strong> have no data yet '
        f'and are excluded from scoring — run <code>python scripts/collect.py</code> to collect them.'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_table, tab_explore, tab_detail, tab_raw = st.tabs(["Ranking", "Explore", "Brand Deep Dive", "Raw Data"])


# ── Tab 1: Ranking ────────────────────────────────────────────────────────────
with tab_table:
    rows = []
    for _, r in filtered_df.iterrows():
        rows.append({
            "#":         int(r["rank"]),
            "Brand":     r["brand_name"],
            "Category":  r["category"],
            "Score":     float(r["icp_score"]),
            "Reach":     float(r["creator_reach_score"]),
            "Ecosystem": float(r["creator_ecosystem_score"]),
            "Intent":    float(r["content_intent_score"]),
            "Cat. Fit":  float(r["category_fit_score"]),
            "Creators":  int(r["unique_creators"]),
            "Views":     int(r["total_views"]),
        })

    disp = pd.DataFrame(rows)

    st.dataframe(
        disp,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                help="ICP Readiness Score (0–100)\n\n≥ 70 → Hot Lead\n≥ 40 → Warm Lead\n< 40 → Low Priority",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
            "Reach": st.column_config.NumberColumn(
                "Reach",
                help="Creator Reach · max 30 pts\n\nTotal views on creator content over 90 days, "
                     "converted to a percentile score vs. all brands in the cohort.",
                format="%.1f",
            ),
            "Ecosystem": st.column_config.NumberColumn(
                "Ecosystem",
                help="Creator Ecosystem · max 25 pts\n\nUnique creators posting about the brand "
                     "(percentile) plus a log-scaled bonus for viral breakout potential "
                     "(top video ÷ average views).",
                format="%.1f",
            ),
            "Intent": st.column_config.NumberColumn(
                "Content Intent",
                help="Content Intent · max 25 pts\n\nAbsolute score — not relative to peers.\n"
                     "60% from % of video titles containing review/haul keywords.\n"
                     "40% from purchase language density in comments.\n\n"
                     "Zero on both = total score capped at 60.",
                format="%.1f",
            ),
            "Cat. Fit": st.column_config.NumberColumn(
                "Category Fit",
                help="Category Fit · max 20 pts\n\nFixed Zelf ICP multiplier by category:\n"
                     "Beauty / Food / Personal Care → 20 pts (1.0×)\n"
                     "Beverage → 16 pts (0.8×)\n"
                     "Household → 12 pts (0.6×)\n"
                     "Pet Care → 8 pts (0.4×)",
                format="%.1f",
            ),
            "Creators": st.column_config.NumberColumn(
                "Creators",
                help="Unique creator channels that posted about this brand in the last 90 days. "
                     "The brand's own channel is excluded.",
            ),
            "Views": st.column_config.NumberColumn(
                "Views",
                help="Total views across all creator videos mentioning the brand in the last 90 days.",
                format="%d",
            ),
        },
        height=560,
        hide_index=True,
        use_container_width=True,
    )

    csv = disp.to_csv(index=False)
    st.download_button("Export CSV", csv, "zelf_icp_scores.csv", "text/csv")


# ── Tab 2: Explore ────────────────────────────────────────────────────────────
with tab_explore:
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Opportunity Matrix**")
        st.caption("Hover a bubble for details · size = creator count · dashed lines = median")

        fig = px.scatter(
            filtered_df,
            x="creator_reach_score",
            y="content_intent_score",
            size="unique_creators",
            color="category",
            hover_name="brand_name",
            hover_data={
                "icp_score": ":.1f",
                "unique_creators": True,
                "creator_reach_score": False,
                "content_intent_score": False,
            },
            size_max=36,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig.add_hline(y=filtered_df["content_intent_score"].median(),
                      line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.add_vline(x=filtered_df["creator_reach_score"].median(),
                      line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.update_layout(
            **PLOTLY_LAYOUT,
            xaxis_title="Creator Reach Score",
            yaxis_title="Content Intent Score",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=11)),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.markdown("**Top 15 by ICP Score**")
        st.caption("Green ≥ 70 · Indigo ≥ 40 · Gray < 40")

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
            hovertemplate="%{y}: %{x:.1f}<extra></extra>",
        ))
        fig.update_layout(
            **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")},
            xaxis=dict(range=[0, 108], showgrid=False, showticklabels=False, zeroline=False),
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
        hovertemplate="%{y}: %{x:.1f}<extra></extra>",
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")},
        xaxis=dict(range=[0, 108], showgrid=False, showticklabels=False, zeroline=False),
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

        # ── Header ────────────────────────────────────────────────────────────
        hcol, scol = st.columns([5, 1])
        with hcol:
            st.markdown(f"### {selected}")
            tier_class = (
                "tier-hot"  if row["icp_score"] >= 70 else
                "tier-warm" if row["icp_score"] >= 40 else
                "tier-low"
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
        if row["review_intent_ratio"] == 0 and row["purchase_intent_score"] == 0:
            st.markdown(
                '<div style="background:#fef9c3;border:1px solid #fde68a;border-radius:6px;'
                'padding:8px 14px;font-size:12px;color:#92400e;margin:10px 0">'
                '⚑ Intent gate applied — no creator intent signals detected; score capped at 60'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        left, right = st.columns([1, 1])

        # ── Radar ─────────────────────────────────────────────────────────────
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
                    radialaxis=dict(visible=True, range=[0, 1], showticklabels=False,
                                    gridcolor="#f1f5f9", linecolor="#f1f5f9"),
                    angularaxis=dict(gridcolor="#f1f5f9", linecolor="#f1f5f9"),
                ),
                showlegend=False, height=300,
                margin=dict(t=16, b=16, l=48, r=48),
                paper_bgcolor="rgba(0,0,0,0)",
                font_family="Inter",
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Score bars with contextual quality labels ─────────────────────────
        with right:
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            fit_mult = CATEGORY_FIT.get(row["category"], 0.3)

            dim_configs = [
                (
                    "Creator Reach",
                    "creator_reach_score", "creator_reach",
                    f"{format_number(int(row['total_views']))} views · {int(row['total_videos'])} videos",
                ),
                (
                    "Ecosystem",
                    "creator_ecosystem_score", "creator_ecosystem",
                    f"{int(row['unique_creators'])} creators · {row['breakout_ratio']:.1f}× breakout",
                ),
                (
                    "Content Intent",
                    "content_intent_score", "content_intent",
                    f"{row['review_intent_ratio']*100:.0f}% review titles · "
                    f"{row['purchase_intent_score']:.2f} purchase score",
                ),
                (
                    "Category Fit",
                    "category_fit_score", "category_fit",
                    f"{row['category']} · {fit_mult:.1f}× multiplier",
                ),
            ]

            bars_html = ""
            for label, score_col, weight_key, signal in dim_configs:
                val = row[score_col]
                mx  = SCORING_WEIGHTS[weight_key]
                pct = val / mx if mx else 0
                q_label, q_color = _quality(pct)
                bar_color = (
                    "#6366f1" if pct > 0.65
                    else "#a5b4fc" if pct > 0.35
                    else "#e2e8f0"
                )
                bars_html += f"""
<div style="margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:10px;font-weight:700;color:#374151;letter-spacing:.08em;text-transform:uppercase">{label}</span>
    <span>
      <span style="font-size:11px;font-weight:600;color:{q_color};margin-right:8px">{q_label}</span>
      <span style="font-size:13px;font-weight:700;color:#0f172a">{val:.1f}</span>
      <span style="font-size:11px;color:#cbd5e1"> / {mx}</span>
    </span>
  </div>
  <div style="font-size:11px;color:#94a3b8;margin-bottom:6px">{signal}</div>
  <div style="background:#f1f5f9;border-radius:99px;height:4px">
    <div style="background:{bar_color};border-radius:99px;height:4px;width:{pct*100:.0f}%"></div>
  </div>
</div>"""

            st.markdown(bars_html, unsafe_allow_html=True)

        # ── Evidence trail ────────────────────────────────────────────────────
        m_raw   = brand_platforms.get(selected, {}).get("youtube", {})
        evidence = m_raw.get("evidence") or {}

        if evidence:
            with st.expander("Evidence trail — see what produced each signal"):
                ev_cols = st.columns(2)

                with ev_cols[0]:
                    # Breakout video
                    tv = evidence.get("top_video")
                    if tv:
                        st.markdown(
                            f'<div style="margin-bottom:16px">'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">Breakout video</div>'
                            f'<div style="font-size:13px;color:#0f172a;font-weight:500;margin-bottom:2px">'
                            f'<a href="{tv["url"]}" target="_blank" style="color:#6366f1;text-decoration:none">{tv["title"]}</a>'
                            f'</div>'
                            f'<div style="font-size:12px;color:#64748b">{tv["channel"]} · {format_number(tv["views"])} views</div>'
                            f'<div style="font-size:11px;color:#94a3b8;margin-top:2px">'
                            f'{format_number(tv["views"])} ÷ {format_number(m_raw.get("avg_views", 0))} avg = {row["breakout_ratio"]:.1f}× ratio'
                            f'</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    # Top creators
                    creators = evidence.get("top_creators") or []
                    if creators:
                        st.markdown(
                            f'<div style="margin-bottom:16px">'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">Creator channels sampled</div>'
                            f'<div style="font-size:12px;color:#374151;line-height:1.8">'
                            + "".join(
                                f'<span style="background:#f1f5f9;padding:2px 8px;border-radius:99px;margin:2px 4px 2px 0;display:inline-block;font-size:11px">{c}</span>'
                                for c in creators
                            )
                            + f'{"&nbsp;<span style=\\'font-size:11px;color:#94a3b8\\'>+ more</span>" if row["unique_creators"] > len(creators) else ""}'
                            + f'</div></div>',
                            unsafe_allow_html=True,
                        )

                with ev_cols[1]:
                    # Review-matched titles
                    rtitles = evidence.get("sample_review_titles") or []
                    n_review = int(row["review_intent_ratio"] * int(row["total_videos"]))
                    if rtitles:
                        items = "".join(
                            f'<li style="margin-bottom:4px;color:#374151">{t}</li>'
                            for t in rtitles
                        )
                        st.markdown(
                            f'<div style="margin-bottom:16px">'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">'
                            f'Review-keyword titles ({n_review} of {int(row["total_videos"])})'
                            f'</div>'
                            f'<ul style="margin:0;padding-left:16px;font-size:12px;line-height:1.6">{items}</ul>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div style="font-size:12px;color:#94a3b8">No review-keyword titles found in this sample.</div>',
                            unsafe_allow_html=True,
                        )

                    # Purchase-intent comments
                    pcomments = evidence.get("sample_purchase_comments") or []
                    n_comments = m_raw.get("total_comments", 0)
                    if pcomments:
                        items = "".join(
                            f'<li style="margin-bottom:6px;color:#374151;font-style:italic">"{c}"</li>'
                            for c in pcomments
                        )
                        st.markdown(
                            f'<div>'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">'
                            f'Purchase-intent comments (from top video)'
                            f'</div>'
                            f'<ul style="margin:0;padding-left:16px;font-size:12px;line-height:1.6">{items}</ul>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div style="font-size:12px;color:#94a3b8">No purchase-intent comments found in sample.</div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.caption("Evidence not available for this brand — refresh data to collect it.")

        # ── Raw stats ─────────────────────────────────────────────────────────
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Videos Found",     format_number(row["total_videos"]),
                   help="Total YouTube videos found mentioning this brand in the last 90 days.")
        sc2.metric("Total Views",      format_number(row["total_views"]),
                   help="Sum of views across all creator videos. Drives the Creator Reach score.")
        sc3.metric("Unique Creators",  int(row["unique_creators"]),
                   help="Distinct creator channels that posted about this brand. Brand's own channel excluded.")
        sc4.metric("Breakout Ratio",   f"{row['breakout_ratio']:.1f}×",
                   help="Top video views ÷ average video views. A high ratio means one video is going viral.")

        # ── Sales Signal ──────────────────────────────────────────────────────
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


# ── Tab 4: Raw Data ───────────────────────────────────────────────────────────
with tab_raw:
    # Build raw metrics dataframe from brand_platforms
    raw_rows = []
    for _, r in filtered_df.iterrows():
        m = brand_platforms.get(r["brand_name"], {}).get("youtube", {})
        raw_rows.append({
            "Brand":           r["brand_name"],
            "Category":        r["category"],
            "Videos":          int(m.get("videos_last_90d", 0)),
            "Total Views":     int(m.get("total_views", 0)),
            "Avg Views":       int(m.get("avg_views", 0)),
            "Total Likes":     int(m.get("total_likes", 0)),
            "Total Comments":  int(m.get("total_comments", 0)),
            "Eng. Rate":       float(m.get("engagement_rate", 0.0)),
            "Creators":        int(m.get("unique_creators", 0)),
            "Breakout Ratio":  float(m.get("breakout_ratio", 0.0)),
            "Review Intent %": round(float(m.get("review_intent_ratio", 0.0)) * 100, 1),
            "Purchase Score":  float(m.get("purchase_intent_score", 0.0)),
        })

    raw_df = pd.DataFrame(raw_rows)

    # ── Table ─────────────────────────────────────────────────────────────────
    st.dataframe(
        raw_df,
        column_config={
            "Total Views": st.column_config.NumberColumn(
                "Total Views",
                help="Sum of views across all creator videos in the last 90 days.",
                format="%d",
            ),
            "Avg Views": st.column_config.NumberColumn(
                "Avg Views",
                help="Mean views per video. Used as the denominator in breakout ratio.",
                format="%d",
            ),
            "Eng. Rate": st.column_config.NumberColumn(
                "Eng. Rate",
                help="(likes + comments) ÷ views on the top 5 videos.",
                format="%.4f",
            ),
            "Breakout Ratio": st.column_config.NumberColumn(
                "Breakout Ratio",
                help="Top video views ÷ avg video views. Higher = one video going viral.",
                format="%.1f",
            ),
            "Review Intent %": st.column_config.NumberColumn(
                "Review Intent %",
                help="% of video titles containing keywords: review, haul, routine, unboxing, honest, try, tested…",
                format="%.1f",
            ),
            "Purchase Score": st.column_config.NumberColumn(
                "Purchase Score",
                help="Fraction of comments on the top video containing purchase language: bought, ordered, need this, use code…",
                format="%.3f",
            ),
        },
        height=480,
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    ca, cb = st.columns(2)

    with ca:
        st.markdown("**Views vs. Creator Count**")
        st.caption("Raw reach signal — how much view volume per creator")
        fig = px.scatter(
            raw_df,
            x="Creators",
            y="Total Views",
            color="Category",
            hover_name="Brand",
            hover_data={"Total Views": True, "Creators": True,
                        "Breakout Ratio": ":.1f", "Category": False},
            color_discrete_sequence=px.colors.qualitative.Pastel,
            log_y=True,
        )
        fig.update_layout(
            **PLOTLY_LAYOUT,
            xaxis_title="Unique Creators",
            yaxis_title="Total Views (log scale)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=11)),
            height=340,
        )
        st.plotly_chart(fig, use_container_width=True)

    with cb:
        st.markdown("**Review Intent vs. Purchase Score**")
        st.caption("Intent signal — what % of titles are review-driven vs. comment buy-language")
        fig = px.scatter(
            raw_df,
            x="Review Intent %",
            y="Purchase Score",
            color="Category",
            hover_name="Brand",
            size="Creators",
            size_max=28,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig.update_layout(
            **PLOTLY_LAYOUT,
            xaxis_title="Review Intent %",
            yaxis_title="Purchase Score",
            showlegend=False,
            height=340,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Breakout ratio bar
    st.markdown("**Breakout Ratio by Brand**")
    st.caption("Top video ÷ avg views — measures viral potential within a brand's creator content")
    br_sorted = raw_df.sort_values("Breakout Ratio", ascending=True)
    fig = go.Figure(go.Bar(
        x=br_sorted["Breakout Ratio"],
        y=br_sorted["Brand"],
        orientation="h",
        marker_color=[
            "#6366f1" if v >= 10 else "#a5b4fc" if v >= 4 else "#e2e8f0"
            for v in br_sorted["Breakout Ratio"]
        ],
        text=br_sorted["Breakout Ratio"].apply(lambda v: f"{v:.1f}×"),
        textposition="outside",
        textfont=dict(size=10, color="#64748b"),
        hovertemplate="%{y}: %{x:.1f}×<extra></extra>",
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")},
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11)),
        height=max(320, len(br_sorted) * 22),
        margin=dict(t=16, b=16, l=120, r=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Download
    st.download_button(
        "Export Raw Data CSV",
        raw_df.to_csv(index=False),
        "zelf_raw_metrics.csv",
        "text/csv",
    )
