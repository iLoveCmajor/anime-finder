import re

INSTRUCTIONS = '''
Your task is to help a user find a pretrained model on the Hugging Face
Hub based on a description of the ML task they want to solve, including
any constraints they mention (language, domain, model size, license,
hardware).

Look at the candidate models provided (retrieved by searching model
cards, tasks, and tags). Pick exactly ONE best-matching model from the
candidates - do not hedge or list multiple options as equally likely.

End your answer with a final line in this exact format, copying the
model id exactly as written in the candidates:
ANSWER: <model id>

Briefly justify your pick using only the retrieved information, then
give the ANSWER line. If none of the candidates are a good match, still
pick the closest one but say so in your justification.
'''.strip()

PROMPT_TEMPLATE = '''
QUERY: {question}

CANDIDATE MODELS:
{context}
'''.strip()


def parse_answer(text):
    """The model id from the answer's final `ANSWER: <model id>` line, or None."""
    match = re.search(r'ANSWER:\s*(.+)', text)
    return match.group(1).strip() if match else None


def format_count(n):
    if n is None:
        return 'unknown'
    for unit, size in (('B', 1e9), ('M', 1e6), ('K', 1e3)):
        if n >= size:
            return f'{n / size:.1f}{unit}'
    return str(n)


def format_languages(languages):
    if not languages:
        return 'not specified'
    if len(languages) > 8:
        return f'multilingual ({len(languages)} languages)'
    return ', '.join(languages)


class RAGBase:

    def __init__(
        self,
        index,
        llm_client,
        instructions=INSTRUCTIONS,
        prompt_template=PROMPT_TEMPLATE,
        model='gpt-5.4-mini'
    ):
        self.index = index
        self.llm_client = llm_client
        self.instructions = instructions
        self.prompt_template = prompt_template
        self.model = model

    def search(self, query, num_results=5):
        return self.index.search(query, num_results=num_results)

    def build_context(self, search_results):
        lines = []

        for doc in search_results:
            lines.append('Model ID: ' + doc['id'])
            lines.append('Task: ' + doc['pipeline_tag'])
            lines.append('Library: ' + (doc.get('library_name') or 'not specified'))
            lines.append('License: ' + (doc.get('license') or 'not specified'))
            lines.append('Languages: ' + format_languages(doc.get('languages')))
            lines.append('Parameters: ' + format_count(doc.get('params')))
            lines.append(
                f"Downloads: {format_count(doc.get('downloads_30d'))} last 30 days, "
                f"{format_count(doc.get('downloads_all'))} all time; "
                f"likes: {doc.get('likes', 0)}"
            )
            lines.append('Tags: ' + ', '.join(doc.get('topic_tags', [])[:10]))
            lines.append('Model card excerpt: ' + doc['card_text'])
            lines.append('')

        return '\n'.join(lines).strip()

    def build_prompt(self, query, search_results):
        context = self.build_context(search_results)
        return self.prompt_template.format(
            question=query, context=context
        )

    def llm(self, prompt):
        input_messages = [
            {'role': 'developer', 'content': self.instructions},
            {'role': 'user', 'content': prompt}
        ]

        response = self.llm_client.responses.create(
            model=self.model,
            input=input_messages
        )

        return response.output_text

    def rag(self, query):
        # Returns the results instead of storing them on self: the app shares
        # one RAGBase across all sessions (st.cache_resource), so per-request
        # state here would leak between concurrent users.
        search_results = self.search(query)
        prompt = self.build_prompt(query, search_results)
        answer = self.llm(prompt)
        return answer, search_results
