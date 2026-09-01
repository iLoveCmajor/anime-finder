# Capstone Project Plan — Anime Finder (working title)

Deadline: 2026-09-08.

## Idea

"Describe the anime, find the title." A semantic search / RAG app over
an anime knowledge base (synopsis, genres, tags, episode count, year,
studio). User describes a plot or vibe in natural language; the app
retrieves candidate titles and an LLM explains/ranks the match(es)
grounded in the retrieved data.

Chosen over alternatives considered: video games (too similar to
anime, less interesting), movies/TV via TMDb (same mechanics, less
distinctive), board games / recipes (interesting niche/practical
angles, kept as backup ideas if anime data turns out too thin).

## Data source: AniList (decided)

Compared Jikan (unofficial MyAnimeList API) vs. AniList GraphQL API by
pulling a live test sample (`pull_sample.py`, 50 popular titles ->
`data_sample.json`, both gitignored as scratch data).

- Jikan was returning 504s during testing (it scrapes MAL live, so
  it's dependent on MAL's own uptime) — not a reliable foundation.
- AniList is a first-party GraphQL API, responded cleanly. Needs a
  `User-Agent` header (default urllib UA gets a 403) but otherwise
  simple `POST` with a GraphQL query body.
- **Decision: use AniList.**

Sample findings (n=50, most-popular anime):

- `description`, `genres`, `tags`, `episodes`, `seasonYear`, `format`,
  `isAdult`, `averageScore`, and `relations` (typed edges like
  `SEQUEL`/`PREQUEL`/`ADAPTATION`/`SPIN_OFF`) are all present and
  populated — no missing descriptions in the sample.
- `isAdult: false` as a query-level filter works cleanly — adult
  content exclusion is a free one-line fix, not a data-cleaning
  problem. Resolves the NSFW open question from below with near-zero
  effort.
- Descriptions contain HTML tags (`<br>`, `<i>`, source credit lines)
  in 46/50 samples — need a strip/clean step before embedding.
- Descriptions: 278-1602 chars, median 615 — good length for
  embedding, not too short/sparse.
- Tags carry an `isMediaSpoiler` flag (270 spoiler-flagged tags found
  in this sample alone) — worth excluding spoiler tags from the
  searchable text so results don't spoil plot twists.
- 39/50 (78%) of this popularity-sorted sample have a SEQUEL/PREQUEL
  relation. This is a popularity-sample artifact (long-running
  franchises dominate the top of the popularity list), not
  necessarily representative of the full ~20k+ catalog, but it does
  mean the sequel/dedup question from below is worth revisiting once
  we pull the real, larger dataset rather than assuming it's rare.

## Broader (non-popularity) sample findings

The 50-item sample above was sorted by popularity, which turned out to
bias several of its stats. Pulled a second sample (`pull_sample_random.py`
-> `data_sample_random.json`, gitignored) sorted by ID instead, spanning
AniList's older/lower-ID catalog (ids ~1-9600, 150 items) to sanity-check
against a less curated slice.

- **Sequel/prequel ratio drops from 78% to 35%.** Confirms the earlier
  number was a popularity-sample artifact (long franchises dominate
  the top of the popularity list), not representative of the catalog
  as a whole. Still meaningful enough that dedup is a real question
  for later, just not as urgent as the first sample suggested.
- **The catalog has a long tail of low-signal junk entries** that a
  naive "pull everything" ingestion would include: DVD bonus episodes,
  OP/ED music videos, festival compilation specials, one-line remakes.
  Examples found: "Special episodes included in DVD volumes 1-4",
  "m-flo Loves Chara's animated music video for the song...", "Special
  episode 9.5." These have thin descriptions (as low as 16-90 chars,
  vs. ~520-615 median) and few or zero tags.
- **Fix: quality filter at ingestion time**, not full-catalog dedup.
  Require both a minimum description length (e.g. >=150 chars) and a
  minimum tag count (e.g. >=5) before including an entry. From the
  sample, this cleanly separates real narrative synopses from
  promotional/bonus-content noise without needing per-format
  allow/deny lists (format alone isn't a clean signal — junk shows up
  across OVA, SPECIAL, MOVIE, and TV_SHORT alike).
- **AniList caps pagination at a 5000-result window per query**
  ("Page depth exceeds maximum allowed for API requests (5000
  entries)" — confirmed by testing `page * perPage > 5000`). This
  matters for the real ingestion pipeline: a single unfiltered/sorted
  query can only reach the first 5000 matches. To pull the full
  catalog we'll need to partition the query into windows that each
  stay under that cap — `seasonYear` is the natural partition key
  (no single year has anywhere near 5000 anime), looping over years
  from ~1960-2026.

## Ingestion: done (2026-09-01)

`ingest.py` (stdlib only) pulls pages 1-100 (perPage 50) sorted by
popularity, cleans descriptions (strips HTML, unescapes entities,
normalizes whitespace), drops spoiler-flagged tags, and applies the
quality filter. Output: `data/anime.jsonl` (gitignored — regenerate
with `python3 ingest.py`, ~3 min).

Actual results, full 5000-item pull:

- **Kept 4313, dropped 687 (13.7%)** to the quality filter — in line
  with expectations from the sample.
