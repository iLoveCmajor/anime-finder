REWRITE_INSTRUCTIONS = '''
Your task is to rewrite a user's casual anime plot/vibe description into
a fuller, more detailed description optimized for matching against
anime synopses.

Expand implicit details into more descriptive, synopsis-like language
(genre, setting, tone) but do not invent specific plot points, character
names, or details that weren't implied by the original description.

Output only the rewritten description, nothing else - no preamble, no
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
