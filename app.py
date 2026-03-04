import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd  # used only for st.dataframe display tables
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import BRANDS_CSV, SCORING_WEIGHTS, CATEGORY_FIT
from database.db import (
    init_db, get_all_metrics, upsert_scores,
    get_data_freshness, get_data_sources_summary,
)
from scoring.scorer import ICPScorer
from utils.helpers import format_number, score_tier, generate_why_zelf_blurb

st.set_page_config(
    page_title="Brand Signal",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
section[data-testid="stSidebar"] { display: none; }
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
def load_brands() -> list[dict]:
    with open(BRANDS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_all_data() -> tuple[list[dict], dict]:
    brands = load_brands()
    all_metrics = get_all_metrics()
    brand_platforms = {}
    for m in all_metrics:
        bn = m["brand_name"]
        if bn not in brand_platforms:
            brand_platforms[bn] = {}
        brand_platforms[bn][m["platform"]] = m["metrics"]
    return brands, brand_platforms


def score_all_brands() -> tuple[list[dict], int]:
    """Returns (brands, uncollected_count).

    Only brands with actual YouTube data are scored. Uncollected brands are
    excluded so they don't pollute the percentile distribution with zeros.
    """
    brands, brand_platforms = load_all_data()
    scorer = ICPScorer()

    collected, uncollected = [], []
    for brand in brands:
        entry = {
            "brand_name": brand["brand_name"],
            "category":   brand["category"],
            "platforms":  brand_platforms.get(brand["brand_name"], {}),
        }
        if brand_platforms.get(brand["brand_name"]):
            collected.append(entry)
        else:
            uncollected.append(brand["brand_name"])

    scored = scorer.score_brands(collected)
    if scored:
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
                "review_intent_ratio": r["review_intent_ratio"],
                "purchase_intent_score": r["purchase_intent_score"],
            }
            for r in scored
        ])
    return scored, len(uncollected)


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


# ── Data ──────────────────────────────────────────────────────────────────────
brands, uncollected_count = score_all_brands()

if not brands:
    st.info("No data yet — run `python scripts/collect.py` to collect it.")
    st.stop()

_, brand_platforms = load_all_data()
freshness = get_data_freshness()
sources   = get_data_sources_summary()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# Brand Signal")
st.markdown(
    "<span style='color:#64748b;font-size:15px'>"
    "Ranks CPG brands by organic creator activity — the leading signal for Zelf-readiness."
    "</span>",
    unsafe_allow_html=True,
)

if freshness:
    st.markdown(
        f'<div style="font-size:11px;color:#94a3b8;margin-bottom:8px">'
        f'Updated {freshness[:10]}</div>',
        unsafe_allow_html=True,
    )

# Methodology expander — collapsed by default, clean when opened
with st.expander("How scores are computed"):
    st.markdown("""
**Score = Creator Reach (30) + Ecosystem (25) + Content Intent (25) + Category Fit (20)**

| | Weight | Method | Signal |
|---|---|---|---|
| **Creator Reach** | 30 pts | Percentile vs. cohort | Total views on creator content · 90 days |
| **Ecosystem** | 25 pts | Percentile vs. cohort | Unique creators posting about the brand |
| **Content Intent** | 25 pts | Percentile vs. cohort | % of video titles containing review/haul keywords |
| **Category Fit** | 20 pts | Fixed multiplier | Beauty / Food / Personal Care → 20 · Beverage → 16 · Household → 12 · Pet → 8 |

**Intent gate:** if a brand has zero review intent (no review/haul/routine keywords in any title), total score is capped at 60 — high view volume alone isn't enough.
**Data:** YouTube · collected via yt-dlp (no API key) · brand's own channel excluded
""")

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── Summary strip ─────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)

hot     = [b for b in brands if b["icp_score"] >= 70]
avg     = sum(b["icp_score"] for b in brands) / len(brands)
cat_scores = defaultdict(list)
for b in brands:
    cat_scores[b["category"]].append(b["icp_score"])
