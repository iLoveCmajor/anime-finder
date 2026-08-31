"""Quick test pull from AniList to eyeball data quality before building
the real ingestion pipeline. Stdlib only (no uv/venv set up yet)."""

import json
import time
import urllib.request

URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
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
      isAdult
      relations {
        edges {
          relationType
          node { id title { romaji } type }
        }
      }
    }
  }
}
"""


def fetch_page(page, per_page=25):
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
    for page in (1, 2):
        items.extend(fetch_page(page))
        time.sleep(1)  # be polite, AniList rate limit is ~90 req/min

    with open("project/data_sample.json", "w") as f:
        json.dump(items, f, indent=2)

    print(f"Pulled {len(items)} items -> project/data_sample.json")


if __name__ == "__main__":
    main()
