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
| Retrieval eval | Synthetic query-per-title, hit rate / MRR — **done, 3 methods compared, vector wins** (see below) | — |
| LLM eval | LLM-as-judge on a couple of prompt variants | More variants / approaches compared |
| Interface | Streamlit: text box -> ranked results + explanation | — |
| Monitoring | Thumbs up/down feedback + small dashboard | 5+ chart dashboard |
| Containerization | Single Dockerfile for the app | Full docker-compose |
| Best practices bonus | — | Hybrid search, reranking, query rewriting |
| Cloud bonus | — | Deploy on Streamlit Community Cloud (free, cheap bonus points) |

## Retrieval evaluation: done (2026-09-03) — vector search wins

Built keyword search (`minsearch.Index`, with `genres`/`tags` joined
into string fields since `Index` needs plain strings, not lists),
vector search (`minsearch.VectorSearch` + ONNX `Embedder`,
`Xenova/all-MiniLM-L6-v2`), and hybrid search (manual RRF fusion of
the two, per `06-best-practices/lessons/02-hybrid-search.md`).

**Ground truth**: OpenAI structured output (`Questions` Pydantic
model, `responses.parse`) generating 3 plot-description queries per
anime, explicitly instructed not to leak the title/proper nouns/exact
synopsis wording. Ran on a random sample of 100 anime (out of 4313) ->
300 ground truth (query, anime_id) pairs, cost $0.069. Sample size is
a cost/time lever, not a corpus-coverage decision — full-corpus
ground truth remains cheap to generate later if needed (~$3,
~15-20 min estimated), not required for picking a winner now.

**Results** (`hit_rate`/`mrr` at num_results=5, course's standard
functions):

| Method | Hit rate | MRR |
|---|---|---|
| Keyword | 0.217 | 0.120 |
| Vector | 0.323 | **0.230** |
| Hybrid (RRF, k=1) | **0.333** | 0.198 |

Swept RRF's `k` parameter (1, 5, 10, 20, 60) to check whether hybrid's
MRR deficit was a tuning artifact: hit rate stayed flat at 0.333 for
every `k`, MRR only moved 0.198 -> 0.201 before plateauing at k=5.
Confirms this is a structural fusion effect (diluting vector's sharp
top-1 placements by blending in the much-weaker keyword list), not
something a different `k` fixes.

**Decision: vector search is the app's default retrieval method.**
Hybrid's hit-rate edge over vector is tiny (~1pp, ~3 documents out of
300) while its MRR is meaningfully worse (~16% relative), and the app
experience (LLM explaining the top 1-2 matches) cares more about
ranking quality than raw top-5 recall. Vector is also simpler — no
fusion logic to maintain. Keyword search alone is clearly worst, as
expected, since ground-truth queries deliberately avoid literal
synopsis/title wording.

Note on absolute numbers: 22-33% hit rate is expected, not a red flag.
The course's own FAQ eval hit ~93% because those synthetic questions
paraphrased answers closely; ours were deliberately adversarial
(no title/proper-noun leakage), and the course's own caveat applies —
ground truth assumes exactly one correct answer per query, but a vague
query like "post-apocalyptic anime, humanity behind walls" could
plausibly fit more than one title, so some "misses" aren't necessarily
real retrieval failures.

This satisfies the rubric's retrieval-eval criterion at the 2-point
level (multiple approaches compared, best one used) and the
best-practices bonus's hybrid-search item (evaluated, even though not
the one shipped).

## RAG assembly: done (2026-09-03)

`rag_helper.py`'s `RAGBase` (course Module 1 shape, adapted for anime
records) wired to vector search via `search_backends.py`'s
`VectorIndexAdapter` (bridges `VectorSearch`'s vector-input `.search()`
to `RAGBase`'s plain-string-query interface — embeds the query, then
calls `vindex.search(...)`).