top_cat = max(cat_scores, key=lambda c: sum(cat_scores[c]) / len(cat_scores[c])) if cat_scores else "—"

c1.metric("Brands", len(brands),
          help="Total brands with YouTube data collected.")
c2.metric("Hot Leads", len(hot),
          help="Brands scoring ≥ 70 — strong creator signal with meaningful creator activity.")
c3.metric("Avg Score", f"{avg:.0f}",
          help="Mean signal score across all brands.")
c4.metric("Top Category", top_cat,
          help="Category with the highest average signal score.")

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
tab_table, tab_explore, tab_detail, tab_raw, tab_about = st.tabs(["Ranking", "Explore", "Brand Deep Dive", "Raw Data", "About"])


# ── Tab 1: Ranking ────────────────────────────────────────────────────────────
with tab_table:
    disp = pd.DataFrame([
        {
            "#":         r["rank"],
            "Brand":     r["brand_name"],
            "Category":  r["category"],
            "Score":     float(r["icp_score"]),
            "Reach":     float(r["creator_reach_score"]),
            "Ecosystem": float(r["creator_ecosystem_score"]),
            "Intent":    float(r["content_intent_score"]),
            "Cat. Fit":  float(r["category_fit_score"]),
            "Creators":  int(r["unique_creators"]),
            "Views":     int(r["total_views"]),
        }
        for r in brands
    ])

    st.dataframe(
        disp,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                help="Brand Signal Score (0–100)\n\n≥ 70 → Hot Lead\n≥ 40 → Warm Lead\n< 40 → Low Priority",
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
                     "(percentile vs. cohort).",
                format="%.1f",
            ),
            "Intent": st.column_config.NumberColumn(
                "Content Intent",
                help="Content Intent · max 25 pts\n\nPercentile vs. cohort — ranks brands relative to each other.\n"
                     "% of video titles containing review/haul/routine keywords.\n"
                     "Purchase intent (comments) is shown in evidence but not scored — too noisy from 1 video.\n\n"
                     "Zero review intent = total score capped at 60 — high reach alone isn't a Zelf lead.",
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
        width="stretch",
    )

    st.download_button("Export CSV", disp.to_csv(index=False), "brand_signal_scores.csv", "text/csv")


