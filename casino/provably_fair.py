"""Provably-fair механика для игры Crash.

Схема commit-reveal:
1. До раунда сервер генерирует ``server_seed`` (секрет) и публикует его SHA-256 хэш
   (commitment). Игрок видит хэш заранее и не может его подделать.
2. Точка краша вычисляется детерминированно из HMAC-SHA256(server_seed, "client_seed:nonce").
3. После раунда сервер раскрывает ``server_seed``. Игрок проверяет, что
   SHA-256(server_seed) совпадает с обещанным хэшем и что точка краша посчитана честно.

Формула точки краша — классическая (как в bustabit/trustdice). House edge ~1%
заложен в самой формуле: примерно 1% исходов выпадает ровно на 1.00x (краш до
того, как кто-либо успел забрать), потому что это случается при h < 2^52 / 100.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_server_seed() -> str:
    """Случайный секретный seed (64 hex-символа = 256 бит)."""
    return secrets.token_hex(32)


def hash_server_seed(server_seed: str) -> str:
    """SHA-256 от server_seed — публикуется как commitment до раунда."""
    return hashlib.sha256(server_seed.encode()).hexdigest()


def _hmac_hex(server_seed: str, client_seed: str, nonce: int) -> str:
    message = f"{client_seed}:{nonce}".encode()
    return hmac.new(server_seed.encode(), message, hashlib.sha256).hexdigest()


def crash_point(server_seed: str, client_seed: str, nonce: int) -> float:
    """Детерминированная точка краша (множитель), >= 1.00.

    Зависит только от трёх публично проверяемых значений.
    """
    digest = _hmac_hex(server_seed, client_seed, nonce)

    # 52-битное число из первых 13 hex-символов.
    h = int(digest[:13], 16)
    e = 2 ** 52
    result = (100 * e - h) // (e - h)  # целое в "сотых" множителя
    # ~1% исходов даёт result == 100 (1.00x) => house edge.
    return max(1.0, result / 100.0)


def verify(server_seed: str, server_seed_hash: str, client_seed: str,
           nonce: int, claimed_crash: float) -> bool:
    """Проверка раунда игроком после раскрытия server_seed."""
    if hash_server_seed(server_seed) != server_seed_hash:
        return False
    return abs(crash_point(server_seed, client_seed, nonce) - claimed_crash) < 1e-9
