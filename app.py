import json
import os
import time

import streamlit as st
from dotenv import load_dotenv
from minsearch import VectorSearch
from openai import OpenAI

import db
from auth import require_password
from embedder import Embedder
from embedding_cache import load_or_build
from rag_helper import RAGBase, format_count, parse_answer
from search_backends import VectorIndexAdapter

st.set_page_config(page_title="HF Model Finder", page_icon="🤗", layout="centered")

load_dotenv()
require_password()
db.init_db()


DOCUMENTS_PATH = "data/models.jsonl"
EMBEDDINGS_CACHE = "data/model_embeddings.npy"
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8502")

EXAMPLES = [
    "Named entity recognition for German text",
    "Transcribe English speech to text",
    "Small sentence embedding model that runs fast on CPU",
    "Classify photos of plants by species",
    "Read text aloud in a natural voice",
]


@st.cache_resource(show_spinner="Loading the model index...")
def load_rag():
    with open(DOCUMENTS_PATH) as f:
        documents = [json.loads(line) for line in f]

    embed = Embedder()
    X = load_or_build([doc["embed_text"] for doc in documents], embed, EMBEDDINGS_CACHE)

    vindex = VectorSearch()
    vindex.fit(X, documents)

    rag = RAGBase(index=VectorIndexAdapter(vindex, embed), llm_client=OpenAI())
    return rag, len(documents)


def find_model(rag, question):
    started = time.time()
    answer, results = rag.rag(question)
    elapsed = time.time() - started

    conversation_id = db.save_conversation(question, answer, elapsed)
    return {
        "id": conversation_id,
        "question": question,
        "answer": answer,
        "candidates": results,
        "elapsed": elapsed,
    }


def render_candidates(result):
    picked = parse_answer(result["answer"])
    label = f"Retrieved candidates — {len(result['candidates'])} models, answered in {result['elapsed']:.1f}s"

    with st.expander(label):
        for doc in result["candidates"]:
            mark = " ✅" if doc["id"] == picked else ""
            st.markdown(f"**[{doc['id']}](https://huggingface.co/{doc['id']})**{mark}")
            st.caption(
                f"{doc['pipeline_tag']} · {doc.get('library_name') or 'n/a'} · "
                f"license: {doc.get('license') or 'n/a'} · params: {format_count(doc.get('params'))} · "
                f"downloads (30d): {format_count(doc.get('downloads_30d'))}"
            )
            excerpt = doc["card_text"][:500]
            st.text(excerpt + ("..." if len(doc["card_text"]) > 500 else ""))


def render_feedback(result):
    """Thumbs up / down, keyed by conversation id so every answer keeps its own state."""
    conversation_id = result["id"]
    given = st.session_state.votes.get(conversation_id)

    if given is not None:
        st.caption("Thanks — feedback recorded." if given > 0 else "Thanks — noted.")
        return

    left, right, _ = st.columns([1, 1, 8])
    for column, vote, label in ((left, 1, "👍"), (right, -1, "👎")):
        if column.button(label, key=f"{vote}-{conversation_id}"):
            db.save_feedback(conversation_id, "user", score=vote)
            st.session_state.votes[conversation_id] = vote
            st.rerun()


rag, corpus_size = load_rag()

if "history" not in st.session_state:
    st.session_state.history = []
if "votes" not in st.session_state:
    st.session_state.votes = {}

st.title("🤗 HF Model Finder")
st.caption(
    "Describe the ML task you want to solve and get matched to a pretrained model on the "
    f"Hugging Face Hub. Answers come only from the model cards of {corpus_size:,} popular models, "
    "with the exact model id so you can load it."
)

with st.sidebar:
    st.subheader("Try one of these")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state.pending_question = example

    st.divider()
    if st.button("🗑️ Clear conversation", width="stretch"):
        st.session_state.history = []
        st.rerun()

    st.divider()
    st.caption(f"Models: {corpus_size:,} from a Hugging Face Hub snapshot")
    st.caption("Embeddings: `all-MiniLM-L6-v2` (local, ONNX)")
    st.caption(f"LLM: `{rag.model}`")
    st.caption(f"Monitoring: [dashboard]({DASHBOARD_URL})")

for past in st.session_state.history:
    with st.chat_message("user"):
        st.write(past["question"])

    with st.chat_message("assistant"):
        st.write(past["answer"])
        render_candidates(past)
        render_feedback(past)

question = st.chat_input("What do you need a model for?") or st.session_state.pop("pending_question", None)

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching model cards..."):
            result = find_model(rag, question)

        st.write(result["answer"])
        render_candidates(result)
        render_feedback(result)

    st.session_state.history.append(result)
