"""Слой данных на libSQL (SQLite-совместимый).

Локально подключается к файлу (file:casino.db), на сервере — к облачной базе
Turso (libsql://… + токен), чтобы балансы НЕ пропадали при перезапусках/обновлениях.
Балансы — целые nanoTON; списание атомарно одним UPDATE с проверкой rows_affected.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

import libsql_client

SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY,
        username    TEXT,
        balance     INTEGER NOT NULL DEFAULT 0,
        client_seed TEXT    NOT NULL DEFAULT '',
        nonce       INTEGER NOT NULL DEFAULT 0,
        last_faucet INTEGER NOT NULL DEFAULT 0,
        created_at  INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS transactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        kind       TEXT    NOT NULL,
        amount     INTEGER NOT NULL,
        meta       TEXT,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rounds (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        bet              INTEGER NOT NULL,
        crash_point      REAL    NOT NULL,
        cashout          REAL,
        payout           INTEGER NOT NULL DEFAULT 0,
        server_seed      TEXT    NOT NULL,
        server_seed_hash TEXT    NOT NULL,
        client_seed      TEXT    NOT NULL,
        nonce            INTEGER NOT NULL,
        outcome          TEXT    NOT NULL,
        created_at       INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS processed_deposits (
        tx_hash    TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rounds_user ON rounds(user_id, id DESC)",
]


class Database:
    def __init__(self, path_or_url: str, auth_token: Optional[str] = None):
        if path_or_url.startswith("libsql://"):
            # libsql-client по схеме libsql:// идёт через WebSocket (wss://), а Turso
            # его отвергает рукопожатием 400 (WSServerHandshakeError) — ws-протокол
            # Hrana там задепрекейчен. HTTP-транспорт (https) работает стабильно.
            self._url = "https://" + path_or_url[len("libsql://"):]
        elif path_or_url.startswith(("https://", "http://", "wss://", "ws://")):
            self._url = path_or_url
        elif path_or_url == ":memory:":
            # libSQL держит данные в файле; для тестов даём уникальный временный.
            self._url = "file:" + os.path.join(tempfile.gettempdir(), f"casino_mem_{uuid.uuid4().hex}.db")
        else:
            self._url = "file:" + path_or_url
        self._token = auth_token
        self._db: Optional[Any] = None

    async def connect(self) -> None:
        self._db = libsql_client.create_client(url=self._url, auth_token=self._token)
        for stmt in SCHEMA_STMTS:
            await self._db.execute(stmt)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    # --- низкоуровневые помощники ---

    async def _one(self, sql: str, params=()) -> Optional[Dict[str, Any]]:
        rs = await self._db.execute(sql, list(params))
        if not rs.rows:
            return None
        row = rs.rows[0]
        return {c: row[c] for c in rs.columns}

    async def _all(self, sql: str, params=()) -> List[Dict[str, Any]]:
        rs = await self._db.execute(sql, list(params))
        return [{c: row[c] for c in rs.columns} for row in rs.rows]

    async def _exec(self, sql: str, params=()):
        return await self._db.execute(sql, list(params))

    # --- пользователи ---

    async def get_or_create_user(self, user_id: int, username: str) -> Dict[str, Any]:
        await self._exec(
            "INSERT INTO users(id, username, client_seed, created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username",
            (user_id, username, f"u{user_id}", int(time.time())),
        )
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM users WHERE id=?", (user_id,))

    async def get_balance(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user["balance"]) if user else 0

    async def set_client_seed(self, user_id: int, seed: str) -> None:
        await self._exec("UPDATE users SET client_seed=? WHERE id=?", (seed, user_id))

    async def next_nonce(self, user_id: int) -> int:
        await self._exec("UPDATE users SET nonce = nonce + 1 WHERE id=?", (user_id,))
        row = await self._one("SELECT nonce FROM users WHERE id=?", (user_id,))
        return int(row["nonce"])

    # --- деньги (списание атомарно) ---

    async def credit(self, user_id: int, amount: int, kind: str, meta: str = "") -> int:
        assert amount >= 0
        await self._exec("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
        await self._add_tx(user_id, kind, amount, meta)
        return await self.get_balance(user_id)

    async def try_debit(self, user_id: int, amount: int, kind: str, meta: str = "") -> Optional[int]:
        assert amount >= 0
        rs = await self._exec(
            "UPDATE users SET balance = balance - ? WHERE id=? AND balance >= ?",
            (amount, user_id, amount),
        )
        if not rs.rows_affected:
            return None
        await self._add_tx(user_id, kind, -amount, meta)
        return await self.get_balance(user_id)

    async def _add_tx(self, user_id: int, kind: str, amount: int, meta: str) -> None:
        await self._exec(
            "INSERT INTO transactions(user_id, kind, amount, meta, created_at) VALUES(?,?,?,?,?)",
            (user_id, kind, amount, meta, int(time.time())),
        )

    # --- faucet ---

    async def faucet_seconds_left(self, user_id: int, cooldown: int) -> int:
        user = await self.get_user(user_id)
        if not user:
            return 0
        return max(0, int(user["last_faucet"]) + cooldown - int(time.time()))

    async def mark_faucet(self, user_id: int) -> None:
        await self._exec("UPDATE users SET last_faucet=? WHERE id=?", (int(time.time()), user_id))

    # --- раунды ---

    async def record_round(self, *, user_id: int, bet: int, crash_point: float,
                           cashout: Optional[float], payout: int, server_seed: str,
                           server_seed_hash: str, client_seed: str, nonce: int,
                           outcome: str) -> None:
        await self._exec(
            "INSERT INTO rounds(user_id, bet, crash_point, cashout, payout, server_seed, "
            "server_seed_hash, client_seed, nonce, outcome, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, bet, crash_point, cashout, payout, server_seed,
             server_seed_hash, client_seed, nonce, outcome, int(time.time())),
        )

    async def recent_crash_points(self, limit: int = 14) -> List[float]:
        rows = await self._all("SELECT crash_point FROM rounds ORDER BY id DESC LIMIT ?", (limit,))
        return [float(r["crash_point"]) for r in rows]

    async def top_players(self, limit: int = 10) -> List[Dict[str, Any]]:
        return await self._all("SELECT username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))

    async def recent_transactions(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return await self._all(
            "SELECT kind, amount, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    # --- дедупликация депозитов (TON) ---

    async def is_deposit_processed(self, tx_hash: str) -> bool:
        row = await self._one("SELECT 1 AS x FROM processed_deposits WHERE tx_hash=?", (tx_hash,))
        return row is not None

    async def mark_deposit_processed(self, tx_hash: str, user_id: int, amount: int) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO processed_deposits(tx_hash, user_id, amount, created_at) VALUES(?,?,?,?)",
            (tx_hash, user_id, amount, int(time.time())),
        )
