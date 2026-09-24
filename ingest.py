"""Ingestion script: pull the most-downloaded public models from the
Hugging Face Hub, fetch and clean their README model cards, filter out
low-signal/duplicate entries, and save the result as JSONL.

Five stages, each with its output on disk so a crash or rate limit costs
nothing on rerun:

  1. sweep     list_models() metadata for the top RAW_PULL models by downloads
               -> data/raw_models.jsonl (reused on rerun; pass --refresh to re-pull)
  2. metadata  drop models with no task, quantized/format variants, test repos,
               re-upload orgs; cap models per author
  3. cards     ModelCard.load() per surviving model, threaded, appended one per
               line -> data/raw_cards.jsonl (resumable: fetched ids are skipped)
  4. clean     strip Markdown/HTML noise; drop missing, placeholder and
               prose-less cards
  5. build     structure tags, build card_text + embed_text -> data/models.jsonl

Run with: uv run python ingest.py [--refresh]
"""

import collections
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from huggingface_hub import HfApi, ModelCard
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError
from huggingface_hub.utils import disable_progress_bars, logging as hf_logging

RAW_PULL = 10_000
AUTHOR_CAP = 25
CARD_THREADS = 8
CARD_RETRIES = 3

CARD_TEXT_MAX = 2000
EMBED_TEXT_MAX = 600
MIN_PROSE_LEN = 80
PLACEHOLDER = "[More Information Needed]"
MAX_PLACEHOLDERS = 5

# Quantized / format-converted copies of another model. Matched on the id (and
# library_name below), NOT on baseModels.relation, which the Hub mislabels
# (e.g. sentence-transformers/all-MiniLM-L6-v2 is reported as "quantized").
QUANT_RE = re.compile(r"(gguf|awq|gptq|mlx|exl2|bnb|4bit|8bit|int4|int8|fp8|nvfp4)", re.I)
QUANT_LIBRARIES = {"gguf", "mlx"}
QUANT_TAGS = {"gguf", "mlx", "awq", "gptq", "exl2"}
TEST_RE = re.compile(r"(tiny-random|dummy|(^|[-_/])tests?([-_/]|$)|testing)", re.I)
REUPLOADERS = {
    "unsloth", "lmstudio-community", "bartowski", "mlx-community",
    "onnx-community", "Comfy-Org", "litert-community", "TheBloke",
}

# Tags that describe packaging/infra rather than what the model does.
STRUCTURAL_TAGS = {
    "endpoints_compatible", "text-generation-inference", "autotrain_compatible",
    "safetensors", "pytorch", "tf", "jax", "flax", "onnx", "gguf", "openvino",
    "rust", "coreml", "tflite", "keras", "mlx", "transformers", "transformers.js",
    "sentence-transformers", "diffusers", "timm", "model-index", "eval-results",
    "custom_code", "has_space", "deploy", "tensorboard", "text-embeddings-inference",
}