# ── Tab 2: Explore ────────────────────────────────────────────────────────────
with tab_explore:
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Review Intent vs. Creator Count**")
        st.caption("Brands with many creators AND high review intent — the sweet spot for Zelf")

        fig = px.scatter(
            brands,
            x="unique_creators",
            y="review_intent_ratio",
            color="category",
            hover_name="brand_name",
            hover_data={
                "icp_score": ":.1f",
                "unique_creators": True,
                "review_intent_ratio": ":.2f",
            },
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        med_intent   = statistics.median(b["review_intent_ratio"] for b in brands)
        med_creators = statistics.median(b["unique_creators"] for b in brands)
        fig.add_hline(y=med_intent,   line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.add_vline(x=med_creators, line_dash="dot", line_color="#e2e8f0", line_width=1)
        fig.update_layout(
            **PLOTLY_LAYOUT,
            xaxis_title="Unique Creators",
            yaxis_title="Review Intent Ratio",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=11)),
            height=380,
        )
        st.plotly_chart(fig, width="stretch")

    with col_right:
        st.markdown("**Top 15 by Signal Score**")
        st.caption("Green ≥ 70 · Indigo ≥ 40 · Gray < 40")

        top15     = brands[:15]  # already sorted descending
        top15_asc = sorted(top15, key=lambda b: b["icp_score"])
        fig = go.Figure(go.Bar(
            x=[b["icp_score"] for b in top15_asc],
            y=[b["brand_name"] for b in top15_asc],
            orientation="h",
            marker_color=[
                "#059669" if b["icp_score"] >= 70 else "#6366f1" if b["icp_score"] >= 40 else "#e2e8f0"
                for b in top15_asc
            ],
            text=[round(b["icp_score"], 1) for b in top15_asc],
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
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Average ICP Score by Category**")
    cat_avgs = sorted(
        [
            {"category": c, "mean": sum(v) / len(v), "count": len(v)}
            for c, v in cat_scores.items()
        ],
        key=lambda x: x["mean"],
    )
    fig = go.Figure(go.Bar(
        x=[round(c["mean"], 1) for c in cat_avgs],
        y=[c["category"] for c in cat_avgs],
        orientation="h",
        marker_color="#6366f1",
        opacity=0.8,
        text=[f"{c['mean']:.0f}  ({c['count']} brands)" for c in cat_avgs],
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
    st.plotly_chart(fig, width="stretch")


# ── Tab 3: Brand Deep Dive ────────────────────────────────────────────────────
with tab_detail:
    brand_names = [b["brand_name"] for b in brands]
    selected = st.selectbox("Select brand", brand_names, label_visibility="collapsed")

    if selected:
        row  = next(b for b in brands if b["brand_name"] == selected)
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
            st.plotly_chart(fig, width="stretch")

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
                    f"{int(row['unique_creators'])} creators",
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
                    # Top video
                    tv = evidence.get("top_video")
                    if tv:
                        st.markdown(
                            f'<div style="margin-bottom:16px">'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">Top video</div>'
                            f'<div style="font-size:13px;color:#0f172a;font-weight:500;margin-bottom:2px">'
                            f'<a href="{tv["url"]}" target="_blank" style="color:#6366f1;text-decoration:none">{tv["title"]}</a>'
                            f'</div>'
                            f'<div style="font-size:12px;color:#64748b">{tv["channel"]} · {format_number(tv["views"])} views</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    # Top creators
                    creators = evidence.get("top_creators") or []
                    if creators:
                        import urllib.parse as _up
                        st.markdown(
                            f'<div style="margin-bottom:16px">'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">Creator channels sampled</div>'
                            f'<div style="font-size:12px;color:#374151;line-height:1.8">'
                            + "".join(
                                f'<a href="https://www.youtube.com/results?search_query={_up.quote(c)}" target="_blank" '
                                f'style="background:#f1f5f9;padding:2px 8px;border-radius:99px;margin:2px 4px 2px 0;display:inline-block;font-size:11px;color:#374151;text-decoration:none">{c}</a>'
                                for c in creators
                            )
                            + (f'&nbsp;<span style="font-size:11px;color:#94a3b8">+ more</span>' if row["unique_creators"] > len(creators) else "")
                            + f'</div></div>',
                            unsafe_allow_html=True,
                        )

                with ev_cols[1]:
                    # Review-matched titles
                    rvideos = evidence.get("sample_review_videos") or []
                    # fallback for old cached data that stored plain title strings
                    if rvideos and isinstance(rvideos[0], str):
                        rvideos = [{"id": None, "title": t} for t in rvideos]
                    n_review = int(row["review_intent_ratio"] * int(row["total_videos"]))
                    if rvideos:
                        items = "".join(
                            f'<li style="margin-bottom:4px;color:#374151">'
                            f'<a href="https://youtu.be/{v["id"]}" target="_blank" '
                            f'style="color:#374151;text-decoration:none" onmouseover="this.style.color=\'#6366f1\'" onmouseout="this.style.color=\'#374151\'">{v["title"]}</a>'
                            f'</li>'
                            if v.get("id") else
                            f'<li style="margin-bottom:4px;color:#374151">{v["title"]}</li>'
                            for v in rvideos
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
                    top_video_url = (evidence.get("top_video") or {}).get("url", "")
                    if pcomments:
                        label = (
                            f'Purchase-intent comments (<a href="{top_video_url}" target="_blank" '
                            f'style="color:#94a3b8;text-decoration:underline">from top video</a>)'
                            if top_video_url else "Purchase-intent comments (from top video)"
                        )
                        items = "".join(
                            f'<li style="margin-bottom:6px;color:#374151;font-style:italic">"{c}"</li>'
                            for c in pcomments
                        )
                        st.markdown(
                            f'<div>'
                            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">'
                            f'{label}'
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
        sc4.metric("Avg Views",        format_number(row.get("avg_views", row["total_views"] // max(row["total_videos"], 1))),
                   help="Average views per creator video.")

        # ── Sales Signal ──────────────────────────────────────────────────────
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        blurb_html = _md(generate_why_zelf_blurb(selected, row))
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
    raw_rows = [
        {
            "Brand":           r["brand_name"],
            "Category":        r["category"],
            "Videos":          int(brand_platforms.get(r["brand_name"], {}).get("youtube", {}).get("videos_last_90d", 0)),
            "Total Views":     int(r["total_views"]),
            "Avg Views":       int(brand_platforms.get(r["brand_name"], {}).get("youtube", {}).get("avg_views", 0)),
            "Total Likes":     int(r["total_likes"]),
            "Total Comments":  int(r["total_comments"]),
            "Eng. Rate":       float(r["avg_engagement_rate"]),
            "Creators":        int(r["unique_creators"]),
            "Review Intent %": round(float(r["review_intent_ratio"]) * 100, 1),
            "Purchase Score":  float(r["purchase_intent_score"]),
        }
        for r in brands
    ]
    raw_df = pd.DataFrame(raw_rows)

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
                help="Mean views per video.",
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
        width="stretch",
    )

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    ca, cb = st.columns(2)

    with ca:
        st.markdown("**Views vs. Creator Count**")
        st.caption("Raw reach signal — how much view volume per creator")
        fig = px.scatter(
            raw_rows,
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
        st.plotly_chart(fig, width="stretch")

    with cb:
        st.markdown("**Review Intent vs. Purchase Score**")
        st.caption("Intent signal — what % of titles are review-driven vs. comment buy-language")
        fig = px.scatter(
            raw_rows,
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
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Breakout Ratio by Brand**")
    st.caption("Top video ÷ avg views — measures viral potential within a brand's creator content")
    br_sorted = sorted(raw_rows, key=lambda r: r["Breakout Ratio"])
    fig = go.Figure(go.Bar(
        x=[r["Breakout Ratio"] for r in br_sorted],
        y=[r["Brand"] for r in br_sorted],
        orientation="h",
        marker_color=[
            "#6366f1" if r["Breakout Ratio"] >= 10 else "#a5b4fc" if r["Breakout Ratio"] >= 4 else "#e2e8f0"
            for r in br_sorted
        ],
        text=[f"{r['Breakout Ratio']:.1f}×" for r in br_sorted],
        textposition="outside",
        textfont=dict(size=10, color="#64748b"),
        hovertemplate="%{y}: %{x:.1f}×<extra></extra>",
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis", "margin")},
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11)),
        height=max(320, len(br_sorted) * 22),
        margin=dict(t=16, b=16, l=120, r=60),
    )
    st.plotly_chart(fig, width="stretch")

    st.download_button(
        "Export Raw Data CSV",
        raw_df.to_csv(index=False),
        "zelf_raw_metrics.csv",
        "text/csv",
    )


# ── Tab 5: About ──────────────────────────────────────────────────────────────
with tab_about:
    st.markdown("""
<div style="max-width:680px;margin:32px auto 0;font-size:15px;color:#374151;line-height:1.75">

<h2 style="font-size:22px;font-weight:700;color:#0f172a;margin-bottom:4px">What this tool is</h2>
<p style="color:#64748b;margin-top:0">A YouTube video activity monitor for CPG brands. It searches YouTube for each brand, collects what it finds, and presents it plainly.</p>
<p style="color:#64748b">This covers <strong>YouTube videos only</strong> — long-form reviews, hauls, routines. It does not cover TikTok, Instagram Reels, or YouTube Shorts as a distinct format. For many CPG brands today, a significant portion of organic creator activity happens on TikTok specifically. That data is not here.</p>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:12px">How brands are selected</h2>
<p>Brands are not hand-picked. They are discovered from YouTube content using this process:</p>
<ol style="padding-left:20px;margin:0 0 12px">
<li style="margin-bottom:8px">We run a set of category-specific YouTube searches — things like <em>"skincare routine review"</em>, <em>"snack haul taste test"</em>, <em>"energy drink review"</em> — and collect the video titles from the results.</li>
<li style="margin-bottom:8px">We send those titles to an LLM with the prompt: find every real CPG brand name mentioned across these titles, count how many titles each appears in, return nothing that is not a real brand.</li>
<li style="margin-bottom:8px">Brands that appear in enough titles are kept. Each brand is assigned to the category where it appeared most.</li>
</ol>
<p>The honest caveat: the search queries themselves are hand-written by us. We chose the categories and we chose the query phrasing. So the brands are organically surfaced from YouTube content, but the categories and search framing are ours. A brand that doesn't appear in our query results won't be discovered regardless of how much creator activity it has.</p>
<p>If discovery returns fewer than three brands for a category, we fall back to a hand-curated seed list for that category.</p>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:12px">How we collect data</h2>
<p>For each brand we run a YouTube search using <a href="https://github.com/yt-dlp/yt-dlp" style="color:#6366f1">yt-dlp</a> — no API key, no YouTube Data API, no quota limits. The search is sorted by upload date (most recent first).</p>
<p>YouTube returns up to 50 results. We then filter those for: videos older than 90 days, and videos from the brand's own channel. What remains is our dataset for that brand.</p>
<p>Sorting by recency means we are measuring what is happening now, which is the right framing for a sales tool — you want to call a brand when creators are actively posting about them, not when an old video happened to go viral.</p>
<p>For the <strong>top 5 videos by view count</strong> in that set, we make a second request to get like and comment counts. Everything else is derived from the flat search alone.</p>
<p>That is the entirety of our data collection.</p>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:12px">The four numbers we compute</h2>

<p><strong>Unique creators</strong><br>
The number of distinct channel names in our 50-result sample. If two videos came from the same channel, they count as one creator. This is a lower-bound estimate — we are only seeing 50 results.</p>

<p><strong>Total views</strong><br>
The sum of view counts across all collected videos. For large brands this dramatically undercounts reality. For smaller brands it is more representative.</p>

<p><strong>Review intent ratio</strong><br>
The percentage of video titles containing at least one of these words: <em>review, haul, routine, unboxing, unbox, try, tried, testing, tested, honest, worth it, first impression, reaction, comparison, vs</em>. This tells you whether creators are actively evaluating the brand versus casually mentioning it. It is a keyword match on the title — nothing more.</p>

<p><strong>Engagement rate</strong><br>
(likes + comments) ÷ views, computed only on the top 5 videos by view count. This is not the engagement rate across all creator content — it is specifically the top 5.</p>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:12px">What the ranking is</h2>
<p>Brands are ranked by an ICP score. That score is a weighted combination of the four numbers above, normalised within the current cohort. The weights are not validated against any outcome — they reflect a prior that creator count and reach matter more than content type or engagement. Treat the score as a sort order, not a prediction.</p>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<h2 style="font-size:18px;font-weight:700;color:#0f172a;margin-bottom:12px">What this tool cannot tell you</h2>
<ul style="padding-left:20px;margin:0">
<li style="margin-bottom:8px">Anything on TikTok, Instagram, or YouTube Shorts — this is YouTube long-form only</li>
<li style="margin-bottom:8px">Total YouTube activity — we see at most 50 videos per brand per search</li>
<li style="margin-bottom:8px">Whether any creator content is paid or organic</li>
<li style="margin-bottom:8px">Whether the brand is already aware of or working with these creators</li>
<li style="margin-bottom:8px">Whether viewers purchased anything</li>
<li style="margin-bottom:8px">Whether a brand is a good fit for Zelf — that is a sales judgement, not a data output</li>
</ul>

<hr style="border:none;border-top:1px solid #f1f5f9;margin:28px 0">

<p style="font-size:12px;color:#94a3b8">Data collected via yt-dlp · YouTube search only · 90-day lookback · 50 results per brand</p>

</div>
""", unsafe_allow_html=True)
