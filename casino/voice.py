"""Озвучка фраз «ИИ Барана» голосом-клоном (ElevenLabs) → ogg/opus для голосовых
Telegram. Возвращает путь к .ogg или None (тогда отправим текстом)."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

log = logging.getLogger("casino.voice")


async def tts_ogg(key: str, voice_id: str, text: str) -> Optional[str]:
    if not key or not voice_id or not text:
        return None
    import httpx

    work = tempfile.mkdtemp(prefix="baran_")
    mp3 = os.path.join(work, "v.mp3")
    ogg = os.path.join(work, "v.ogg")
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key},
                json={"text": text[:500], "model_id": "eleven_multilingual_v2"},
            )
        if r.status_code != 200:
            log.info("tts -> %s", r.status_code)
            return None
        with open(mp3, "wb") as f:
            f.write(r.content)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", "-b:a", "48k",
            "-application", "voip", ogg,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return ogg if (os.path.exists(ogg) and os.path.getsize(ogg) > 0) else None
    except Exception:  # noqa: BLE001
        log.debug("tts error", exc_info=True)
        return None