# Plain-language task descriptions put at the front of embed_text. Bare tag
# names embed almost identically when they share words ("text to speech" vs
# "automatic speech recognition" for "speech to text" queries), so each
# description spells out the input -> output direction in everyday words.
# Tags not listed here fall back to the tag name itself.
TASK_DESCRIPTIONS = {
    "text-generation": "text generation: a language model / chatbot that writes text, answers questions, follows instructions",
    "image-text-to-text": "vision language model: takes images and text, answers questions about images, describes pictures",
    "sentence-similarity": "sentence embeddings: turns sentences into vectors for semantic search, similarity, clustering",
    "feature-extraction": "embeddings / feature extraction: turns text into vectors for semantic search and retrieval",
    "text-classification": "text classification: labels a piece of text (sentiment, topic, toxicity, intent)",
    "automatic-speech-recognition": "speech recognition: transcribes spoken audio into written text (speech to text)",
    "text-to-speech": "speech synthesis: reads written text aloud as generated audio (text to speech, voice)",
    "fill-mask": "masked language model: pretrained text encoder that fills in missing words, base for fine-tuning",
    "text-to-image": "image generation: creates images from a text prompt",
    "token-classification": "token classification: tags words in text, named entity recognition (NER), extracting names, places, entities",
    "image-classification": "image classification: labels what a photo or picture shows",
    "image-to-image": "image editing: transforms an input image into another image (restyle, upscale, edit)",
    "zero-shot-image-classification": "zero-shot image classification: matches images against arbitrary text labels, image-text embeddings",
    "time-series-forecasting": "time series forecasting: predicts future values of numeric series",
    "text-ranking": "reranking: scores how relevant a document is to a search query",
    "translation": "machine translation: translates text from one language into another",
    "image-segmentation": "image segmentation: outlines objects or regions in an image pixel by pixel",
    "image-to-video": "video generation from an image: animates a still picture into a video",
    "image-to-text": "image to text: captions images or reads text in images (OCR, documents)",
    "object-detection": "object detection: finds and boxes objects in images",
    "audio-classification": "audio classification: labels sounds or audio clips (sound events, speaker, emotion)",
    "text-to-video": "video generation: creates video clips from a text prompt",
    "zero-shot-classification": "zero-shot text classification: labels text with any categories given at run time",
    "depth-estimation": "depth estimation: predicts how far each pixel of an image is from the camera",
    "image-feature-extraction": "image embeddings: turns images into vectors for similarity search",
    "question-answering": "extractive question answering: finds the answer span to a question inside a passage",
    "summarization": "summarization: condenses long text into a short summary",
    "text-to-audio": "audio generation: creates music or sound from a text prompt",
    "voice-activity-detection": "voice activity detection: detects when someone is speaking in audio",
    "video-classification": "video classification: labels what happens in a video clip",
}

EXPAND = [
    "downloads", "downloadsAllTime", "likes", "pipeline_tag", "library_name",
    "tags", "cardData", "gated", "baseModels", "safetensors", "lastModified",
]

RAW_MODELS_PATH = "data/raw_models.jsonl"
RAW_CARDS_PATH = "data/raw_cards.jsonl"
OUT_PATH = "data/models.jsonl"
STATS_PATH = "data/ingest_stats.json"


# ---------- stage 1: sweep ----------

