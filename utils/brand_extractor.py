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

Find every real CPG brand name mentioned across these titles.
Count how many titles each brand appears in (case-insensitive).

Rules:
- Include ONLY real brands sold in stores or online (e.g. CeraVe, Dove, Red Bull, OLIPOP, Tide, Doritos, Native, Gillette)
- Normalize to correct casing (cerave→CeraVe, ordinary→The Ordinary, elf→e.l.f., loreal→L'Oreal Paris)
- Exclude: generic words, adjectives, verbs, retailers (Amazon/Target/Walmart/Costco/Ulta), platforms (YouTube/TikTok)

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
    unique_titles = list(dict.fromkeys(t for t in titles if t.strip()))[:200]
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
                "max_tokens": 512,
            },
            timeout=30,
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
