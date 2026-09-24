FROM python:3.12-slim

# Pinned uv binary from its official image, instead of whatever pip resolves.
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

# Run as an unprivileged user. It owns /app/state (the SQLite volume mount
# point) and data/ (in case the embedding cache has to be rebuilt).
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY --chown=app:app . .
RUN mkdir -p /app/state && chown app:app /app/state

USER app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
