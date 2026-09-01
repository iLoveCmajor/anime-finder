"""Ingestion script: pull the top 5000 non-adult anime by popularity
from AniList, clean the text, filter out low-signal/junk entries, and
save the result as JSONL.

Stdlib only, no dependencies needed.
"""

import html
import json
import re
import time
import urllib.error
import urllib.request

URL = "https://graphql.anilist.co"
PER_PAGE = 50
PAGES = 100  # 100 * 50 = 5000, AniList's per-query pagination cap

MIN_DESCRIPTION_LEN = 150
MIN_TAG_COUNT = 5

OUT_PATH = "data/anime.jsonl"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, isAdult: false, sort: POPULARITY_DESC) {
      id
      title { romaji english }
      description
      genres
      tags { name isMediaSpoiler }
      episodes
      seasonYear
      format
      status
      averageScore
      popularity
      studios(isMain: true) { nodes { name } }
      relations {
        edges {
          relationType
          node { id type }
        }
      }
    }
  }
}
"""

HTML_TAG_RE = re.compile(r"<[^>]+>")


def fetch_page(page, retries=3):
    body = json.dumps({"query": QUERY, "variables": {"page": page, "perPage": PER_PAGE}}).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "curl/8.0",
    }
    req = urllib.request.Request(URL, data=body, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)["data"]["Page"]["media"]
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            wait = 5 * (attempt + 1)
            print(f"  page {page} failed ({e}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"page {page} failed after {retries} retries")


def clean_description(raw):
    if not raw:
        return ""
    text = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def passes_quality_filter(description, tags):
    return len(description) >= MIN_DESCRIPTION_LEN and len(tags) >= MIN_TAG_COUNT


def transform(item):
    description = clean_description(item.get("description"))
    tags = [t["name"] for t in item.get("tags", []) if not t.get("isMediaSpoiler")]
    studios = [s["name"] for s in item.get("studios", {}).get("nodes", [])]
    relations = [
        {"type": e["relationType"], "id": e["node"]["id"], "media_type": e["node"]["type"]}
        for e in item.get("relations", {}).get("edges", [])
    ]

    return {
        "id": item["id"],
        "title_romaji": item["title"]["romaji"],
        "title_english": item["title"].get("english"),
        "description": description,
        "genres": item.get("genres", []),
        "tags": tags,
        "episodes": item.get("episodes"),
        "year": item.get("seasonYear"),
        "format": item.get("format"),
        "status": item.get("status"),
        "score": item.get("averageScore"),
        "popularity": item.get("popularity"),
        "studios": studios,
        "relations": relations,
    }, tags


def main():
    kept = []
    dropped = 0

    for page in range(1, PAGES + 1):
        batch = fetch_page(page)
        if not batch:
            print(f"page {page}: empty, stopping early")
            break

        for raw_item in batch:
            record, tags = transform(raw_item)
            if passes_quality_filter(record["description"], tags):
                kept.append(record)
            else:
                dropped += 1

        print(f"page {page}/{PAGES}: kept {len(kept)} so far, dropped {dropped} so far")
        time.sleep(1.0)

    with open(OUT_PATH, "w") as f:
        for record in kept:
            f.write(json.dumps(record) + "\n")

    print(f"\nDone. Kept {len(kept)}, dropped {dropped} (junk/thin entries). Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
