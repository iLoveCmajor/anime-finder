class VectorIndexAdapter:
    """Bridges VectorSearch (which takes an embedded query vector) to
    RAGBase's expected `.search(query, num_results)` interface (which
    passes a plain string query)."""

    def __init__(self, vindex, embed):
        self.vindex = vindex
        self.embed = embed

    def search(self, query, num_results=5):
        query_vector = self.embed.encode(query)
        return self.vindex.search(query_vector, num_results=num_results)
