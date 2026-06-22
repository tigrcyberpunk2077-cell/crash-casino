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
        created_at  INTEGER NOT NULL,
        referred_by INTEGER NOT NULL DEFAULT 0,
        last_active INTEGER NOT NULL DEFAULT 0,
        last_remind INTEGER NOT NULL DEFAULT 0
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

# Доп. колонки для уже существующих баз (Turso): ALTER упадёт, если колонка есть —
# ловим и игнорируем (идемпотентная миграция).
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN referred_by INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN last_active INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN last_remind INTEGER NOT NULL DEFAULT 0",
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
        for stmt in MIGRATIONS:
            try:
                await self._db.execute(stmt)
            except Exception:  # noqa: BLE001 — колонка уже есть
                pass

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
        now = int(time.time())
        await self._exec(
            "INSERT INTO users(id, username, client_seed, created_at, last_active) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, last_active=excluded.last_active",
            (user_id, username, f"u{user_id}", now, now),
        )
        return await self.get_user(user_id)

    # --- рефералы и активность (соцфичи + напоминания) ---

    async def set_referrer(self, user_id: int, ref_id: int) -> bool:
        """Привязывает пригласившего ровно один раз. True — если применилось."""
        rs = await self._exec(
            "UPDATE users SET referred_by=? WHERE id=? AND referred_by=0 AND id<>?",
            (ref_id, user_id, ref_id),
        )
        return bool(rs.rows_affected)

    async def count_referrals(self, user_id: int) -> int:
        row = await self._one("SELECT COUNT(*) AS c FROM users WHERE referred_by=?", (user_id,))
        return int(row["c"]) if row else 0

    async def due_for_remind(self, idle_sec: int, limit: int) -> List[int]:
        """Реальные игроки (id>0), неактивные дольше idle_sec и давно без напоминания."""
        cutoff = int(time.time()) - idle_sec
        rows = await self._all(
            "SELECT id FROM users WHERE id>0 AND last_active>0 AND last_active<? "
            "AND last_remind<? ORDER BY last_active ASC LIMIT ?",
            (cutoff, cutoff, limit),
        )
        return [int(r["id"]) for r in rows]

    async def mark_reminded(self, ids: List[int]) -> None:
        now = int(time.time())
        for uid in ids:
            await self._exec("UPDATE users SET last_remind=? WHERE id=?", (now, uid))

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

    async def stats_overview(self, limit: int = 50) -> Dict[str, Any]:
        """Сводка для админ-раздела: общие цифры + список игроков с активностью/ставками."""
        now = int(time.time())
        tot = await self._one("SELECT COUNT(*) AS u, COALESCE(SUM(balance),0) AS bal FROM users WHERE id>0")
        act = await self._one("SELECT COUNT(*) AS c FROM users WHERE id>0 AND last_active>=?", (now - 86400,))
        wag = await self._one("SELECT COALESCE(SUM(-amount),0) AS w, COUNT(*) AS c FROM transactions WHERE kind='bet'")
        rows = await self._all(
            "SELECT u.id, u.username, u.balance, u.last_active, u.created_at, "
            "COALESCE(t.cnt,0) AS bets, COALESCE(t.wagered,0) AS wagered, COALESCE(t.last_bet,0) AS last_bet "
            "FROM users u LEFT JOIN ("
            "  SELECT user_id, COUNT(*) AS cnt, SUM(-amount) AS wagered, MAX(created_at) AS last_bet "
            "  FROM transactions WHERE kind='bet' GROUP BY user_id) t ON t.user_id = u.id "
            "WHERE u.id>0 ORDER BY u.last_active DESC LIMIT ?",
            (limit,),
        )
        players = [{
            "id": int(r["id"]), "name": r["username"] or "player",
            "balance": int(r["balance"]), "lastActive": int(r["last_active"]),
            "created": int(r["created_at"]), "bets": int(r["bets"]),
            "wagered": int(r["wagered"]), "lastBet": int(r["last_bet"]),
        } for r in rows]
        return {
            "users": int(tot["u"]), "active24h": int(act["c"]),
            "totalBet": int(wag["w"]), "betCount": int(wag["c"]),
            "totalBalance": int(tot["bal"]), "players": players,
        }

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
