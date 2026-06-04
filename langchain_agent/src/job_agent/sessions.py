import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "sessions.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_sessions_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def create_session(user_id: str = "local-user", name: str = "新对话") -> dict:
    init_sessions_db()
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "thread_id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": name.strip() or "新对话",
        "created_at": now,
        "updated_at": now,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (thread_id, user_id, name, created_at, updated_at)
            VALUES (:thread_id, :user_id, :name, :created_at, :updated_at)
            """,
            session,
        )
    return session


def list_sessions(user_id: str = "local-user") -> list[dict]:
    init_sessions_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT thread_id, user_id, name, created_at, updated_at
            FROM sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def touch_session(thread_id: str, message: str | None = None) -> None:
    init_sessions_db()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT name FROM sessions WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"会话不存在：{thread_id}")
        if row["name"] == "新对话" and message:
            name = message.strip().replace("\n", " ")[:24] or "新对话"
            conn.execute(
                "UPDATE sessions SET name = ?, updated_at = ? WHERE thread_id = ?",
                (name, now, thread_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE thread_id = ?",
                (now, thread_id),
            )


def delete_session(thread_id: str) -> bool:
    init_sessions_db()
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
    return cursor.rowcount > 0

