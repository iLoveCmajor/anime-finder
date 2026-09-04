import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "data/monitoring.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                response_time REAL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER REFERENCES conversations(id),
                source TEXT NOT NULL,
                score INTEGER,
                relevance TEXT,
                explanation TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def save_conversation(query, answer, response_time):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "INSERT INTO conversations (query, answer, response_time, timestamp) VALUES (?, ?, ?, ?)",
            (query, answer, response_time, timestamp),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def save_feedback(conversation_id, source, score=None, relevance=None, explanation=None):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO feedback
                (conversation_id, source, score, relevance, explanation, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, source, score, relevance, explanation, timestamp),
        )
        conn.commit()
    finally:
        conn.close()


def get_conversations(limit=100):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats():
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*), AVG(response_time) FROM conversations"
        ).fetchone()
        return {"total": row[0] or 0, "avg_response_time": row[1] or 0.0}
    finally:
        conn.close()


def get_user_feedback_stats():
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END)
            FROM feedback WHERE source = 'user'
            """
        ).fetchone()
        return row[0] or 0, row[1] or 0
    finally:
        conn.close()