Manually spot-checked 4 varied queries end-to-end (magical girl,
mecha, workplace romance, locked-room mystery). Results are grounded
in retrieved synopses (cites specific plot details, doesn't
hallucinate), ranks/explains multiple candidates when several are
plausible, and — importantly — is honest when no candidate is a great
fit ("none of the candidates explicitly mention locked-room murders,
so I can't claim a perfect match") rather than forcing a confident
wrong answer. Good enough to move forward as-is.

## LLM output evaluation: done (2026-09-03) — precise/single-answer variant wins

Built `judge.py`: an offline LLM-as-judge (`AnswerEvaluation` Pydantic
model, per `04-evaluation/lessons/13-llm-as-judge.md`), adapted since
we don't have gold-standard free-text answers like the course's FAQ
does — instead it judges whether the RAG answer surfaces the
known-correct anime title (from the Phase B ground truth) as a strong
match.

Compared two `RAGBase` instruction variants on a random sample of 30
of the 300 ground-truth queries:
- **v1** (original): open-ended, allowed hedging/listing multiple
  candidates, could say "no good match"
- **v2**: forced exactly one pick, ending with a parseable
  `ANSWER: <title>` line, brief justification first

Results: v1 46.7% good (14/30), v2 43.3% good (13/30) — a 1-query
difference, well within noise at n=30, not a real quality gap. v2 was
~13% cheaper ($0.0187 vs $0.0214) due to shorter, more constrained
output.

**Decision: v2.** Quality is statistically tied, so picked on
practical grounds — cheaper, and the `ANSWER:` line is parseable,
which matters for Phase F (monitoring/dashboard) and any future UI
work that wants to highlight the top pick without regexing free-form
prose. `rag_helper.py`'s default `INSTRUCTIONS` updated to v2.

Caveat worth remembering, not chasing down now: both variants' good
rates (43-47%) came in higher than Phase B's 32.3% vector-search hit
rate, which is odd since the RAG answer can only correctly recommend
something that was actually retrieved. Could be pure sampling noise
(n=30 has a wide confidence interval around 32%), or could mean the
judge sometimes rewards the LLM naming a famous anime from its own
pretrained knowledge rather than from grounded retrieval — a known
risk given our corpus skews toward globally iconic titles. Not
verified either way; flagged for awareness, not blocking.

## Interface: done (2026-09-03)

`app.py` — Streamlit UI: text input -> LLM recommendation (via
`RAGBase`) + expandable list of retrieved candidates (title, genres,
tags, synopsis) for transparency. `load_rag()` wrapped in
`@st.cache_resource` so the index only builds once per running
session.

Found and fixed during testing (browser-verified, not just read
through): a fresh process cold-start re-embedded all 4313 descriptions
every time (~2-3 min, since `@st.cache_resource` only helps *within*
one running process, not across restarts) — a real problem for local
dev restarts and for Phase G's Docker container. Fixed with a simple
disk cache (`data/embeddings.npy`, computed once, loaded thereafter).
Verified: first run after deleting the cache took the full ~50s-2min;
immediately after, a full process restart loaded near-instantly.

Manually tested end-to-end in a real browser: query -> grounded
recommendation with the `ANSWER:` line -> expandable candidates with
correct genres/tags/synopsis. Works.

## Monitoring: done (2026-09-03)

`db.py` — SQLite (`data/monitoring.db`, gitignored), two tables:
`conversations` (query, answer, response_time, timestamp) and
`feedback` (conversation_id, source, score, relevance, explanation,
timestamp) — same shape as the course's Postgres schema, just SQLite,
per the course's own note that "for a lightweight project, SQLite plus
a Streamlit dashboard is a perfectly good place to stop."

`app.py` updated: logs every query/answer/response-time to
`conversations`, adds thumbs up/down buttons (`db.save_feedback`).
Fixed a rough edge found while wiring this up: the recommendation was
only rendered inside the `if st.button("Search")` block, so clicking a
feedback button (which reruns the whole script) made the answer
disappear. Fixed by rendering from `st.session_state` instead, so the
answer + candidates persist across the feedback-button rerun.

`dashboard.py` (separate app, `make dashboard`, port 8502): 4 summary
metrics + 5 charts (conversations over time, response time over time,
response time distribution, user feedback up/down, most-recommended
anime — parsed from the `ANSWER:` line the Phase D prompt variant
already produces) + a recent-conversations list. Satisfies the
5+-chart threshold for full monitoring points.

Browser-tested end-to-end: ran 2 real queries through the app, gave
one thumbs up and one thumbs down, confirmed both persisted and all
5 charts + metrics rendered correctly against that real data. Test
data cleared afterward (`data/monitoring.db` deleted) so the app
starts fresh.

Not done (optional per plan, skipped for time): wiring in the online
LLM-as-judge (`RelevanceVerdict`) as an automatic per-query signal
alongside user feedback. Feedback collection + 5-chart dashboard alone
already satisfies the rubric's monitoring criterion at full points.

## Containerization: done (2026-09-03) — docker-compose, full 2/2

Went straight to docker-compose (app + dashboard as two services)
rather than a single Dockerfile, after weighing it explicitly: a
single container is simpler/lower-risk as a first step, but caps the
containerization rubric item at 1/2 ("Dockerfile for main app OR
compose for deps only"). Compose isn't actually much harder once the
shared-state problem is solved, and it's the idiomatic Docker pattern
anyway (one process per container) rather than running two Streamlit
servers inside one container. Gets the full 2/2.

- `Dockerfile`: single image (`python:3.12-slim`, `uv sync --locked
  --no-dev`), shared by both services via a different `command:` in
  compose. Moved `jupyter` into the `dev` dependency group first
  (`--no-dev` skips it) since it's local-dev-only and was adding
  significant unnecessary weight to the runtime image.
- **Key design point**: `data/anime.jsonl`, `data/embeddings.npy`, and
  `models/` are gitignored locally but get baked into the image via
  `COPY . .` regardless — `.gitignore` doesn't affect Docker's build
  context, only `.dockerignore` does, and ours deliberately does NOT
  exclude `data/`/`models/`. This avoids needing network access
  (AniList API + HuggingFace) at container build/start time.
- **SQLite needs its own path, separate from `data/`**: the
  monitoring db can't live inside `data/` alongside the baked-in
  files, because mounting a shared volume there for persistence would
  shadow (replace) the baked-in `anime.jsonl`/`embeddings.npy` with an
  empty volume. Fixed by making `db.py`'s `DB_PATH` an env-var
  override (`DB_PATH` env, defaults to `data/monitoring.db` for local
  dev unchanged), and pointing both containers at a separate named
  volume mounted at `/app/state` in `docker-compose.yml`.
- `.dockerignore` excludes `.venv`, `.git`, `.env` (never bake
  secrets into image layers), notebooks, and the old scratch JSON
  samples.
- `Makefile`: `make docker-up` / `make docker-down`.

Required installing Docker Desktop (wasn't present on this machine at
all) — on macOS, Docker always needs a Linux VM under the hood since
containers rely on Linux kernel features; a bare `docker-compose` CLI
package alone has no daemon to talk to. Colima was offered as a
lighter CLI-only alternative but user went with Docker Desktop.

Verified end-to-end, not just built: `docker compose up`, ran a real
query through the containerized app (fast — confirms the baked-in
embeddings cache worked inside the container too), then loaded the
dashboard container and confirmed it showed the same conversation
(`docker compose exec app ls /app/state/` + `docker volume ls`
confirmed `monitoring.db` lives in the shared named volume, proving
both containers actually read/write the same state). Cleaned up with
`docker compose down -v` afterward.

## Docs: done (2026-09-03)

Wrote `README.md` (was empty) and `.env.example`. Covers: problem
statement written for someone who didn't take the course, architecture
diagram, dataset/scope explanation with the popularity-drift
reproducibility caveat, both evaluation tables (retrieval methods, LLM
prompt variants) pulled straight from this file, local + Docker run
instructions, project structure (including a note on what
`pull_sample.py`/`pull_sample_random.py`/`data_sample*.json` are —
early exploration artifacts, not part of the running app), and an
explicit rubric self-assessment table so a reviewer can find what's
scored where without digging.

This closes out the original bare-pass-plus-docs plan (Phases A-H).
Current honest rubric total per the README's self-assessment: **18
points** (problem 2 + retrieval flow 2 + retrieval eval 2 + LLM eval 2
+ interface 2 + ingestion 1 + monitoring 2 + containerization 2 +
reproducibility 2 + hybrid-search bonus 1). Only ingestion is under
its max (1/2, stays there until dlt is done). Reranking, query
rewriting, and cloud deployment remain deferred per the saved rubric
table from the scope check-in — revisit that table next to decide
what, if anything, to pursue with remaining time before 2026-09-08.

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