- Description length: 150-5185 chars, median 520 (matches the sample).
- Tags per item: 5-57, mean 13.5.
- Format spread: mostly TV (2757) and MOVIE (600), rest OVA/ONA/
  SPECIAL/TV_SHORT (small MUSIC/None counts, negligible).
- Year range 1969-2027 (includes unreleased/upcoming titles - AniList
  lists these ahead of airing).
- **50% have a SEQUEL/PREQUEL relation** — higher than the 35%
  broader-catalog figure, as expected once we cut to popularity-only.
  Still deferred per Open decisions, but now confirmed as a real
  fraction of the actual corpus, not just a sample artifact.
- 0 duplicate ids.
- Spot-checked entries confirm real synopses, not junk, at the low
  end near the 150-char cutoff (worst case seen: an OVA description
  that opens with a promotional sentence but still has real plot
  content after it — an acceptable MVP tradeoff, not perfect).

## Corpus size: top 5000 by popularity (decided)

- Sort by `popularity`, pull `page*perPage <= 5000` — this fits inside
  AniList's 5000-result pagination cap in a single query loop, so we
  skip the `seasonYear`-partitioning workaround entirely. Simpler
  ingestion script, one less moving part under the deadline.
- Cheap either way (cents, minutes to embed), so the ceiling was never
  cost — 5000 is plenty of genre/decade diversity for a convincing
  demo and a meaningful retrieval eval, well beyond the course's own
  FAQ-corpus size.
- Popularity ordering doubles as a soft quality filter: the junk
  entries found in the broader sample (DVD bonus episodes, thin
  music-video blurbs) skew toward obscure/low-popularity titles, so
  top-5000-by-popularity should mostly dodge them. Still keep the
  description-length/tag-count check (see above) as a cheap safety
  net in case a few thin entries land in the top 5000 anyway.
- Trade-off, worth a line in the README as a documented scope choice:
  corpus is "well-known anime only" — a query describing a very
  obscure or brand-new title won't match anything.
- Note: this also means the sequel-dedup question resurfaces at full
  strength (popularity-sorted sets skew franchise-heavy, per the 78%
  finding above) — still deferred per the Open decisions below, but
  worth knowing this choice leans back toward the higher end of that
  range rather than the 35% broader-catalog figure.

## Why anime

- Free, well-documented data source with rich synopsis text out of
  the box: AniList GraphQL API (see decision above).
- Natural synthetic eval: ask an LLM to write a plot-description query
  for a known title (without leaking the title/proper nouns), then
  check whether retrieval surfaces that title back. Same hit-rate/MRR
  pattern as course Module 4, applied to a new corpus.
- Cheap to embed (a few thousand synopses, cents on OpenAI
  text-embedding-3-small or similar).

## Scope: bare-pass MVP first

Hit every scored rubric category (see `../../project.md`) at the 1-2
point level with minimum extra work. Only add bonus items after the
MVP works end to end.

| Criterion | MVP plan | Stretch (if time allows) |
|---|---|---|
| Knowledge base | Pull anime (title, synopsis, genres, tags, year, episodes) via Jikan/AniList, one-time snapshot | — |
| Ingestion | One script/notebook (semi-automated, 1pt) | dlt pipeline (2pts) |
| Retrieval + LLM | Embed synopses, vector search top-k, LLM explains/ranks match grounded in retrieved text | Agentic tool-call to extract structured filters (genre, year, episode count) + combine with semantic search |
| Retrieval eval | Synthetic query-per-title, hit rate / MRR, one method | Compare multiple retrieval approaches (e.g. add hybrid search) |
| LLM eval | LLM-as-judge on a couple of prompt variants | More variants / approaches compared |
| Interface | Streamlit: text box -> ranked results + explanation | — |
| Monitoring | Thumbs up/down feedback + small dashboard | 5+ chart dashboard |
| Containerization | Single Dockerfile for the app | Full docker-compose |
| Best practices bonus | — | Hybrid search, reranking, query rewriting |
| Cloud bonus | — | Deploy on Streamlit Community Cloud (free, cheap bonus points) |

## Open decisions

- **Adult/NSFW content — resolved.** `isAdult: false` at the query
  level, zero extra effort.
- **Junk/low-signal entries — resolved, filter at ingestion.**
  Require description length >=150 chars and tag count >=5 (see
  findings above).
- **Sequels/seasons — still deferred.** ~35% of a representative
  sample have a SEQUEL/PREQUEL relation. Real, but not urgent enough
  to design around yet — AniList's `relations` field already gives us
  typed franchise edges (SEQUEL/PREQUEL/ADAPTATION/SPIN_OFF/etc.) for
  free, so dedup is a cheap follow-up whenever it's actually needed,
  not a blocker now.
- **Rate limits**: no issue in practice with AniList (first-party API,
  handled fine with ~1.5s between requests in testing). Jikan's
  3 req/s limit is moot since we're not using Jikan.
- **Pagination windowing**: need `seasonYear`-partitioned queries for
  the real bulk ingestion, since a single query can't page past 5000
  results (see findings above). Not needed for further sampling, only
  for the full pull.

## Repo

Per course tips, this should end up in its own separate GitHub repo
with a meaningful title (not bundled into the course-following repo).
This `project/` directory is just the planning scratch space until
that split happens.
