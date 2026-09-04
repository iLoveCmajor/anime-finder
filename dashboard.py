import re

import pandas as pd
import streamlit as st

import db
from auth import require_password

require_password()
db.init_db()

st.title("Anime Finder - Monitoring Dashboard")

stats = db.get_stats()
thumbs_up, thumbs_down = db.get_user_feedback_stats()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total conversations", stats["total"])
col2.metric("Avg response time", f"{stats['avg_response_time']:.2f}s")
col3.metric("Thumbs up", thumbs_up)
col4.metric("Thumbs down", thumbs_down)

records = db.get_conversations(limit=200)

if not records:
    st.info("No conversations yet - use the app first, then come back here.")
else:
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    st.subheader("Conversations over time")
    df["count"] = 1
    st.line_chart(df.set_index("timestamp")["count"].cumsum())

    st.subheader("Response time over time")
    st.line_chart(df, x="timestamp", y="response_time")

    st.subheader("Response time distribution")
    bins = pd.cut(df["response_time"], bins=10)
    dist = bins.value_counts().sort_index()
    dist.index = dist.index.astype(str)
    st.bar_chart(dist)

    st.subheader("User feedback")
    st.bar_chart(pd.Series({"thumbs up": thumbs_up, "thumbs down": thumbs_down}))

    st.subheader("Most recommended anime")

    def extract_answer_title(text):
        match = re.search(r"ANSWER:\s*(.+)", text)
        return match.group(1).strip() if match else None

    titles = df["answer"].apply(extract_answer_title).dropna()
    top_titles = titles.value_counts().head(10)
    st.bar_chart(top_titles)

    st.subheader("Recent conversations")
    for record in records[:20]:
        st.write(f"**{record['query']}**")
        st.write(record["answer"][:300] + ("..." if len(record["answer"]) > 300 else ""))
        st.caption(f"{record['timestamp']} | {record['response_time']:.2f}s")
        st.divider()
