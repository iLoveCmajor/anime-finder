from types import SimpleNamespace

from rag_helper import RAGBase, format_count, format_languages, parse_answer

DOC = {
    "id": "org/german-ner",
    "pipeline_tag": "token-classification",
    "library_name": "transformers",
    "license": "mit",
    "languages": ["de"],
    "params": 110_000_000,
    "downloads_30d": 12_345,
    "downloads_all": 2_500_000,
    "likes": 42,
    "topic_tags": ["ner"],
    "card_text": "Finds names in German text.",
}


class FakeIndex:
    def __init__(self, docs):
        self.docs = docs

    def search(self, query, num_results=5):
        return self.docs[:num_results]


class FakeLLMClient:
    """Stands in for openai.OpenAI(): records the request, returns a canned answer."""

    def __init__(self, output_text):
        self.output_text = output_text
        self.requests = []
        self.responses = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


def test_format_count():
    assert format_count(None) == "unknown"
    assert format_count(999) == "999"
    assert format_count(12_345) == "12.3K"
    assert format_count(110_000_000) == "110.0M"
    assert format_count(8_030_000_000) == "8.0B"


def test_format_languages():
    assert format_languages([]) == "not specified"
    assert format_languages(["de", "en"]) == "de, en"
    assert format_languages([str(i) for i in range(12)]) == "multilingual (12 languages)"


def test_parse_answer():
    assert parse_answer("Because reasons.\n\nANSWER: org/german-ner") == "org/german-ner"
    assert parse_answer("ANSWER:   org/model  \n") == "org/model"
    assert parse_answer("no answer line here") is None


def test_build_context_includes_metadata_and_card():
    rag = RAGBase(index=FakeIndex([DOC]), llm_client=None)
    context = rag.build_context([DOC])

    for expected in ["Model ID: org/german-ner", "Task: token-classification", "License: mit", "Languages: de",
                     "Parameters: 110.0M", "12.3K last 30 days", "2.5M all time", "likes: 42",
                     "Finds names in German text."]:
        assert expected in context


def test_rag_returns_answer_and_results_without_storing_them():
    client = FakeLLMClient("It handles German NER.\nANSWER: org/german-ner")
    rag = RAGBase(index=FakeIndex([DOC]), llm_client=client)

    answer, results = rag.rag("german named entity recognition")

    assert parse_answer(answer) == "org/german-ner"
    assert results == [DOC]
    # Regression: per-request results must not live on the shared instance,
    # which the app shares across all Streamlit sessions.
    assert not hasattr(rag, "last_results")

    request = client.requests[0]
    assert request["model"] == rag.model
    assert request["input"][0]["role"] == "developer"
    assert "QUERY: german named entity recognition" in request["input"][1]["content"]
    assert "Model ID: org/german-ner" in request["input"][1]["content"]