def sweep():
    models = HfApi().list_models(sort="downloads", gated=False, expand=EXPAND, limit=RAW_PULL)
    rows = []
    for m in models:
        base = m.base_models if isinstance(m.base_models, dict) else {}
        rows.append({
            "id": m.id,
            "pipeline_tag": m.pipeline_tag,
            "library_name": m.library_name,
            "tags": m.tags or [],
            "card_data": m.card_data.to_dict() if m.card_data else {},
            "base_models": [b["id"] for b in base.get("models", []) if b.get("id")],
            "downloads_30d": m.downloads or 0,
            "downloads_all": m.downloads_all_time or 0,
            "likes": m.likes or 0,
            "params": m.safetensors.total if m.safetensors else None,
            "last_modified": m.last_modified.isoformat() if m.last_modified else None,
        })
    with open(RAW_MODELS_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    return rows


def load_or_sweep(refresh):
    if os.path.exists(RAW_MODELS_PATH) and not refresh:
        with open(RAW_MODELS_PATH) as f:
            rows = [json.loads(line) for line in f]
        print(f"[1] reusing {RAW_MODELS_PATH}: {len(rows)} models (--refresh to re-pull)")
        return rows
    t = time.time()
    rows = sweep()
    print(f"[1] swept {len(rows)} models in {time.time() - t:.1f}s -> {RAW_MODELS_PATH}")
    return rows


# ---------- stage 2: metadata filter ----------

def metadata_drop_reason(row):
    author = row["id"].split("/")[0]
    if not row["pipeline_tag"]:
        return "no_pipeline_tag"
    if (QUANT_RE.search(row["id"]) or row["library_name"] in QUANT_LIBRARIES
            or QUANT_TAGS & set(row["tags"])):
        return "quantized_variant"
    if TEST_RE.search(row["id"]):
        return "test_repo"
    if author in REUPLOADERS:
        return "reuploader"
    return None


def filter_metadata(rows, drops):
    per_author = collections.Counter()
    kept = []
    for row in rows:  # already sorted by downloads, so the cap keeps each author's top models
        reason = metadata_drop_reason(row)
        if reason is None:
            author = row["id"].split("/")[0]
            if per_author[author] >= AUTHOR_CAP:
                reason = "author_cap"
            else:
                per_author[author] += 1
        if reason:
            drops[reason] += 1
        else:
            kept.append(row)
    print(f"[2] {len(kept)} candidates after metadata filters")
    return kept


# ---------- stage 3: card fetch ----------

def load_cards():
    cards = {}
    if os.path.exists(RAW_CARDS_PATH):
        with open(RAW_CARDS_PATH) as f:
            for line in f:
                rec = json.loads(line)
                cards[rec["id"]] = rec
    return cards


def fetch_card(model_id):
    for attempt in range(CARD_RETRIES):
        try:
            # Only .text is used, so a malformed YAML header shouldn't cost us the card.
            card = ModelCard.load(model_id, ignore_metadata_errors=True)
            return {"id": model_id, "text": card.text}
        except (EntryNotFoundError, RepositoryNotFoundError):
            return {"id": model_id, "error": "no_readme"}  # permanent: recorded, never retried
        except Exception as e:
            if attempt == CARD_RETRIES - 1:
                return {"id": model_id, "transient_error": f"{type(e).__name__}: {e}"[:200]}
            time.sleep(2 * (attempt + 1))


def fetch_cards(candidates):
    cards = load_cards()
    todo = [row["id"] for row in candidates if row["id"] not in cards]
    print(f"[3] {len(cards)} cards already on disk, fetching {len(todo)}")
    t = time.time()
    done = 0
    with open(RAW_CARDS_PATH, "a") as f, ThreadPoolExecutor(CARD_THREADS) as pool:
        futures = [pool.submit(fetch_card, model_id) for model_id in todo]
        for future in as_completed(futures):
            rec = future.result()
            done += 1
            # Transient failures aren't persisted, so the next run retries them.
            if "transient_error" not in rec:
                f.write(json.dumps(rec) + "\n")
                f.flush()
                cards[rec["id"]] = rec
            if done % 250 == 0:
                print(f"    {done}/{len(todo)} cards ({done / (time.time() - t):.1f}/s)")
    return cards


# ---------- stage 4: clean ----------

def clean_markdown(md):
    text = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)          # images, badges
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)        # unwrap links
    text = re.sub(r"<[^>]+>", " ", text)                        # html tags
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace(PLACEHOLDER, " ").replace("`", "")
    text = re.sub(r"\*\*|__", "", text)                          # bold markers
    text = text.replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") or re.fullmatch(r"[-=*_ ]{3,}", stripped):
            continue  # tables, horizontal rules
        lines.append(re.sub(r"[ \t]+", " ", stripped))
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_prose(text):
    return len(text) >= MIN_PROSE_LEN and sum(c.isalpha() for c in text) / len(text) > 0.6


def card_summary(cleaned):
    """The first real prose paragraph of the card. Terse cards (timm, opus-mt)
    describe the model in a short sentence plus a bullet list instead, so
    fall back to the first ~300 chars of non-heading text before giving up."""
    for block in re.split(r"\n\s*\n", cleaned):
        prose = " ".join(
            line for line in block.split("\n")
            if line and not line.startswith(("#", "- ", "* ", "+ ", ">"))
            and not re.match(r"\d+\.\s", line)
        )
        if is_prose(prose):
            return prose
    body = " ".join(
        line.lstrip("-*+> ") for line in cleaned.split("\n")
        if line and not line.startswith("#")
    )
    fallback = truncate(body, 300)
    return fallback if is_prose(fallback) else None


