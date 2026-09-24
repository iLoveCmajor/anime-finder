import json
import time

import streamlit as st
from dotenv import load_dotenv
from minsearch import VectorSearch
from openai import OpenAI

import db
from auth import require_password
from embedder import Embedder
from embedding_cache import load_or_build
from rag_helper import RAGBase, format_count
from search_backends import VectorIndexAdapter

load_dotenv()
require_password()
db.init_db()


DOCUMENTS_PATH = "data/models.jsonl"
EMBEDDINGS_CACHE = "data/model_embeddings.npy"


@st.cache_resource
def load_rag():
    with open(DOCUMENTS_PATH) as f:
        documents = [json.loads(line) for line in f]

    embed = Embedder()

    X = load_or_build([doc["embed_text"] for doc in documents], embed, EMBEDDINGS_CACHE)

    vindex = VectorSearch()
    vindex.fit(X, documents)

    vector_index = VectorIndexAdapter(vindex, embed)
    client = OpenAI()

    return RAGBase(index=vector_index, llm_client=client)


rag = load_rag()

st.title("HF Model Finder")
st.caption("Describe the ML task you want to solve - get matched to a pretrained model on the Hugging Face Hub.")

# A form submits the text and the button press together, so pressing Enter
# or clicking Search runs exactly one search with what was typed.
with st.form("search"):
    query = st.text_input(
        "What do you need a model for?",
        placeholder="e.g. transcribe German phone calls on a CPU-only server",
    )
    submitted = st.form_submit_button("Search")

if submitted and query:
    with st.spinner("Searching..."):
        start = time.time()
        answer, results = rag.rag(query)
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
        with st.expander(doc["id"]):
            st.markdown(f"[huggingface.co/{doc['id']}](https://huggingface.co/{doc['id']})")
            st.write(
                f"**Task:** {doc['pipeline_tag']} | "
                f"**Library:** {doc.get('library_name') or 'n/a'} | "
                f"**License:** {doc.get('license') or 'n/a'} | "
                f"**Params:** {format_count(doc.get('params'))} | "
                f"**Downloads (30d):** {format_count(doc.get('downloads_30d'))}"
            )
            if doc.get("topic_tags"):
                st.write("**Tags:** " + ", ".join(doc["topic_tags"][:10]))
            st.text(doc["card_text"])

    conversation_id = st.session_state.get("conversation_id")
    if conversation_id is not None:
        if "votes" not in st.session_state:
            st.session_state.votes = {}

        given = st.session_state.votes.get(conversation_id)

        if given is not None:
            st.caption("Thanks — feedback recorded." if given > 0 else "Thanks for the feedback.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                if st.button("\U0001F44D", key=f"feedback_up_{conversation_id}"):
                    db.save_feedback(conversation_id, "user", score=1)
                    st.session_state.votes[conversation_id] = 1
                    st.rerun()

            with col2:
                if st.button("\U0001F44E", key=f"feedback_down_{conversation_id}"):
                    db.save_feedback(conversation_id, "user", score=-1)
                    st.session_state.votes[conversation_id] = -1
                    st.rerun()
