from search_backends import VectorIndexAdapter

REWRITE_INSTRUCTIONS = '''
Your task is to rewrite a user's casual description of an ML task into a
short search phrase optimized for matching against Hugging Face model
cards.

Translate everyday wording into the terminology model cards use: the
task name (e.g. "automatic speech recognition", "token classification /
named entity recognition", "sentence similarity embeddings"), the input
and output modality, and any language, domain, size or deployment
constraint the user stated. Keep it under 30 words. Do not add
constraints, model names or details the user didn't imply.

Output only the rewritten phrase, nothing else - no preamble, no
quotes, no explanation.
'''.strip()


def rewrite_query(client, query, model='gpt-5.4-mini'):
    input_messages = [
        {'role': 'developer', 'content': REWRITE_INSTRUCTIONS},
        {'role': 'user', 'content': query}
    ]

    response = client.responses.create(
        model=model,
        input=input_messages
    )

    return response.output_text.strip()


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
