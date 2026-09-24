"""Quick test pull from the Hugging Face Hub to eyeball data quality before
building the real ingestion pipeline: 200 models' metadata plus the README
card for a spread of 20 of them, dumped to data_sample.json."""

import collections
import json

from huggingface_hub import HfApi, ModelCard

EXPAND = [
    "downloads", "downloadsAllTime", "likes", "pipeline_tag", "library_name",
    "tags", "cardData", "gated", "baseModels", "safetensors", "lastModified",
]


def to_dict(m):
    return {
        "id": m.id,
        "downloads": m.downloads,
        "downloads_all_time": m.downloads_all_time,
        "likes": m.likes,
        "pipeline_tag": m.pipeline_tag,
        "library_name": m.library_name,
        "tags": m.tags,
        "card_data": m.card_data.to_dict() if m.card_data else None,
        "gated": m.gated,
        "base_models": m.base_models,
        "params": m.safetensors.total if m.safetensors else None,
        "last_modified": str(m.last_modified),
    }


def main():
    models = list(HfApi().list_models(sort="downloads", gated=False, expand=EXPAND, limit=200))
    items = [to_dict(m) for m in models]

    for item in items[::10]:
        try:
            item["card_text"] = ModelCard.load(item["id"]).text
        except Exception as e:
            item["card_error"] = f"{type(e).__name__}: {e}"

    with open("data_sample.json", "w") as f:
        json.dump(items, f, indent=2, default=str)

    print(f"Pulled {len(items)} models -> data_sample.json")
    print("pipeline_tag:", collections.Counter(i["pipeline_tag"] for i in items).most_common(10))


if __name__ == "__main__":
    main()
