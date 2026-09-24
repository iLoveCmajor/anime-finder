import numpy as np

from embedding_cache import cache_key, load_or_build


class FakeEmbedder:
    path = "models/fake"

    def __init__(self):
        self.calls = 0

    def encode_batch(self, texts):
        self.calls += 1
        return [[float(len(t)), float(sum(map(ord, t)))] for t in texts]


def test_cache_is_reused_for_identical_texts(tmp_path):
    path = str(tmp_path / "emb.npy")
    embed = FakeEmbedder()

    first = load_or_build(["a", "bb"], embed, path)
    calls = embed.calls
    second = load_or_build(["a", "bb"], embed, path)

    assert embed.calls == calls
    np.testing.assert_array_equal(first, second)


def test_cache_rebuilds_when_content_changes_but_count_does_not(tmp_path):
    # Regression: the old cache only compared row counts.
    path = str(tmp_path / "emb.npy")
    embed = FakeEmbedder()

    load_or_build(["a", "bb"], embed, path)
    calls = embed.calls
    rebuilt = load_or_build(["a", "cc"], embed, path)

    assert embed.calls > calls
    np.testing.assert_array_equal(rebuilt, np.array(embed.encode_batch(["a", "cc"])))


def test_cache_key_depends_on_order_model_and_boundaries():
    assert cache_key(["a", "b"], "m") != cache_key(["b", "a"], "m")
    assert cache_key(["a", "b"], "m") != cache_key(["a", "b"], "other-model")
    assert cache_key(["ab", "c"], "m") != cache_key(["a", "bc"], "m")
