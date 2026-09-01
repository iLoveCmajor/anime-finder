INSTRUCTIONS = '''
Your task is to help a user find anime based on a description of the
plot, vibe, or themes they're looking for.

Use the provided candidate anime (retrieved by searching synopses,
genres, and tags) to answer. Recommend the best-matching title(s) from
the candidates and briefly explain why they match, grounded only in
the retrieved information. If none of the candidates are a good match,
say so honestly instead of making one up.
'''

PROMPT_TEMPLATE = '''
QUERY: {question}

CANDIDATE ANIME:
{context}
'''.strip()


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
            title = doc['title_romaji']
            if doc.get('title_english'):
                title += f" ({doc['title_english']})"

            lines.append('Title: ' + title)
            lines.append('Genres: ' + ', '.join(doc.get('genres', [])))
            lines.append('Tags: ' + ', '.join(doc.get('tags', [])[:10]))
            lines.append('Synopsis: ' + doc['description'])
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
        search_results = self.search(query)
        prompt = self.build_prompt(query, search_results)
        answer = self.llm(prompt)
        return answer
