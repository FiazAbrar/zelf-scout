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
    """Generate a 'Why this brand needs Zelf' blurb based on metrics."""
    score = row.get("icp_score", 0)
    category = row.get("category", "CPG")
    platforms = row.get("platforms_active", 0)
    total_videos = row.get("total_videos", row.get("total_shorts", 0))
    total_views = row.get("total_views", 0)

    parts = [f"**{brand_name}**"]

    # Creator ecosystem volume signal
    if total_videos > 100:
        parts.append(
            f"has a massive creator ecosystem — {format_number(total_videos)} videos "
            f"about this brand in the last 90 days across {platforms} platform{'s' if platforms != 1 else ''}"
        )
    elif total_videos > 20:
        parts.append(
            f"has an active creator ecosystem — {format_number(total_videos)} creator "
            f"videos about this brand in the last 90 days"
        )
    else:
        parts.append("has limited creator video activity around the brand right now")

    # Views signal
    if total_views > 10_000_000:
        parts.append(
            f"generating {format_number(total_views)} total views across creator content"
        )
    elif total_views > 1_000_000:
        parts.append(
            f"with {format_number(total_views)} total views on creator content"
        )

    # Category signal
    if category in ("Beauty & Skincare", "Food & Snacks", "Personal Care"):
        parts.append(
            f". As a {category} brand, they're in Zelf's core ICP — "
            "understanding what creators are saying about them can directly inform "
            "product strategy, influencer partnerships, and competitive positioning."
        )
    else:
        parts.append(
            f". As a {category} brand, Zelf can help them understand creator sentiment "
            "and benchmark their share of voice against competitors."
        )

    # Score-based recommendation
    if score >= 70:
        parts.append(
            " **Recommendation: Priority outreach.** High creator volume, strong engagement, "
            "and strong category fit — an ideal Zelf customer today."
        )
    elif score >= 40:
        parts.append(
            " **Recommendation: Nurture lead.** Growing creator presence — "
            "will benefit from Zelf as their social video ecosystem scales."
        )
    else:
        parts.append(
            " **Recommendation: Monitor.** Low creator video activity for now, "
            "but worth tracking as the brand grows its social presence."
        )

    return " ".join(parts)


def engagement_rate_fmt(rate: float) -> str:
    """Format engagement rate as percentage."""
    return f"{rate * 100:.2f}%"
