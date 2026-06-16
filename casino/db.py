"""Слой данных на aiosqlite. Балансы — целые nanoTON, обновления атомарны."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    balance     INTEGER NOT NULL DEFAULT 0,   -- nanoTON
    client_seed TEXT    NOT NULL DEFAULT '',
    nonce       INTEGER NOT NULL DEFAULT 0,
    last_faucet INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL,              -- faucet|deposit|withdraw|bet|win
    amount     INTEGER NOT NULL,              -- знаковый nanoTON
    meta       TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    bet              INTEGER NOT NULL,
    crash_point      REAL    NOT NULL,
    cashout          REAL,                    -- множитель вывода, NULL если краш
    payout           INTEGER NOT NULL DEFAULT 0,
    server_seed      TEXT    NOT NULL,
    server_seed_hash TEXT    NOT NULL,
    client_seed      TEXT    NOT NULL,
    nonce            INTEGER NOT NULL,
    outcome          TEXT    NOT NULL,        -- win|lose
    created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_deposits (
    tx_hash    TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_rounds_user ON rounds(user_id, id DESC);
"""


class Database:
    def __init__(self, path: str):
        self._path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    # --- пользователи ---

    async def get_or_create_user(self, user_id: int, username: str) -> Dict[str, Any]:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO users(id, username, client_seed, created_at) "
            "VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username",
            (user_id, username, f"u{user_id}", int(time.time())),
        )
        await self._db.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_balance(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user["balance"]) if user else 0

    async def set_client_seed(self, user_id: int, seed: str) -> None:
        assert self._db is not None
        await self._db.execute("UPDATE users SET client_seed=? WHERE id=?", (seed, user_id))
        await self._db.commit()

    async def next_nonce(self, user_id: int) -> int:
        """Атомарно инкрементирует и возвращает новый nonce."""
        assert self._db is not None
        await self._db.execute("UPDATE users SET nonce = nonce + 1 WHERE id=?", (user_id,))
        async with self._db.execute("SELECT nonce FROM users WHERE id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        await self._db.commit()
        return int(row["nonce"])

    # --- деньги (атомарно) ---

    async def credit(self, user_id: int, amount: int, kind: str, meta: str = "") -> int:
        """Зачислить amount nanoTON. Возвращает новый баланс."""
        assert self._db is not None and amount >= 0
        await self._db.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
        await self._add_tx(user_id, kind, amount, meta)
        await self._db.commit()
        return await self.get_balance(user_id)

    async def try_debit(self, user_id: int, amount: int, kind: str, meta: str = "") -> Optional[int]:
        """Списать amount. None если недостаточно средств. Иначе новый баланс."""
        assert self._db is not None and amount >= 0
        cur = await self._db.execute(
            "UPDATE users SET balance = balance - ? WHERE id=? AND balance >= ?",
            (amount, user_id, amount),
        )
        if cur.rowcount == 0:
            await self._db.rollback()
            return None
        await self._add_tx(user_id, kind, -amount, meta)
        await self._db.commit()
        return await self.get_balance(user_id)

    async def _add_tx(self, user_id: int, kind: str, amount: int, meta: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO transactions(user_id, kind, amount, meta, created_at) VALUES(?,?,?,?,?)",
            (user_id, kind, amount, meta, int(time.time())),
        )

    # --- faucet (кран тестовых монет) ---

    async def faucet_seconds_left(self, user_id: int, cooldown: int) -> int:
        user = await self.get_user(user_id)
        if not user:
            return 0
        left = int(user["last_faucet"]) + cooldown - int(time.time())
        return max(0, left)

    async def mark_faucet(self, user_id: int) -> None:
        assert self._db is not None
        await self._db.execute("UPDATE users SET last_faucet=? WHERE id=?", (int(time.time()), user_id))
        await self._db.commit()

    # --- раунды ---

    async def record_round(self, *, user_id: int, bet: int, crash_point: float,
                           cashout: Optional[float], payout: int, server_seed: str,
                           server_seed_hash: str, client_seed: str, nonce: int,
                           outcome: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO rounds(user_id, bet, crash_point, cashout, payout, server_seed, "
            "server_seed_hash, client_seed, nonce, outcome, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, bet, crash_point, cashout, payout, server_seed,
             server_seed_hash, client_seed, nonce, outcome, int(time.time())),
        )
        await self._db.commit()

    async def recent_crash_points(self, limit: int = 14) -> List[float]:
        """Последние точки краша (для ленты истории в Mini App)."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT crash_point FROM rounds ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [float(r["crash_point"]) for r in await cur.fetchall()]

    async def top_players(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Топ игроков по балансу (лидерборд)."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def recent_transactions(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT kind, amount, created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- дедупликация депозитов (TON) ---

    async def is_deposit_processed(self, tx_hash: str) -> bool:
        assert self._db is not None
        async with self._db.execute(
            "SELECT 1 FROM processed_deposits WHERE tx_hash=?", (tx_hash,)
        ) as cur:
            return await cur.fetchone() is not None

    async def mark_deposit_processed(self, tx_hash: str, user_id: int, amount: int) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR IGNORE INTO processed_deposits(tx_hash, user_id, amount, created_at) "
            "VALUES(?,?,?,?)",
            (tx_hash, user_id, amount, int(time.time())),
        )
        await self._db.commit()
