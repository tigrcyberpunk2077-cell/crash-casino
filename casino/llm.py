"""Лёгкий вызов Gemini для «ИИ Барана» в группах. Возвращает None при ошибке/лимите
(чтобы бот просто молчал, а не падал). Бесплатный тариф Gemini Flash."""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("casino.llm")


async def gemini_reply(api_key: str, model: str, system: str, prompt: str,
                       timeout: float = 20.0) -> Optional[str]:
    if not api_key:
        return None
    import httpx

    gen_cfg = {"maxOutputTokens": 300, "temperature": 1.1}
    if "2.5" in model or "latest" in model:        # отключаем «размышления» — иначе режет ответ
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json={
                "contents": [{"parts": [{"text": system + "\n\n" + prompt}]}],
                "generationConfig": gen_cfg,
            })
            if r.status_code != 200:
                log.info("gemini -> %s", r.status_code)
                return None
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            return ("".join(p.get("text", "") for p in parts).strip()) or None
    except Exception:  # noqa: BLE001
        log.debug("gemini error", exc_info=True)
        return None
