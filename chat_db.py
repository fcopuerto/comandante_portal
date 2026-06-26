"""Persistent chat history — conversations + messages (MSSQL backend)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db() -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            IF OBJECT_ID('cobaltax_conversations', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_conversations (
                    id         INT            IDENTITY(1,1) PRIMARY KEY,
                    [user]     NVARCHAR(200)  NOT NULL,
                    title      NVARCHAR(500)  NOT NULL DEFAULT 'New conversation',
                    created_at NVARCHAR(30)   NOT NULL,
                    updated_at NVARCHAR(30)   NOT NULL
                );
                CREATE INDEX idx_conv_user ON cobaltax_conversations([user], updated_at);
            END
        """)
        cur.execute("""
            IF OBJECT_ID('cobaltax_chat_messages', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_chat_messages (
                    id              INT            IDENTITY(1,1) PRIMARY KEY,
                    conversation_id INT            NOT NULL
                                    REFERENCES cobaltax_conversations(id) ON DELETE CASCADE,
                    [user]          NVARCHAR(200)  NOT NULL,
                    role            NVARCHAR(50)   NOT NULL,
                    content         NVARCHAR(MAX)  NOT NULL,
                    created_at      NVARCHAR(30)   NOT NULL
                );
                CREATE INDEX idx_msg_conv ON cobaltax_chat_messages(conversation_id, id);
            END
        """)


# ── Conversations ─────────────────────────────────────────────────────────────

def list_conversations(user: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM cobaltax_chat_messages WHERE conversation_id = c.id) AS msg_count
            FROM cobaltax_conversations c
            WHERE c.[user] = ?
            ORDER BY c.updated_at DESC
        """, user)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_conversation(user: str, title: str = "New conversation") -> int:
    now = _now()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO cobaltax_conversations ([user], title, created_at, updated_at)"
            " OUTPUT INSERTED.id VALUES (?,?,?,?)",
            user, title, now, now,
        )
        return int(cur.fetchone()[0])


def rename_conversation(cid: int, user: str, title: str) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cobaltax_conversations SET title=? WHERE id=? AND [user]=?",
            title, cid, user,
        )


def delete_conversation(cid: int, user: str) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM cobaltax_conversations WHERE id=? AND [user]=?", cid, user
        )


def touch_conversation(cid: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cobaltax_conversations SET updated_at=? WHERE id=?", _now(), cid
        )


# ── Messages ──────────────────────────────────────────────────────────────────

def save_message(user: str, role: str, content: str,
                 conversation_id: Optional[int] = None) -> None:
    now = _now()
    with get_conn() as conn:
        cur = conn.cursor()
        if conversation_id is None:
            cur.execute(
                "SELECT TOP 1 id FROM cobaltax_conversations WHERE [user]=? ORDER BY updated_at DESC",
                user,
            )
            row = cur.fetchone()
            if row:
                conversation_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO cobaltax_conversations ([user], title, created_at, updated_at)"
                    " OUTPUT INSERTED.id VALUES (?,?,?,?)",
                    user, "New conversation", now, now,
                )
                conversation_id = int(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO cobaltax_chat_messages (conversation_id, [user], role, content, created_at)"
            " VALUES (?,?,?,?,?)",
            conversation_id, user, role, content, now,
        )
        cur.execute(
            "UPDATE cobaltax_conversations SET updated_at=? WHERE id=?", now, conversation_id
        )


def get_history(user: str, conversation_id: int,
                limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT role, content, created_at FROM (
                SELECT TOP (?) role, content, created_at, id
                FROM cobaltax_chat_messages
                WHERE conversation_id=? AND [user]=?
                ORDER BY id DESC
            ) sub ORDER BY id ASC
        """, limit, conversation_id, user)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def clear_history(user: str) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM cobaltax_conversations WHERE [user]=?", user)
