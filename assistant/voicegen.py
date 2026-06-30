"""Клон голоса (ElevenLabs IVC) + озвучка → ogg/opus для голосовых Telegram."""

from __future__ import annotations

import asyncio
import os


async def clone_voice(key: str, name: str, sample_path: str):
    """Загружает образец голоса в ElevenLabs (instant voice cloning). Возвращает voice_id."""
    import httpx
    with open(sample_path, "rb") as f:
        data = f.read()
    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(
                "https://api.elevenlabs.io/v1/voices/add",
                headers={"xi-api-key": key},
                data={"name": name},
                files={"files": (os.path.basename(sample_path), data, "audio/ogg")},
            )
        if r.status_code == 200:
            return r.json().get("voice_id")
        print("clone error:", r.status_code, r.text[:200], flush=True)
    except Exception as e:  # noqa: BLE001
        print("clone exc:", e, flush=True)
    return None


async def transcribe(key: str, audio_path: str):
    """Распознаёт речь из аудио (ElevenLabs STT, scribe_v1). Возвращает текст или None."""
    import httpx
    try:
        with open(audio_path, "rb") as f:
            data = f.read()
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                "https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": key},
                data={"model_id": "scribe_v1"},
                files={"file": (os.path.basename(audio_path), data, "audio/ogg")},
            )
        if r.status_code == 200:
            return (r.json().get("text") or "").strip() or None
        print("STT error:", r.status_code, r.text[:160], flush=True)
    except Exception as e:  # noqa: BLE001
        print("STT exc:", e, flush=True)
    return None


async def tts_ogg(key: str, voice_id: str, text: str, out_ogg: str, work: str) -> bool:
    """Озвучка текста клонированным голосом → ogg/opus (формат голосовых ТГ)."""
    import httpx
    mp3 = os.path.join(work, "voice_tmp.mp3")
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key, "content-type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
            )
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio"):
            print("tts error:", r.status_code, r.text[:160], flush=True)
            return False
        with open(mp3, "wb") as f:
            f.write(r.content)
    except Exception as e:  # noqa: BLE001
        print("tts exc:", e, flush=True)
        return False

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", "-b:a", "48k", "-application", "voip", out_ogg,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    try:
        os.remove(mp3)
    except OSError:
        pass
    return os.path.exists(out_ogg) and os.path.getsize(out_ogg) > 500
