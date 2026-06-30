"""Хранилище ассистента (SQLite): whitelist друзей, черновики ответов, настройки."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

_conn: Optional[sqlite3.Connection] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(path: str) -> None:
    global _conn
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS allow (
            chat_id  INTEGER PRIMARY KEY,
            name     TEXT,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER NOT NULL,
            name       TEXT,
            incoming   TEXT,
            reply      TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',
            fmt        TEXT NOT NULL DEFAULT 'text',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
        """
    )
    try:
        _conn.execute("ALTER TABLE drafts ADD COLUMN fmt TEXT NOT NULL DEFAULT 'text'")
    except sqlite3.OperationalError:
        pass
    _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() не вызван")
    return _conn


# --- whitelist ---

def allow(chat_id: int, name: str) -> None:
    _db().execute("INSERT OR REPLACE INTO allow(chat_id, name, added_at) VALUES(?,?,?)",
                  (chat_id, name, _now()))
    _db().commit()


def deny(chat_id: int) -> None:
    _db().execute("DELETE FROM allow WHERE chat_id=?", (chat_id,))
    _db().commit()


def is_allowed(chat_id: int) -> bool:
    return _db().execute("SELECT 1 FROM allow WHERE chat_id=?", (chat_id,)).fetchone() is not None


def list_allowed() -> List[sqlite3.Row]:
    return _db().execute("SELECT * FROM allow ORDER BY added_at").fetchall()


# --- черновики ---

def add_draft(chat_id: int, name: str, incoming: str, reply: str, fmt: str = "text") -> int:
    cur = _db().execute(
        "INSERT INTO drafts(chat_id, name, incoming, reply, fmt, created_at) VALUES(?,?,?,?,?,?)",
        (chat_id, name, incoming, reply, fmt, _now()),
    )
    _db().commit()
    return int(cur.lastrowid)


def get_draft(draft_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()


def set_draft(draft_id: int, reply: Optional[str] = None, status: Optional[str] = None) -> None:
    if reply is not None:
        _db().execute("UPDATE drafts SET reply=? WHERE id=?", (reply, draft_id))
    if status is not None:
        _db().execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
    _db().commit()


# --- настройки (kv) ---

def kv_get(k: str, default=None):
    r = _db().execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def kv_set(k: str, v) -> None:
    _db().execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?,?)", (k, str(v)))
    _db().commit()
