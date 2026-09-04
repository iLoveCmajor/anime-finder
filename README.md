# Anime Finder

Describe a plot, a vibe, or a half-remembered scene — get back the anime it's from.

Built as a capstone project for [LLM Zoomcamp](https://github.com/DataTalksClub/llm-zoomcamp). You don't need to have taken the course to read this; everything relevant is explained below.

## The problem

If you half-remember an anime — "the one where humanity lives behind giant walls because of man-eating monsters" — you can't search for it by title, because you don't know the title. Keyword search over plot summaries doesn't help much either: your description almost never uses the same words as the official synopsis. This app does semantic search over ~4,300 anime synopses, then has an LLM turn the best-matching candidates into a grounded recommendation with an explanation, so a vague description is enough to find the title.

## How it works

```
AniList API  ->  ingest.py  ->  data/anime.jsonl  (4,313 anime, cleaned + filtered)
                                       |
                                       v
                              embedder.py (ONNX, local, free)
                                       |
                                       v
                          minsearch.VectorSearch  (in-memory vector index)
                                       |
                    query  ---------->|-------- retrieve top-k candidates
                                       |
                                       v
                          rag_helper.RAGBase  (LLM picks + explains the best match)
                                       |
                                       v
                              Streamlit app (app.py)
                                       |
                                       v
                   SQLite (conversations + feedback)  ->  dashboard.py
```

- **Ingestion** (`ingest.py`): pulls the top 5,000 anime by popularity from the [AniList GraphQL API](https://anilist.co/graphiql) (a free, first-party API — no key needed), strips HTML from descriptions, drops spoiler-tagged tags, and filters out low-signal entries (DVD bonus episodes, music videos, etc. — anything under 150 characters of description or fewer than 5 tags). Kept 4,313 of 5,000 pulled.
- **Embeddings**: [ONNX Runtime](https://onnxruntime.ai/) running `Xenova/all-MiniLM-L6-v2` locally (`embedder.py`) — no API calls, no cost, ~33x smaller install than the equivalent `sentence-transformers` setup.
- **Retrieval**: [minsearch](https://github.com/alexeygrigorev/minsearch)'s `VectorSearch`, an in-memory vector index. Compared against keyword search and a hybrid (RRF fusion of both) — vector search won on evaluation, see below.
- **Answer generation**: `rag_helper.RAGBase` — retrieves candidates, builds a prompt grounded in their synopses/genres/tags, asks an LLM (`gpt-5.4-mini` via OpenAI) to pick and justify a single best match. Always commits to a pick (no listing multiple options as equally likely), but is instructed to say so honestly in its justification when none of the retrieved candidates are a good fit, rather than silently pretending a weak match is a strong one.
- **Interface**: a Streamlit app (`app.py`) — text box in, recommendation + expandable retrieved candidates out, thumbs up/down feedback.
- **Monitoring**: every query/answer/response-time is logged to SQLite (`db.py`); a separate Streamlit dashboard (`dashboard.py`) shows usage and feedback trends.

## Dataset & scope

The corpus is the **top 5,000 anime by AniList popularity**, not the full catalog (which is closer to 20,000+ titles). This was a deliberate choice: it fits inside a single AniList query (which caps at 5,000 results per query), it naturally filters out most low-quality/promotional entries, and it's still large enough for a meaningful demo across genres and decades (1969-2027 in the resulting corpus).

**Trade-off worth knowing**: this means the app is good at finding well-known anime, and won't have very obscure or extremely recent titles. Worth a mention if you try a very niche description and get no good match — the corpus doesn't contain it, not that retrieval failed.

**Reproducibility note**: AniList's popularity rankings can shift over time, so re-running `ingest.py` today vs. later could produce a slightly different top-5,000 set than the one this project was developed and evaluated against.

## Evaluation

### Retrieval: three methods compared

Built a synthetic ground-truth set: for 100 randomly sampled anime, asked an LLM to write 3 plot-description queries each — explicitly instructed to avoid the title, character names, or other identifying proper nouns — giving 300 (query, correct-anime) pairs. Scored keyword search, vector search, and hybrid (RRF fusion of both) against it with hit-rate and MRR (top-5):

| Method | Hit rate | MRR |
|---|---|---|
| Keyword | 0.217 | 0.120 |
| Vector | 0.323 | **0.230** |
| Hybrid (RRF) | **0.333** | 0.198 |

**Vector search won and is what ships.** Hybrid's hit-rate edge is tiny (~1 percentage point) while its MRR is meaningfully worse — confirmed not a tuning artifact by sweeping RRF's `k` parameter (hit rate stayed flat, MRR barely moved). Vector also avoids the extra fusion logic. Absolute numbers look low compared to typical FAQ-style RAG evaluations (~90%+) because the ground-truth queries were deliberately adversarial (no title/proper-noun leakage) — this is a much harder retrieval task by design.

### LLM output: two prompt variants compared

Built an offline LLM-as-judge that checks whether the generated answer surfaces the known-correct anime as a strong match. Compared an open-ended instruction style (hedges, allows listing multiple candidates) against a precise style (forces exactly one pick with a parseable `ANSWER: <title>` line):

| Variant | Good rate (n=30) | Cost |
|---|---|---|
| Open-ended | 46.7% | $0.0214 |
| Precise (shipped) | 43.3% | $0.0187 |

Quality is statistically tied at this sample size (a 1-query difference). The precise variant was chosen on practical grounds: ~13% cheaper, and the parseable `ANSWER:` line is what the monitoring dashboard's "most recommended anime" chart is built on.

### Query rewriting: evaluated, not shipped

Tried rewriting the user's query with an LLM before embedding it (`query_rewrite.py`, `search_backends.RewritingVectorIndexAdapter`) — expanding a short, casual description into fuller, more synopsis-like language before retrieval. Compared against plain vector search on the same ground truth:

| Method | Hit rate | MRR |
|---|---|---|
| Vector (shipped) | 0.293 | 0.223 |
| Vector + query rewrite | **0.197** | **0.146** |

This made retrieval clearly worse, not better. The ground-truth queries are deliberately short and sparse (see the retrieval evaluation above), and the rewrite step expands them into long, generic synopsis-style paragraphs that dilute the embedding — a short, specific phrase concentrates its vector on the few distinctive details that matter for matching; a longer, genericized paragraph averages across a lot of stock phrasing that doesn't correspond to how AniList actually writes synopses. `app.py` continues shipping plain vector search unchanged. Full spot-check examples and the evaluation run are in `evaluation.ipynb`.

## Running it

### Locally

```bash
uv sync
cp .env.example .env         # add your OPENAI_API_KEY
uv run python download.py    # one-time: fetches the ONNX embedding model (~90MB)
uv run python ingest.py      # one-time: pulls the dataset (~5-10 min)
make run                     # the app, http://localhost:8501
make dashboard                # the dashboard, http://localhost:8502 (separate terminal)
```

First app launch embeds all 4,313 descriptions (~1-2 min) and caches the result to `data/embeddings.npy`; every launch after that is near-instant.

### With Docker

```bash
cp .env.example .env        # add your OPENAI_API_KEY
uv run python download.py && uv run python ingest.py   # generate data/models locally first - see note below
make docker-up               # app: localhost:8501, dashboard: localhost:8502
make docker-down
```

The Docker image bakes in `data/` and `models/` at build time (so containers start instantly, with no AniList/HuggingFace dependency at runtime) — run the ingestion/download steps locally once before `docker compose build` picks them up. The app and dashboard run as separate containers sharing a Docker volume for the SQLite monitoring database, so feedback given in the app immediately shows up in the dashboard.

## Project structure

```
ingest.py              - pulls + cleans the AniList dataset
download.py             - fetches the ONNX embedding model
embedder.py              - ONNX embedding wrapper (encode/encode_batch)
rag_helper.py             - RAGBase: search -> build_context -> build_prompt -> llm -> rag
search_backends.py         - adapts VectorSearch to RAGBase's search() interface;
                              also has RewritingVectorIndexAdapter (evaluated, not shipped)
query_rewrite.py             - LLM query rewriting (evaluated, not shipped - see README)
evaluation_utils.py            - structured-output + parallel-eval helpers (from the course)
judge.py                     - offline LLM-as-judge for comparing prompt variants
evaluation.ipynb              - retrieval + LLM evaluation: ground truth generation,
                                 hit-rate/MRR comparison, prompt-variant comparison
app.py                          - the Streamlit app
dashboard.py                     - the monitoring dashboard
db.py                              - SQLite: conversations + feedback
pull_sample.py, pull_sample_random.py, data_sample*.json
                                     - early data-source exploration scripts, not part
                                       of the running app (kept for reference)
```

## Where to find each rubric item

| Criterion | Where |
|---|---|
| Problem description | This README, "The problem" |
| Retrieval flow | "How it works" — knowledge base + LLM |
| Retrieval evaluation | "Evaluation" — three methods compared, best one used |
| LLM evaluation | "Evaluation" — two prompt variants compared, best one used |
| Interface | Streamlit app (`app.py`) |
| Ingestion pipeline | `ingest.py` — semi-automated script |
| Monitoring | `db.py` + `dashboard.py` — user feedback collected + 5-chart dashboard |
| Containerization | `docker-compose.yml` — app + dashboard |
| Reproducibility | "Running it" — instructions, `uv.lock` for pinned deps, dataset regenerable via `ingest.py` |
| Best practices: hybrid search | "Evaluation" — evaluated in the retrieval comparison (not shipped, vector search won) |
| Best practices: query rewriting | "Evaluation" — evaluated (not shipped, made retrieval worse) |

## Data source & attribution

Anime metadata (titles, synopses, genres, tags, relations) from [AniList](https://anilist.co/) via its free public GraphQL API. Used for non-commercial, educational purposes.
