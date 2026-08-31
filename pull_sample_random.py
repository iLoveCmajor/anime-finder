"""Spread sample across the AniList catalog (sorted by ID, not
popularity) to check whether data quality/sequel-density findings from
the top-50-popular sample hold up for a representative slice."""

import json
import time
import urllib.request

URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, isAdult: false, sort: ID) {
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

# Spread across the catalog: page 1 (oldest IDs) through page 1500
# (perPage 50 => offset 75000), covering old to newer entries, not
# just what's popular.
PAGES = [1, 30, 80, 150, 250, 400, 600, 900, 1200, 1500]


def fetch_page(page, per_page=50):
    body = json.dumps({"query": QUERY, "variables": {"page": page, "perPage": per_page}}).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "curl/8.0",
    }
    req = urllib.request.Request(URL, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)["data"]["Page"]["media"]


def main():
    items = []
    for page in PAGES:
        try:
            batch = fetch_page(page)
            items.extend(batch)
            print(f"page {page}: {len(batch)} items (first id={batch[0]['id'] if batch else None})")
        except Exception as e:
            print(f"page {page}: FAILED ({e})")
        time.sleep(1.5)

    with open("project/data_sample_random.json", "w") as f:
        json.dump(items, f, indent=2)

    print(f"\nPulled {len(items)} items -> project/data_sample_random.json")


if __name__ == "__main__":
    main()
