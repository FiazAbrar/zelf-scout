from config import CATEGORY_FIT

_HIGH_FIT_CATEGORIES = {k for k, v in CATEGORY_FIT.items() if v >= 1.0}


def format_number(n: int | float) -> str:
    """Format large numbers: 1200000 → '1.2M', 45300 → '45.3K'."""
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def score_color(score: float) -> str:
    """Return CSS color for score badge."""
    if score >= 70:
        return "#22c55e"  # green
    if score >= 40:
        return "#eab308"  # yellow
    return "#ef4444"  # red


def score_tier(score: float) -> str:
    """Return tier label for a score."""
    if score >= 70:
        return "Hot Lead"
    if score >= 40:
        return "Warm Lead"
    return "Low Priority"


def score_badge_html(score: float) -> str:
    """Return an HTML badge for a score."""
    color = score_color(score)
    return (
        f'<span style="background-color:{color};color:white;padding:2px 8px;'
        f'border-radius:12px;font-weight:bold;font-size:14px;">'
        f'{score:.0f}</span>'
    )


def platform_badges_html(platforms: dict) -> str:
    """Return HTML badges for active platforms with data source indicators."""
    icons = {"youtube": "YT", "tiktok": "TT", "instagram": "IG"}
    source_colors = {
        "live_api": "#3b82f6",
        "cache": "#8b5cf6",
        "sample": "#6b7280",
        "unavailable": "#d1d5db",
    }
    badges = []
    for platform, metrics in platforms.items():
        source = metrics.get("data_source", "unavailable")
        color = source_colors.get(source, "#d1d5db")
        icon = icons.get(platform, platform[:2].upper())
        text_color = "white" if source != "unavailable" else "#9ca3af"
        badges.append(
            f'<span style="background-color:{color};color:{text_color};'
            f'padding:1px 6px;border-radius:4px;font-size:11px;margin-right:2px;">'
            f'{icon}</span>'
        )
    return " ".join(badges)


def generate_why_zelf_blurb(brand_name: str, row: dict) -> str:
    """Sharp, data-specific sales insight for a brand."""
    score              = row.get("icp_score", 0)
    category           = row.get("category", "CPG")
    total_views        = row.get("total_views", 0)
    total_videos       = row.get("total_videos", 0)
    unique_creators    = int(row.get("unique_creators", 0))
    breakout_ratio     = row.get("breakout_ratio", 0.0)
    review_intent      = row.get("review_intent_ratio", 0.0)
    purchase_intent    = row.get("purchase_intent_score", 0.0)
    reach_score        = row.get("creator_reach_score", 0)
    intent_score       = row.get("content_intent_score", 0)

    lines = []

    # ── Lead signal ───────────────────────────────────────────────────────────
    if score >= 70:
        if unique_creators >= 30:
            lines.append(
                f"**{unique_creators} independent creators** published about {brand_name} "
                f"in the last 90 days — that level of organic coverage is rare and usually "
                f"precedes a spike in consumer demand."
            )
        else:
            lines.append(
                f"{brand_name} is generating **{format_number(total_views)} views** from "
                f"creator content with strong intent signals — the ecosystem is small but loud."
            )
    elif unique_creators > 0:
        lines.append(
            f"{unique_creators} creators covered {brand_name} in the last 90 days, "
            f"accumulating **{format_number(total_views)} views**."
        )
    else:
        lines.append(
            f"Creator data for {brand_name} is thin right now — "
            f"either the brand is early-stage or the category search didn't surface much."
        )

    # ── Intent gap analysis ───────────────────────────────────────────────────
    if review_intent > 0.3 and purchase_intent < 0.05:
        lines.append(
            f"Creators are actively reviewing it — {review_intent*100:.0f}% of titles "
            f"are intent-driven — but comment sections show almost no purchase signals. "
            f"That gap is exactly what Zelf closes: understanding *why* viewers aren't converting."
        )
    elif review_intent > 0.2 and purchase_intent > 0.1:
        lines.append(
            f"Strong two-sided intent: {review_intent*100:.0f}% review-titled content "
            f"and real purchase language in the comments. Their audience is ready to buy — "
            f"they just need better visibility into who those creators are."
        )
    elif review_intent > 0 and purchase_intent == 0:
        lines.append(
            f"Creators mention it but audiences aren't reacting with purchase intent. "
            f"Could be a brand awareness play that hasn't converted — Zelf can help them figure out why."
        )

    # ── Breakout / viral signal ────────────────────────────────────────────────
    if breakout_ratio > 8:
        lines.append(
            f"One video is pulling **{breakout_ratio:.0f}× the average views** — "
            f"a breakout that their team probably doesn't know is happening."
        )
    elif breakout_ratio > 4:
        lines.append(
            f"Viral potential is real: top video is {breakout_ratio:.1f}× the average, "
            f"suggesting the category is receptive to a hit piece."
        )

    # ── Category + recommendation ─────────────────────────────────────────────
    if score >= 70:
        if category in _HIGH_FIT_CATEGORIES:
            lines.append(
                f"**Call this week.** {category} is Zelf's core market and "
                f"{brand_name} has the creator volume to make the ROI obvious in the first demo."
            )
        else:
            lines.append(
                f"**Worth a call.** {category} isn't Zelf's primary vertical but the "
                f"creator footprint is large enough that the value prop translates."
            )
    elif score >= 40:
        if reach_score > 20:
            lines.append(
                f"The reach is there — **{format_number(total_views)} views** is a real number. "
                f"Intent is the gap. Nurture until their creator program matures, "
                f"then they'll be an easy close."
            )
        else:
            lines.append(
                f"Early-stage creator ecosystem. Come back in a quarter — "
                f"if the trend holds this becomes a strong lead."
            )
    else:
        lines.append(
            f"Not the right time. Creator footprint is too small to make the pitch land. "
            f"Flag for re-evaluation if the brand raises or launches a new product line."
        )

    return "\n\n".join(lines)


def engagement_rate_fmt(rate: float) -> str:
    """Format engagement rate as percentage."""
    return f"{rate * 100:.2f}%"
