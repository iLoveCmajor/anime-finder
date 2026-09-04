from query_rewrite import rewrite_query


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


class RewritingVectorIndexAdapter(VectorIndexAdapter):
    """Same as VectorIndexAdapter, but rewrites the query with an LLM
    before embedding/searching. RAGBase's prompt still sees the
    original query - only retrieval uses the rewritten version."""

    def __init__(self, vindex, embed, llm_client):
        super().__init__(vindex, embed)
        self.llm_client = llm_client

    def search(self, query, num_results=5):
        rewritten = rewrite_query(self.llm_client, query)
        return super().search(rewritten, num_results=num_results)