def card_drop_reason(card):
    if card is None:
        return "fetch_error"
    if card.get("error"):
        return card["error"]
    if card["text"].count(PLACEHOLDER) >= MAX_PLACEHOLDERS:
        return "placeholder_card"
    return None


# ---------- stage 5: build ----------

def as_list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def structure_tags(row):
    card_data = row["card_data"] or {}
    tags = row["tags"]

    licenses = as_list(card_data.get("license")) or [t.split(":", 1)[1] for t in tags if t.startswith("license:")]
    languages = as_list(card_data.get("language"))
    if not languages:
        languages = [t for t in tags if re.fullmatch(r"[a-z]{2}", t) and t not in STRUCTURAL_TAGS]
    datasets = [t.split(":", 1)[1] for t in tags if t.startswith("dataset:")]

    skip = STRUCTURAL_TAGS | {row["pipeline_tag"], row["library_name"]} | set(languages)
    topic_tags = [
        t for t in tags
        if ":" not in t and t not in skip and not re.fullmatch(r"[a-z]{2,3}", t)
    ]
    return {
        "license": licenses[0] if licenses else None,
        "languages": languages,
        "datasets": datasets,
        "topic_tags": topic_tags,
    }


def build_embed_text(record, prose):
    task = record["pipeline_tag"]
    parts = [TASK_DESCRIPTIONS.get(task, task.replace("-", " "))]
    if record["library_name"]:
        parts.append(record["library_name"])
    langs = record["languages"]
    if langs:
        parts.append("Languages: " + (", ".join(langs) if len(langs) <= 8 else "multilingual"))
    if record["topic_tags"]:
        parts.append("Tags: " + ", ".join(record["topic_tags"][:8]))
    head = ". ".join(parts) + ". "
    return truncate(head + prose, EMBED_TEXT_MAX)


def build_record(row, cleaned, prose):
    record = {
        "id": row["id"],
        "author": row["id"].split("/")[0],
        "pipeline_tag": row["pipeline_tag"],
        "library_name": row["library_name"],
        **structure_tags(row),
        "base_models": row["base_models"],
        "downloads_30d": row["downloads_30d"],
        "downloads_all": row["downloads_all"],
        "likes": row["likes"],
        "params": row["params"],
        "last_modified": row["last_modified"],
        "card_text": truncate(cleaned, CARD_TEXT_MAX),
    }
    record["embed_text"] = build_embed_text(record, prose)
    return record


def main():
    hf_logging.set_verbosity_error()
    disable_progress_bars()
    refresh = "--refresh" in sys.argv

    drops = collections.Counter()
    rows = load_or_sweep(refresh)
    candidates = filter_metadata(rows, drops)
    cards = fetch_cards(candidates)

    kept = []
    for row in candidates:
        card = cards.get(row["id"])
        reason = card_drop_reason(card)
        cleaned = prose = None
        if reason is None:
            cleaned = clean_markdown(card["text"])
            prose = card_summary(cleaned)
            if prose is None:
                reason = "no_prose"
        if reason:
            drops[reason] += 1
            continue
        kept.append(build_record(row, cleaned, prose))

    with open(OUT_PATH, "w") as f:
        for record in kept:
            f.write(json.dumps(record) + "\n")

    stats = {
        "pulled": len(rows),
        "kept": len(kept),
        "dropped": dict(drops.most_common()),
        "pipeline_tags": dict(collections.Counter(r["pipeline_tag"] for r in kept).most_common()),
        "top_authors": dict(collections.Counter(r["author"] for r in kept).most_common(10)),
    }
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\nDone. Pulled {len(rows)}, kept {len(kept)}. Saved to {OUT_PATH}")
    print("dropped:", stats["dropped"])
    print("pipeline_tags:", list(stats["pipeline_tags"].items())[:15])
    print("top authors:", stats["top_authors"])


if __name__ == "__main__":
    main()
