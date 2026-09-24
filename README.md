# HF Model Finder

Describe the ML task you want to solve in plain English and get matched to a pretrained model on the Hugging Face Hub. An LLM explains why the model fits and gives its exact id, ready for `from_pretrained(...)`.

**What's in it:**

- **A resumable, 5-stage ingestion pipeline for the Hub.** It narrows 10,000 models to 3,613, with a drop count for every filter ([details](#ingestion-ingestpy)).
- **An embedding design built around the embedder's 128-token limit.** Each model gets a dedicated `embed_text`, and an ablation shows it beats embedding the raw card ([why](#why-a-separate-embed_text), [Experiment E](#what-to-embed-experiment-e)).
- **Evaluation end to end, not just retrieval.** Keyword, vector and hybrid search, query rewriting and prompt variants are compared, and an LLM judge accepts equally valid alternative models ([results](#evaluation)).
- **Operations:** a monitoring dashboard, Docker Compose, a Minikube deployment, and tests with CI.

Built on material from [LLM Zoomcamp](https://github.com/DataTalksClub/llm-zoomcamp): the [minsearch](https://github.com/alexeygrigorev/minsearch) search library, the `evaluation_utils.py` helpers, and the basic RAG flow (search → prompt → LLM). Everything else here is original work. The project started as the course capstone, on a different subject (finding anime from a half-remembered plot), and was then repositioned to model search. The data source, prompts and every evaluation result were redone for it.

## The problem

The Hugging Face Hub hosts over a million models. Its search matches on model names and filters, so it helps when you already know what you're looking for ("whisper", "bert-base-german"). It doesn't help with "transcribe German phone calls on a CPU-only server" or "spot drug and chemical names in biomedical papers". General-purpose chatbots will answer those questions, but often from stale knowledge and sometimes with model ids that don't exist.

This app does semantic search over ~3,600 curated model cards, then has an LLM pick the best-matching candidate and explain the choice using only what the retrieved cards say. The answer always ends with an exact model id from the Hub snapshot.

## How it works

```
HF Hub API  ->  ingest.py (5 stages)  ->  data/models.jsonl  (3,613 models, cleaned + filtered)
                                                 |
                                                 v
                                        embedder.py (ONNX, local, free)
                                                 |
                                                 v
                                   minsearch.VectorSearch  (in-memory vector index)
                                                 |
                             query  ------------>|-------- retrieve top-5 candidates
                                                 |
                                                 v
                                   rag_helper.RAGBase  (LLM picks one model + explains)
                                                 |
                                                 v
                                        Streamlit app (app.py)
                                                 |
                                                 v
                             SQLite (conversations + feedback)  ->  dashboard.py
```

### Ingestion (`ingest.py`)

Model metadata and model cards arrive through different API calls, so ingestion runs in five stages. Each stage writes its output to disk, so a crash or rate limit costs nothing on rerun.

1. **Sweep.** One `HfApi().list_models()` call fetches metadata for the 10,000 most-downloaded public models: task, library, tags, license, languages, downloads and parameter count. It takes about 10 seconds. Gated repos (e.g. Llama) are excluded server-side with `gated=False`, because a recommendation you can't download without approval is not useful.
2. **Metadata filters.** These drop:

   | Reason | Dropped | Why |
   |---|---|---|
   | no task (`pipeline_tag`) | 1,985 | can't say what the model is for |
   | quantized / format variants | 2,368 | GGUF/AWQ/GPTQ/MLX/FP8 copies of other models, detected from the repo id, library and tags |
   | per-author cap (25) | 1,477 | one org alone had 507 near-identical NER models in the top 10k |
   | test / dummy repos | 210 | `tiny-random-*`, `*-test`, internal testing orgs |
   | re-upload orgs | 130 | accounts that mirror other people's models |

   Quantized copies aren't detected from the Hub's own `baseModels.relation` field, because it's unreliable: it labels `sentence-transformers/all-MiniLM-L6-v2` as "quantized".
3. **Card fetch.** For each of the ~3,960 remaining models, the README is fetched with `ModelCard.load()` on 8 threads, at about 13 cards/s without a token. Each card is appended to `data/raw_cards.jsonl` as it arrives, and a rerun skips ids already saved. Repos with no README (404) are recorded and never retried; network errors are retried on the next run.
4. **Clean.** The Markdown/HTML is stripped of comments, code blocks, badges, images, tables and URLs, and links are unwrapped. Cards are dropped if they have no README (58), are mostly `[More Information Needed]` placeholders (48), or contain no usable prose at all (111).
5. **Build.** Tags are split into structured fields: license, languages, datasets, base models, and the remaining topic tags. Two texts are built per model:
   - `card_text`: the cleaned card capped at 2,000 characters, shown to the LLM and in the UI.
   - `embed_text`: what the embedder actually sees, explained below.

Kept: **3,613 of 10,000**, across 54 tasks. The largest are text generation (912), vision-language (279), sentence embeddings (248), text classification (227), speech recognition (218) and masked-language encoders (204). Per-run stats are written to `data/ingest_stats.json`.

### Why a separate `embed_text`

The embedding model (`all-MiniLM-L6-v2`) truncates input at **128 tokens**, about 100 words. A model card's first 100 words are usually a title, badges and links, so embedding the raw card mostly embeds noise. `embed_text` packs the signal into that window instead: a plain-language description of the task, then library, languages, up to 8 topic tags, and the card's first real prose paragraph.

The task description matters more than it looks. Bare tag names embed almost identically when they share words, so before this was added, "transcribe English speech to text" retrieved only text-to-speech models. Descriptions that spell out the direction ("transcribes spoken audio into written text", "reads written text aloud") fixed it. Experiment E below measures this.

### The rest of the pipeline

- **Embeddings**: [ONNX Runtime](https://onnxruntime.ai/) runs `Xenova/all-MiniLM-L6-v2` locally (`embedder.py`), with no API calls and no cost.
- **Retrieval**: [minsearch](https://github.com/alexeygrigorev/minsearch)'s `VectorSearch`, an in-memory vector index. It was compared against keyword search, hybrid search and query rewriting; see below.
- **Answer generation**: `rag_helper.RAGBase` retrieves 5 candidates and builds a prompt from their id, task, library, license, languages, parameter count, downloads and card excerpt. It asks an LLM (`gpt-5.4-mini` via OpenAI) to pick exactly one model and justify it. The answer ends with `ANSWER: <model id>`, copied exactly from the candidates. When none of the candidates fits, the LLM still picks the closest one but has to say so.
- **Interface**: a Streamlit chat app (`app.py`). Example tasks in the sidebar run with one click. Each answer comes with the retrieved candidates (Hub link, metadata, card excerpt; the picked one is marked) and thumbs up/down feedback.
- **Monitoring**: every query, answer and response time is logged to SQLite (`db.py`). A separate Streamlit dashboard (`dashboard.py`) shows usage, response times, feedback and the most recommended models.

## Dataset & scope

The corpus is a **curated snapshot of popular models**, not the whole Hub:

- **Popularity bias.** It includes only models from the top 10,000 by downloads. The least-downloaded kept model had ~6,200 downloads in the last 30 days. The app is good at finding well-established options and won't know brand-new or niche models. If a very specific query gets a weak match, the model most likely isn't in the corpus, rather than retrieval having failed.
- **30-day window.** The Hub sorts by rolling 30-day downloads; sorting by all-time downloads is rejected by the API. So *which* models make the cut depends on when `ingest.py` runs, and re-running it later gives a somewhat different corpus. All-time downloads are stored and shown alongside the 30-day count. The exact corpus used for every number in this README is published as the Hugging Face dataset [`ilovecmajor/hf-model-finder-snapshot`](https://huggingface.co/datasets/ilovecmajor/hf-model-finder-snapshot).
- **Deliberate exclusions.** Gated models, quantized copies and more than 25 models per author are left out. The app recommends an original model; you choose your own quantization.

## Evaluation

All numbers come from `evaluation.ipynb`, run on the 2026-09-24 corpus published as [`ilovecmajor/hf-model-finder-snapshot`](https://huggingface.co/datasets/ilovecmajor/hf-model-finder-snapshot). They were produced fresh for this dataset: results from the anime version of this project were not carried over. To reproduce them, download that corpus with `uv run python ingest.py --from-snapshot` instead of running a fresh ingest. The retrieval numbers then come out exactly the same; the judge and rewrite numbers call an LLM, so they vary slightly between runs.

### Ground truth (Experiment A)

For 100 randomly sampled models, an LLM wrote 3 search queries each that someone who needs *that* model might type, giving 300 (query, model) pairs. Generation cost $0.08.

- **No name leakage.** Queries may not mention the model id, org, model family or architecture names (Qwen, BERT, Whisper, CLIP...) or dataset names. Otherwise retrieval becomes a trivial name lookup.
- **Several right answers.** Unlike looking up one specific item, "English sentiment classifier" has many valid models. Queries combine the task with the model's distinguishing traits (domain, language, size) to keep the exact-id metric meaningful. Two task-level metrics are reported alongside it: whether a model of the right task appears in the top 5 (**task hit**), and whether the top result has the right task (**task@1**).

### Retrieval: three methods compared (Experiment B)

| Method | Hit rate | MRR | Task hit | Task@1 |
|---|---|---|---|---|
| Keyword | 0.270 | 0.178 | 0.663 | 0.490 |
| **Vector (shipped)** | 0.297 | 0.195 | **0.897** | **0.763** |
| Hybrid (RRF) | **0.337** | **0.221** | 0.863 | 0.583 |

- **Keyword search is competitive.** Model queries share exact vocabulary with model cards ("NER", "Bengali", "toxic").
- **Hybrid finds the exact model most often.** Sweeping RRF's `k` from 1 to 60 barely changes it, so this isn't a tuning artifact.
- **Vector puts a model of the right task first far more often.** Keyword matches drag wrong-task models into the top ranks.

This is a real trade-off, so it was settled end to end in Experiment C.

### What to embed (Experiment E)

| Text embedded per model | Hit rate | MRR | Task hit | Task@1 |
|---|---|---|---|---|
| Raw card | 0.287 | 0.184 | 0.887 | 0.683 |
| **`embed_text` (shipped)** | 0.297 | 0.195 | **0.897** | 0.763 |
| `embed_text`, bare task tag | 0.270 | 0.171 | 0.883 | 0.740 |
| Metadata only (no prose) | 0.180 | 0.115 | 0.770 | 0.647 |
| Name words + `embed_text` | **0.310** | **0.208** | 0.883 | **0.770** |

- **Plain-language task descriptions beat bare tag names on every metric.**
- **Card prose carries most of the signal.** Metadata alone is clearly worst.
- **Raw cards rank the right task first much less often.** Their first 128 tokens are mostly titles and badges.
- **Adding the repo name's words gains 4 queries out of 300.** That's within noise, and task hit rate drops slightly, so it isn't shipped.

### LLM output: prompts and retrieval, judged end to end (Experiment C)

An offline LLM judge (`judge.py`) checks whether the final answer recommends the ground-truth model, **or a different model that satisfies every constraint in the query at least as well**. The same 50 sampled queries were used for each configuration:

| Configuration | Good (n=50) | Cost for 50 answers |
|---|---|---|
| Open-ended prompt (may list several) + vector | 62% | $0.162 |
| **Forced single pick + vector (shipped)** | **68%** | $0.117 |
| Forced single pick + hybrid | **68%** | $0.112 |

- **Hybrid's exact-id edge doesn't reach the final answer.** Both retrieval methods tie at 34/50, so the simpler vector search ships, with no keyword index in the app.
- **The forced single pick is 3 queries ahead of the open-ended prompt.** That's within noise at this sample size. It ships because it's ~27% cheaper and its parseable `ANSWER:` line feeds the dashboard's "most recommended model" chart.
- **Exact-id hit rate understates quality.** At least 4 of the shipped configuration's 34 "good" verdicts were equally valid alternatives to the ground-truth model, such as another English financial-sentiment classifier.

### Query rewriting: evaluated, not shipped (Experiment D)

`query_rewrite.py` has an LLM rewrite the user's query into model-card vocabulary before retrieval: a short phrase, not a paragraph. For example, "lightweight entity extraction model for many languages" becomes "multilingual token classification / named entity recognition lightweight model".

| Method | Hit rate | MRR | Task hit | Task@1 |
|---|---|---|---|---|
| **Vector (shipped)** | **0.297** | **0.195** | **0.897** | 0.763 |
| Vector + rewrite | 0.270 | 0.175 | 0.867 | **0.770** |
| Hybrid | 0.337 | 0.221 | 0.863 | 0.583 |
| Hybrid + rewrite | 0.300 | 0.204 | 0.857 | 0.677 |

Rewriting slightly hurts, and it costs an extra LLM round trip per query. An earlier run showed rewriting *helping* task@1 (0.743 → 0.780), before `embed_text` carried task descriptions. Moving that everyday-words-to-ML-task-name translation to the index side made the rewrite redundant, at no cost per query.

## Running it

### Locally

```bash
uv sync
cp .env.example .env         # add your OPENAI_API_KEY
uv run python download.py    # one-time: fetches the ONNX embedding model (~90MB)
uv run python ingest.py      # one-time: pulls + filters a fresh Hub snapshot (~5-10 min)
                             #   or: ingest.py --from-snapshot  (the published corpus, seconds)
make run                     # the app, http://localhost:8501
make dashboard               # the dashboard, http://localhost:8502 (separate terminal)
```

`ingest.py` resumes where it stopped if interrupted. It reuses the saved metadata sweep; pass `--refresh` to pull a fresh one. The first app launch embeds all 3,613 models (~40s) and caches the result to `data/model_embeddings.npy`. Later launches load the cache, which is rebuilt automatically whenever any model's `embed_text` changes.

Only the offline steps (`ingest.py`, `download.py`, `scripts/pull_sample.py`) use `huggingface-hub` directly, so it's declared in an `ingest` dependency group (installed by `uv sync` by default) rather than as a runtime dependency. The running app never calls the Hub.

### With Docker

```bash
cp .env.example .env        # add your OPENAI_API_KEY
uv run python download.py && uv run python ingest.py   # generate data/models locally first - see note below
make docker-up               # app: localhost:8501, dashboard: localhost:8502
make docker-down
```

The Docker image bakes in `data/` and `models/` at build time, so containers start fast and never call the Hub at runtime. Run the ingestion and download steps locally once, before `docker compose build` picks them up. The raw ingest dumps are excluded from the build context. The app and dashboard run as separate containers sharing a Docker volume for the SQLite monitoring database, so feedback given in the app immediately shows up in the dashboard.

### With Kubernetes

The same app runs on Minikube from 8 hand-written manifests in [`k8s/`](k8s/), with no Helm or Kustomize so each primitive stays visible:
- Namespace and ConfigMap
- Secret (created imperatively from `.env`, never committed)
- PVC
- two Deployments + Services (app + dashboard, sharing one PVC-backed SQLite file so feedback syncs between them)
- an optional Ingress for host-based routing (`make k8s-ingress`, not part of the default apply)

It was built as a Kubernetes learning exercise on top of this project.

Prerequisites are the same as "With Docker" above: a populated `.env` and `data/`/`models/` generated locally, so `k8s-build` has something to bake into the image.

```bash
minikube start --driver=docker --cpus=4 --memory=6g
make k8s-build && make k8s-apply
make k8s-status         # verify: both Deployments 1/1, PVC Bound
make k8s-open-app       # opens the app — minikube service, no sudo/hosts-file needed
make k8s-open-dashboard # opens the dashboard the same way
```

Full design writeup (shared-SQLite tradeoff, secrets handling, optional Ingress path) in [`k8s/README.md`](k8s/README.md).

## Project structure

```
ingest.py              - 5-stage HF Hub ingestion: sweep, filter, fetch cards, clean, build
scripts/pull_sample.py  - quick HF Hub pilot pull used to explore the data before ingest.py
download.py              - fetches the ONNX embedding model
embedder.py               - ONNX embedding wrapper (encode/encode_batch)
rag_helper.py              - RAGBase: search -> build_context -> build_prompt -> llm -> rag
search_backends.py          - adapts VectorSearch to RAGBase's search() interface
query_rewrite.py              - LLM query rewriting + RewritingVectorIndexAdapter
                                 (evaluated, not shipped)
evaluation_utils.py             - structured-output + parallel-eval helpers (from the course)
judge.py                          - offline LLM-as-judge for end-to-end answer quality
evaluation.ipynb                   - experiments A-E: ground truth, retrieval, embed text,
                                      prompt/retrieval judging, query rewriting
app.py                              - the Streamlit app
dashboard.py                         - the monitoring dashboard
db.py                                 - SQLite: conversations + feedback
k8s/                                   - Minikube manifests + design notes
```

## Feature map

| Area | Where |
|---|---|
| Problem it solves | This README, "The problem" |
| Retrieval + generation flow | "How it works": knowledge base + LLM |
| Ingestion pipeline | `ingest.py`; "Ingestion" above, with drop counts per filter |
| Retrieval evaluation | "Evaluation": Experiments B and E, with the best configuration shipped |
| LLM output evaluation | "Evaluation": Experiment C, prompt variants judged end to end |
| Interface | Streamlit app (`app.py`) |
| Monitoring | `db.py` + `dashboard.py`: user feedback collected, dashboard with 5 charts |
| Containerization | `docker-compose.yml`: app + dashboard |
| Reproducibility | `uv.lock` pins dependencies; the evaluated corpus is published as [`ilovecmajor/hf-model-finder-snapshot`](https://huggingface.co/datasets/ilovecmajor/hf-model-finder-snapshot) (`ingest.py --from-snapshot`, pinned to one revision) together with the committed `data/ground_truth.csv`, so the retrieval numbers reproduce exactly; `ingest.py` builds a fresh corpus |
| Hybrid search | Experiment B/C: evaluated, not shipped (tied end to end, vector is simpler) |
| Query rewriting | Experiment D: evaluated, not shipped (slightly worse retrieval, extra latency) |
| Kubernetes deployment | "With Kubernetes": `k8s/` manifests; `make k8s-apply`, then `make k8s-status` and `make k8s-open-app` to verify |

## Data source & attribution

Model metadata and model cards come from the [Hugging Face Hub](https://huggingface.co/) through its public API (`huggingface_hub`). Model cards are written by each model's authors and remain theirs. The app shows short cleaned excerpts and always links to the original model page. Check each model's own license (shown in the app) before using it. Used for non-commercial, educational purposes.
