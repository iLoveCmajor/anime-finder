INSTRUCTIONS = '''
Your task is to help a user find anime based on a description of the
plot, vibe, or themes they're looking for.

Look at the candidate anime provided (retrieved by searching synopses,
genres, and tags). Pick exactly ONE best-matching title from the
candidates - do not hedge or list multiple options as equally likely.

End your answer with a final line in this exact format:
ANSWER: <title>

Briefly justify your pick using only the retrieved information, then
give the ANSWER line. If none of the candidates are a good match, still
pick the closest one but say so in your justification.
'''.strip()

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
        self.last_results = None

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
        self.last_results = search_results
        prompt = self.build_prompt(query, search_results)
        answer = self.llm(prompt)
        return answer
