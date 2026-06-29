"""Генерация текста поста. Два провайдера, выбор через LLM_PROVIDER.

  • claude — Anthropic, модель Haiku (очень дёшево: ~$0.002 за пост).
  • gemini — Google Gemini Flash (есть бесплатный тариф).

Импорты ленивые: ставить нужно только ту библиотеку, что используешь.
"""

from __future__ import annotations

import asyncio

from .config import Config

# Кэшируем клиента Anthropic между вызовами.
_anthropic_client = None


async def generate_post(cfg: Config, system: str, prompt: str) -> str:
    if cfg.llm_provider == "claude":
        return await _generate_claude(cfg, system, prompt)
    return await _generate_gemini(cfg, system, prompt)


async def _generate_claude(cfg: Config, system: str, prompt: str) -> str:
    global _anthropic_client
    import anthropic  # ленивый импорт

    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)

    resp = await _anthropic_client.messages.create(
        model=cfg.anthropic_model,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


async def _generate_gemini(cfg: Config, system: str, prompt: str) -> str:
    # Gemini не делит system/user — склеиваем. httpx тянется вместе с anthropic,
    # но используем его и здесь, чтобы не плодить зависимости.
    import httpx

    # Перебираем комбинации КЛЮЧ × МОДЕЛЬ: упёрлись в лимит (429) / перегрузку (503) /
    # нет модели (404) → берём следующую. Несколько ключей (разные аккаунты) и несколько
    # моделей суммируют бесплатный лимит (~20 запросов/сутки на каждую модель на ключ).
    models = [m.strip() for m in cfg.gemini_model.split(",") if m.strip()] or ["gemini-flash-latest"]
    keys = cfg.gemini_api_keys or [""]
    text_in = system + "\n\n" + prompt
    last_429 = None

    async with httpx.AsyncClient(timeout=60) as client:
        for round_ in range(2):                              # два прохода
            for model in models:
                gen_cfg = {"maxOutputTokens": 2048, "temperature": 1.0}
                if "2.5" in model or "latest" in model:      # отключаем «размышления» — иначе обрезает
                    gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
                for key in keys:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model}:generateContent?key={key}"
                    )
                    r = await client.post(url, json={
                        "contents": [{"parts": [{"text": text_in}]}],
                        "generationConfig": gen_cfg,
                    })
                    if r.status_code in (429, 503, 404):     # лимит/перегрузка/нет модели → следующая
                        if r.status_code == 429:
                            last_429 = r
                        continue
                    r.raise_for_status()
                    data = r.json()
                    try:
                        parts = data["candidates"][0]["content"]["parts"]
                        out = "".join(p.get("text", "") for p in parts).strip()
                    except (KeyError, IndexError, TypeError):
                        out = ""
                    if out:
                        return out
                    # пустой ответ (фильтр/обрезка) — пробуем следующий ключ/модель
            if last_429 is not None and round_ == 0:         # всё занято → подождать и повторить
                await asyncio.sleep(min(_retry_delay(last_429, 20.0), 30))

    raise RuntimeError(
        "Gemini: все бесплатные модели упёрлись в дневной лимит (429). Бесплатно даётся "
        "~20 запросов в сутки на модель. Подожди (лимит сбрасывается ночью по тихоокеанскому "
        "времени) либо подключи биллинг в Google AI Studio — flash очень дёшев."
    )


def _retry_delay(resp, default: float) -> float:
    """Достаёт рекомендованную паузу из ответа 429 (RetryInfo.retryDelay='5s')."""
    try:
        for d in resp.json().get("error", {}).get("details", []):
            rd = d.get("retryDelay", "")
            if isinstance(rd, str) and rd.endswith("s"):
                return float(rd[:-1])
    except Exception:  # noqa: BLE001
        pass
    return default
