"""Extract CPG brand names from YouTube video titles using an LLM.

Sends raw titles to SambaNova (free tier) and asks it to identify real brand
names + count mentions. No regex, no stopwords — the LLM handles all filtering
and normalization (e.g. "ordinary" → "The Ordinary", "elf" → "e.l.f.").

Requires SAMBANOVA_API_KEY in environment or .env file.
"""

import json
import logging
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_SAMBANOVA_URL = "https://api.sambanova.ai/v1/chat/completions"
_MODEL = "Meta-Llama-3.3-70B-Instruct"

_SYSTEM = (
    "You are a CPG (consumer packaged goods) brand analyst. "
    "You identify real product brand names from social media content. "
    "You output only valid JSON, nothing else."
)

_PROMPT = """\
Below are YouTube video titles from the {category} category.

Find every real CPG product brand name mentioned across these titles.
Count how many titles each brand appears in (case-insensitive).

Rules:
- Include ONLY brands that manufacture and sell their own products (e.g. CeraVe, Dove, Red Bull, OLIPOP, Tide, Doritos, Native, Gillette, The Ordinary, Neutrogena)
- Normalize to correct casing (cerave→CeraVe, ordinary→The Ordinary, elf→e.l.f., loreal→L'Oreal Paris)
- EXCLUDE retailers and grocery stores — these are NOT brands: Amazon, Target, Walmart, Costco, Aldi, Lidl, Whole Foods, Trader Joe's, Erewhon, Hmart, Sprouts, Kroger, Ulta, Sephora, CVS, Walgreens
- EXCLUDE: generic words, adjectives, verbs, content creators, YouTube/TikTok, country/city names

Output ONLY valid JSON on a single line: {{"BrandName": mention_count, ...}}
If no real brands found, output: {{}}

Titles:
{titles}"""


def extract_brands_from_titles(titles: list[str], category: str) -> dict[str, int]:
    """Return {brand_name: mention_count} extracted by LLM from video titles.

    Falls back to empty dict on API failure (better than returning garbage).
    """
    if not titles:
        return {}

    api_key = os.environ.get("SAMBANOVA_API_KEY", "").strip()
    if not api_key:
        logger.warning("SAMBANOVA_API_KEY not set — brand extraction unavailable")
        return {}

    # Deduplicate and cap titles to avoid huge prompts
    unique_titles = list(dict.fromkeys(t for t in titles if t.strip()))[:400]
    titles_block = "\n".join(f"- {t}" for t in unique_titles)

    prompt = _PROMPT.format(category=category, titles=titles_block)

    try:
        resp = requests.post(
            _SAMBANOVA_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 2048,
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"SambaNova request failed for [{category}]: {e}")
        return {}

    # Parse JSON — try to extract even if the model wraps it in markdown
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        logger.warning(f"[{category}] LLM returned non-JSON: {raw[:120]}")
        return {}

    try:
        brands = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"[{category}] JSON parse error: {e} — raw: {raw[:120]}")
        return {}

    # Ensure values are ints and keys are non-empty strings
    return {
        str(k).strip(): int(v)
        for k, v in brands.items()
        if str(k).strip() and str(v).strip().isdigit()
    }


def is_video_about_brand(title: str, channel: str, brand_name: str, description: str = "") -> bool:
    """Return True if this video is primarily about the brand.

    Uses LLM to filter false positives — e.g. a song called "Rhodes" showing up
    for the brand "Rhode". Falls back to True on API failure so collection continues.
    """
    api_key = os.environ.get("SAMBANOVA_API_KEY", "").strip()
    if not api_key:
        return True  # no key → skip validation, accept all

    time.sleep(2)  # respect SambaNova free tier rate limit

    desc_line = f'Description (first 600 chars): "{description}"\n' if description else ""
    prompt = (
        f'YouTube video:\n'
        f'Title: "{title}"\n'
        f'Channel: "{channel}"\n'
        f'{desc_line}\n'
        f'Is this video primarily reviewing, featuring, or discussing the CPG brand "{brand_name}"?\n'
        f'Answer with a single JSON object: {{"about_brand": true}} or {{"about_brand": false}}'
    )

    for attempt in range(3):
        try:
            resp = requests.post(
                _SAMBANOVA_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a video classification assistant. Output only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 32,
                },
                timeout=15,
            )
            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
                return bool(result.get("about_brand", True))
            break
        except Exception as e:
            logger.warning(f"Video validation failed for '{title}': {e}")
            break

    return True  # on any failure, accept the video
