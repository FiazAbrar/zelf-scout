"""Helper script to look up YouTube channel IDs by channel name.

Usage:
    python scripts/find_channel_ids.py "CeraVe" "e.l.f. Cosmetics" "Doritos"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from googleapiclient.discovery import build
from config import YOUTUBE_API_KEY


def find_channel_id(query: str, api_key: str) -> list[dict]:
    service = build("youtube", "v3", developerKey=api_key)
    resp = service.search().list(
        part="snippet",
        q=query,
        type="channel",
        maxResults=3,
    ).execute()

    results = []
    for item in resp.get("items", []):
        results.append({
            "title": item["snippet"]["title"],
            "channel_id": item["snippet"]["channelId"],
            "description": item["snippet"]["description"][:100],
        })
    return results


def main():
    if not YOUTUBE_API_KEY:
        print("Error: Set YOUTUBE_API_KEY in .env")
        sys.exit(1)

    queries = sys.argv[1:] if len(sys.argv) > 1 else ["CeraVe"]

    for query in queries:
        print(f"\n--- {query} ---")
        results = find_channel_id(query, YOUTUBE_API_KEY)
        for r in results:
            print(f"  {r['title']}: {r['channel_id']}")
            print(f"    {r['description']}")


if __name__ == "__main__":
    main()
