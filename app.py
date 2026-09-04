import json
import os
import time

import numpy as np
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

import db
from embedder import Embedder
from minsearch import VectorSearch
from rag_helper import RAGBase
from search_backends import VectorIndexAdapter

load_dotenv()
db.init_db()


EMBEDDINGS_CACHE = "data/embeddings.npy"


@st.cache_resource
def load_rag():
    with open("data/anime.jsonl") as f:
        documents = [json.loads(line) for line in f]

    embed = Embedder()

    if os.path.exists(EMBEDDINGS_CACHE):
        X = np.load(EMBEDDINGS_CACHE)
    else:
        texts = [doc["description"] for doc in documents]
        batch_size = 50
        X = []
        for i in range(0, len(texts), batch_size):
            X.extend(embed.encode_batch(texts[i:i + batch_size]))
        X = np.array(X)
        np.save(EMBEDDINGS_CACHE, X)

    vindex = VectorSearch()
    vindex.fit(X, documents)

    vector_index = VectorIndexAdapter(vindex, embed)
    client = OpenAI()

    return RAGBase(index=vector_index, llm_client=client)


rag = load_rag()

st.title("Anime Finder")
st.caption("Describe a plot, vibe, or theme you remember - find the anime.")

query = st.text_input(
    "What are you looking for?",
    placeholder="e.g. a shy high school girl secretly gains magical powers and fights monsters at night",
)

if st.button("Search") and query:
    with st.spinner("Searching..."):
        start = time.time()
        answer = rag.rag(query)
        results = rag.last_results
        response_time = time.time() - start

    conversation_id = db.save_conversation(query, answer, response_time)

    st.session_state.conversation_id = conversation_id
    st.session_state.answer = answer
    st.session_state.results = results

# Rendered from session_state (not just inside the button block above) so
# the recommendation stays visible across reruns triggered by the
# feedback buttons below - otherwise clicking +1/-1 would make the
# answer disappear, since Streamlit reruns the whole script on every click.
if "answer" in st.session_state:
    st.subheader("Recommendation")
    st.write(st.session_state.answer)

    st.subheader("Retrieved candidates")
    for doc in st.session_state.results:
        title = doc["title_romaji"]
        if doc.get("title_english"):
            title += f" ({doc['title_english']})"

        with st.expander(title):
            st.write("**Genres:** " + ", ".join(doc.get("genres", [])))
            st.write("**Tags:** " + ", ".join(doc.get("tags", [])[:10]))
            st.write(doc["description"])

    conversation_id = st.session_state.get("conversation_id")
    if conversation_id is not None:
        col1, col2 = st.columns(2)

        with col1:
            if st.button("\U0001F44D", key=f"feedback_up_{conversation_id}"):
                db.save_feedback(conversation_id, "user", score=1)
                st.success("Thanks!")

        with col2:
            if st.button("\U0001F44E", key=f"feedback_down_{conversation_id}"):
                db.save_feedback(conversation_id, "user", score=-1)
                st.success("Thanks for the feedback!")
