import os

import streamlit as st


def require_password():
    """Gate a Streamlit page behind a shared password read from the
    APP_PASSWORD env var. No-op if APP_PASSWORD isn't set (e.g. local
    dev), so this only takes effect once deployed with it configured."""
    app_password = os.environ.get("APP_PASSWORD")
    if not app_password:
        return

    if st.session_state.get("authenticated"):
        return

    password = st.text_input("Password", type="password")
    if st.button("Enter"):
        if password == app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()
