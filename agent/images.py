"""Картинки к постам через Pollinations.ai — бесплатно, без API-ключа.

Картинка = простой HTTP GET по URL с промптом. Сначала просим LLM придумать
короткий визуальный промпт на английском (без текста на картинке), затем
скачиваем изображение в файл и прикрепляем к посту.
"""

from __future__ import annotations

import logging
import os
import random
from urllib.parse import quote

from .config import Config
from .llm import generate_post

log = logging.getLogger("agent.images")

# Хвост, который заставляет генератор выдавать настоящее ФОТО, а не «рисунок».
# Без людей и лиц — только предметы/обстановка (нет AI-странностей лица).
_REALISM = (
    "photorealistic, candid amateur snapshot, shot on smartphone, natural lighting, "
    "true-to-life colours, 35mm, no people, no faces, no text, no watermark"
)

_IMG_SYSTEM = (
    "You write short English prompts for a PHOTO generator. The result must look like a REAL "
    "photograph someone took on a phone — NOT an illustration, render, 3D, or stylised art. "
    "Output ONLY the prompt on a single line — no quotes, no explanation. "
    "Describe a believable real-life scene of OBJECTS / WORKSPACE / SCENERY that fits the niche. "
    "VERY IMPORTANT: no people, no faces, no portraits — things and environments only. "
    "Do NOT use words like 'illustration', 'digital art', 'render', '3d', 'cinematic', 'aesthetic', "
    "'artstation'. SFW. No text/logos/watermark in the image."
)


async def _image_prompt(cfg: Config, post_text: str, niche: str, persona: str) -> str:
    user = (
        f"Personal expert Telegram channel. Niche: {niche or cfg.default_niche}. "
        f"Write one realistic real-life PHOTO prompt for this post: a believable everyday scene "
        f"of objects/workspace/scenery related to the niche — NO people, NO faces, no text. "
        f"Post for context (do not transcribe): {post_text[:300]}"
    )
    try:
        p = (await generate_post(cfg, _IMG_SYSTEM, user)).strip().strip('"').replace("\n", " ")
        if p:
            return p
    except Exception:  # noqa: BLE001 — best-effort, есть запасной вариант
        log.debug("Не удалось получить промпт картинки от LLM", exc_info=True)
    return (
        f"candid photo of a cozy home desk, open laptop showing stock price charts, "
        f"coffee mug, notebook, morning light through a window, {niche or cfg.default_niche}"
    )


async def make_image(cfg: Config, post_text: str, dest_path: str,
                     niche: str = "", persona: str = "") -> bool:
    """Генерирует картинку и сохраняет в dest_path. True — если получилось."""
    import httpx

    prompt = await _image_prompt(cfg, post_text, niche, persona)
    full = prompt + ", " + _REALISM
    seed = random.randint(1, 10_000_000)
    url = (
        f"https://image.pollinations.ai/prompt/{quote(full)}"
        f"?width=1024&height=1024&nologo=true&seed={seed}&model=flux"
    )
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.content
        if not data or len(data) < 1000:  # пустой/битый ответ
            log.warning("Pollinations вернул пустую картинку")
            return False
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось сгенерировать картинку: %s", e)
        return False
