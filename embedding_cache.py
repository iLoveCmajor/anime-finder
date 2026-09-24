"""Embedding cache keyed on content, not row count.

The key is a hash of every text plus the embedder model path, stored next to
the .npy file. A re-ingest that keeps the same number of models but changes
any of them (or their order) no longer silently pairs vectors with the wrong
documents.
"""

import hashlib
import os

import numpy as np


def cache_key(texts, model_path):
    digest = hashlib.sha256(str(model_path).encode())
    for text in texts:
        digest.update(b"\0")
        digest.update(text.encode())
    return digest.hexdigest()


def load_or_build(texts, embed, path, batch_size=50):
    key = cache_key(texts, embed.path)
    key_path = path + ".sha256"

    if os.path.exists(path) and os.path.exists(key_path):
        with open(key_path) as f:
            if f.read().strip() == key:
                return np.load(path)

    X = []
    for i in range(0, len(texts), batch_size):
        X.extend(embed.encode_batch(texts[i:i + batch_size]))
    X = np.array(X)

    np.save(path, X)
    with open(key_path, "w") as f:
        f.write(key)
    return X
