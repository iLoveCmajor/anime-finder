import collections

import pytest

from ingest import (
    AUTHOR_CAP,
    TASK_DESCRIPTIONS,
    build_embed_text,
    card_drop_reason,
    card_summary,
    clean_markdown,
    filter_metadata,
    metadata_drop_reason,
    structure_tags,
    truncate,
)


def row(model_id="org/model", pipeline_tag="text-classification", library_name="transformers", tags=(), card_data=None):
    return {
        "id": model_id,
        "pipeline_tag": pipeline_tag,
        "library_name": library_name,
        "tags": list(tags),
        "card_data": card_data or {},
    }


# ---------- clean_markdown ----------

def test_clean_markdown_strips_noise_and_unwraps_links():
    md = (
        "<!-- hidden -->\n"
        "# Title\n"
        "![badge](https://img.shields.io/x.svg)\n"
        "A **fast** model, see [the paper](https://arxiv.org/abs/1) and `code`.\n"
        "```python\nprint('hi')\n```\n"
        "| col | col |\n|---|---|\n"
        "<div align='center'>html</div>\n"
        "Visit https://example.com today.\n"
    )
    cleaned = clean_markdown(md)

    assert "hidden" not in cleaned
    assert "badge" not in cleaned and "shields" not in cleaned
    assert "A fast model, see the paper and code." in cleaned
    assert "print" not in cleaned
    assert "|" not in cleaned
    assert "<div" not in cleaned and "html" in cleaned
    assert "example.com" not in cleaned


def test_clean_markdown_drops_placeholders_and_collapses_blank_lines():
    cleaned = clean_markdown("one\n\n\n\n[More Information Needed]\n\n\n\ntwo")
    assert "More Information Needed" not in cleaned
    assert "\n\n\n" not in cleaned


# ---------- card_summary ----------

def test_card_summary_returns_first_prose_paragraph():
    prose = "This model classifies customer support tickets by urgency and routes them to the right team."
    cleaned = f"# Model card\n\n- bullet one\n- bullet two\n\n{prose}\n\nMore text later on."
    assert card_summary(cleaned) == prose


def test_card_summary_keeps_bold_led_prose():
    # Regression: lines starting with "*" were once treated as list items.
    cleaned = clean_markdown(
        "**U**niversal **S**entence **E**ncoder for Russian maps sentences to dense vectors for search."
    )
    assert card_summary(cleaned).startswith("Universal Sentence Encoder")


def test_card_summary_falls_back_for_terse_cards():
    # timm-style: one short sentence plus a bullet list, no paragraph >= 80 chars.
    cleaned = (
        "# Model card for resnet18\n\n"
        "A ResNet-B image classification model.\n\n"
        "This model features:\n"
        "* ReLU activations\n"
        "* single layer 7x7 convolution with pooling\n"
    )
    summary = card_summary(cleaned)
    assert summary is not None
    assert "ResNet-B image classification" in summary and "ReLU" in summary


def test_card_summary_none_without_prose():
    assert card_summary("# Title\n\n## Usage") is None


# ---------- metadata filters ----------

@pytest.mark.parametrize("model_row, reason", [
    (row(pipeline_tag=None), "no_pipeline_tag"),
    (row("org/Llama-3-8B-GGUF"), "quantized_variant"),
    (row("org/model", library_name="mlx"), "quantized_variant"),
    (row("org/model", tags=["gguf"]), "quantized_variant"),
    (row("org/tiny-random-bert"), "test_repo"),
    (row("org/bert-test"), "test_repo"),
    (row("unsloth/some-model"), "reuploader"),
    (row("org/good-model"), None),
])
def test_metadata_drop_reason(model_row, reason):
    assert metadata_drop_reason(model_row) == reason


def test_metadata_drop_reason_does_not_flag_words_containing_test():
    assert metadata_drop_reason(row("org/latest-contest-model")) is None


def test_filter_metadata_caps_models_per_author():
    rows = [row(f"bigorg/model-{i}") for i in range(AUTHOR_CAP + 5)] + [row("other/model")]
    drops = collections.Counter()

    kept = filter_metadata(rows, drops)

    assert sum(r["id"].startswith("bigorg/") for r in kept) == AUTHOR_CAP
    assert any(r["id"] == "other/model" for r in kept)
    assert drops["author_cap"] == 5


# ---------- card filters ----------

def test_card_drop_reason():
    assert card_drop_reason(None) == "fetch_error"
    assert card_drop_reason({"id": "x", "error": "no_readme"}) == "no_readme"
    assert card_drop_reason({"id": "x", "text": "[More Information Needed]\n" * 5}) == "placeholder_card"
    assert card_drop_reason({"id": "x", "text": "A real card."}) is None


# ---------- structure_tags / embed_text ----------

def test_structure_tags_splits_structural_tags():
    r = row(
        tags=["transformers", "pytorch", "safetensors", "license:mit", "dataset:imdb", "arxiv:1234.5678",
              "region:us", "en", "text-classification", "sentiment", "movies"],
    )
    tags = structure_tags(r)

    assert tags["license"] == "mit"
    assert tags["datasets"] == ["imdb"]
    assert tags["languages"] == ["en"]
    assert tags["topic_tags"] == ["sentiment", "movies"]


def test_structure_tags_prefers_card_data_and_ignores_framework_codes():
    # Regression: "tf" (TensorFlow) was once picked up as a language code.
    r = row(tags=["tf", "vision"], card_data={"license": "apache-2.0", "language": "de"})
    tags = structure_tags(r)

    assert tags["license"] == "apache-2.0"
    assert tags["languages"] == ["de"]
    assert "tf" not in tags["languages"]


def test_build_embed_text_leads_with_task_description():
    record = {
        "pipeline_tag": "automatic-speech-recognition",
        "library_name": "transformers",
        "languages": ["en"],
        "topic_tags": ["whisper"],
    }
    text = build_embed_text(record, "A speech model.")

    assert text.startswith(TASK_DESCRIPTIONS["automatic-speech-recognition"])
    assert "Languages: en" in text and "Tags: whisper" in text and text.endswith("A speech model.")


def test_build_embed_text_summarizes_many_languages():
    record = {"pipeline_tag": "unknown-task", "library_name": None, "languages": [f"l{i}" for i in range(20)],
              "topic_tags": []}
    text = build_embed_text(record, "prose")

    assert text.startswith("unknown task")
    assert "multilingual" in text


def test_truncate_cuts_on_word_boundary():
    assert truncate("short", 10) == "short"
    assert truncate("one two three four", 9) == "one two…"
