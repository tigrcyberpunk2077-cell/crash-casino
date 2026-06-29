"""Хранилище агента (SQLite): каналы и черновики постов.

Объём работы маленький (несколько постов в час), поэтому синхронный sqlite3
в одном соединении — этого достаточно и проще, чем async-обёртки.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

_conn: Optional[sqlite3.Connection] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(path: str) -> None:
    global _conn
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ref           TEXT UNIQUE NOT NULL,   -- @username или -100… id
            title         TEXT,
            topic         TEXT,                   -- ниша канала (трейдинг/ставки…)
            persona       TEXT,                   -- персона: кто ведёт (имя, характер, подача)
            interval_min  INTEGER NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            last_posted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id    INTEGER NOT NULL,
            text          TEXT NOT NULL,
            angle         TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',  -- pending|published|rejected
            created_at    TEXT NOT NULL,
            approval_chat_id INTEGER,
            approval_msg_id  INTEGER,
            published_at  TEXT,
            image_path    TEXT,
            brief         TEXT
        );
        """
    )
    # Мягкие миграции для баз, созданных в более ранних версиях.
    for stmt in (
        "ALTER TABLE drafts ADD COLUMN image_path TEXT",
        "ALTER TABLE drafts ADD COLUMN brief TEXT",
        "ALTER TABLE channels ADD COLUMN persona TEXT",
    ):
        try:
            _conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # колонка уже есть
    _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("init_db() ещё не вызван")
    return _conn


# --- Каналы ---

def add_channel(ref: str, title: str, topic: str, persona: str, interval_min: int) -> int:
    _db().execute(
        "INSERT INTO channels(ref, title, topic, persona, interval_min) VALUES(?,?,?,?,?) "
        "ON CONFLICT(ref) DO UPDATE SET title=excluded.title, topic=excluded.topic, "
        "persona=excluded.persona, interval_min=excluded.interval_min, active=1",
        (ref, title, topic, persona, interval_min),
    )
    _db().commit()
    row = _db().execute("SELECT id FROM channels WHERE ref=?", (ref,)).fetchone()
    return int(row["id"])


def set_persona(channel_id: int, persona: str) -> None:
    _db().execute("UPDATE channels SET persona=? WHERE id=?", (persona, channel_id))
    _db().commit()


def list_channels(only_active: bool = False) -> List[sqlite3.Row]:
    q = "SELECT * FROM channels"
    if only_active:
        q += " WHERE active=1"
    q += " ORDER BY id"
    return _db().execute(q).fetchall()


def get_channel(channel_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()


def set_active(channel_id: int, active: bool) -> None:
    _db().execute("UPDATE channels SET active=? WHERE id=?", (1 if active else 0, channel_id))
    _db().commit()


def set_interval(channel_id: int, interval_min: int) -> None:
    _db().execute("UPDATE channels SET interval_min=? WHERE id=?", (interval_min, channel_id))
    _db().commit()


def touch_posted(channel_id: int) -> None:
    """Сдвигает «часы» канала на сейчас — следующий пост через interval_min."""
    _db().execute("UPDATE channels SET last_posted_at=? WHERE id=?", (_now(), channel_id))
    _db().commit()


# --- Черновики ---

def has_pending(channel_id: int) -> bool:
    row = _db().execute(
        "SELECT 1 FROM drafts WHERE channel_id=? AND status='pending' LIMIT 1",
        (channel_id,),
    ).fetchone()
    return row is not None


def create_draft(channel_id: int, text: str, angle: str, brief: Optional[str] = None) -> int:
    cur = _db().execute(
        "INSERT INTO drafts(channel_id, text, angle, brief, created_at) VALUES(?,?,?,?,?)",
        (channel_id, text, angle, brief, _now()),
    )
    _db().commit()
    return int(cur.lastrowid)


def get_draft(draft_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()


def set_draft_text(draft_id: int, text: str, angle: str) -> None:
    _db().execute("UPDATE drafts SET text=?, angle=? WHERE id=?", (text, angle, draft_id))
    _db().commit()


def set_draft_image(draft_id: int, image_path: Optional[str]) -> None:
    _db().execute("UPDATE drafts SET image_path=? WHERE id=?", (image_path, draft_id))
    _db().commit()


def channel_exists(ref: str) -> bool:
    return _db().execute("SELECT 1 FROM channels WHERE ref=? LIMIT 1", (ref,)).fetchone() is not None


def set_approval_msg(draft_id: int, chat_id: int, msg_id: int) -> None:
    _db().execute(
        "UPDATE drafts SET approval_chat_id=?, approval_msg_id=? WHERE id=?",
        (chat_id, msg_id, draft_id),
    )
    _db().commit()


def mark_published(draft_id: int) -> None:
    _db().execute(
        "UPDATE drafts SET status='published', published_at=? WHERE id=?",
        (_now(), draft_id),
    )
    _db().commit()


def mark_rejected(draft_id: int) -> None:
    _db().execute("UPDATE drafts SET status='rejected' WHERE id=?", (draft_id,))
    _db().commit()


def recent_published_texts(channel_id: int, limit: int = 5) -> List[str]:
    rows = _db().execute(
        "SELECT text FROM drafts WHERE channel_id=? AND status='published' "
        "ORDER BY id DESC LIMIT ?",
        (channel_id, limit),
    ).fetchall()
    return [r["text"] for r in rows]
