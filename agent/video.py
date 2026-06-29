"""Сборка вертикального фейслес-видео (Reels/TikTok) — бесплатно, локально.

Пайплайн: озвучка (edge-tts) + картинки + субтитры-карточки → MP4 9:16 (ffmpeg).
Текст впечатывается в кадры через Pillow (в этом ffmpeg нет фильтров текста),
кадры склеиваются concat-демуксером + аудио.
Нужны: системный ffmpeg/ffprobe, пакеты edge-tts и Pillow, TTF-шрифт с кириллицей.
"""

from __future__ import annotations

import asyncio
import os
import random
import re

W, H = 1080, 1920
VOICE_DEFAULT = "ru-RU-SvetlanaNeural"   # женский русский голос (под персону)

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                pass
    return ImageFont.load_default()


def _chunks(text: str, maxlen: int = 90) -> list:
    """Режем озвучку на короткие фразы-карточки (по предложениям, длинные дробим)."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        while len(p) > maxlen:
            cut = p.rfind(" ", 0, maxlen)
            if cut <= 0:
                cut = maxlen
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out or [text.strip()]


def _wrap(draw, text: str, font, max_w: int) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _cover(img, w: int, h: int):
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((int(sw * scale) + 1, int(sh * scale) + 1))
    nw, nh = img.size
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _make_frame(bg_path: str, caption: str, out_png: str) -> None:
    from PIL import Image, ImageDraw
    img = _cover(Image.open(bg_path).convert("RGB"), W, H)
    img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.5)  # затемняем для читаемости
    draw = ImageDraw.Draw(img)

    font = _font(66)
    lines = _wrap(draw, caption, font, W - 160)
    line_h = int(font.size * 1.25)
    total_h = line_h * len(lines)
    y = (H - total_h) // 2
    for ln in lines:
        tw = draw.textlength(ln, font=font)
        x = (W - tw) // 2
        draw.text((x, y), ln, font=font, fill="white",
                  stroke_width=6, stroke_fill="black")
        y += line_h
    img.save(out_png)


async def _tts(text: str, path: str, voice: str, el_key: str = None, el_voice: str = None) -> bool:
    """Озвучка: сначала ElevenLabs (если есть ключ), иначе/при сбое — бесплатный edge-tts."""
    if el_key:
        if await _tts_elevenlabs(text, path, el_key, el_voice):
            return True
        print("ElevenLabs недоступен — откат на edge-tts", flush=True)
    return await _tts_edge(text, path, voice)


async def _tts_elevenlabs(text: str, path: str, key: str, voice_id: str) -> bool:
    import httpx
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or 'EXAVITQu4vr4xnSDxMaL'}"
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, headers={"xi-api-key": key, "content-type": "application/json"},
                             json={"text": text, "model_id": "eleven_multilingual_v2"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio"):
            with open(path, "wb") as f:
                f.write(r.content)
            return os.path.getsize(path) > 500
        print("ElevenLabs error:", r.status_code, r.text[:160], flush=True)
        return False
    except Exception as e:  # noqa: BLE001
        print("ElevenLabs exc:", e, flush=True)
        return False


async def _tts_edge(text: str, path: str, voice: str) -> bool:
    import edge_tts
    try:
        await edge_tts.Communicate(text, voice).save(path)
        return os.path.exists(path) and os.path.getsize(path) > 500
    except Exception as e:  # noqa: BLE001
        print("edge-tts error:", e, flush=True)
        return False


async def _duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


async def _run(*args) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="ignore").strip().splitlines()[-3:]
        print("ffmpeg error:", " | ".join(tail), flush=True)
    return proc.returncode


async def make_video(voiceover: str, image_paths: list, out_path: str,
                     voice: str = VOICE_DEFAULT, work_dir: str = None,
                     el_key: str = None, el_voice: str = None) -> bool:
    """Собирает MP4 9:16: субтитры-карточки на фоне картинок + озвучка. True — если ок."""
    work = work_dir or (os.path.dirname(out_path) or ".")
    os.makedirs(work, exist_ok=True)

    audio = os.path.join(work, "voice.mp3")
    if not await _tts(voiceover, audio, voice, el_key, el_voice):
        return False
    dur = await _duration(audio)
    if dur <= 0:
        return False

    imgs = [p for p in image_paths if p and os.path.exists(p)]
    if not imgs:
        return False

    cards = _chunks(voiceover)
    total_chars = sum(len(c) for c in cards) or 1

    # кадр на каждую карточку (фон чередуем по кругу), длительность ∝ длине текста
    frames, durs = [], []
    for i, c in enumerate(cards):
        png = os.path.join(work, f"frame_{i:03d}.png")
        _make_frame(imgs[i % len(imgs)], c, png)
        frames.append(png)
        durs.append(max(1.2, dur * len(c) / total_chars))

    # список для concat-демуксера. Пути ОБЯЗАТЕЛЬНО абсолютные: относительные
    # ffmpeg резолвит относительно папки листа, а не cwd (иначе кадры не находятся).
    listfile = os.path.join(work, "frames.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for png, d in zip(frames, durs):
            f.write(f"file '{os.path.abspath(png)}'\nduration {d:.3f}\n")
        f.write(f"file '{os.path.abspath(frames[-1])}'\n")

    rc = await _run(
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", os.path.abspath(listfile),
        "-i", os.path.abspath(audio), "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
        out_path,
    )
    return rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000


# ===================== Видео на реальных клипах (Pexels) =====================

# Подбор английских поисковых запросов под нишу (без LLM — быстро и без квоты).
_FOOTAGE = {
    ("трейд", "бирж", "инвест", "крипт", "график", "акци", "форекс"): [
        "stock market trading screen", "financial charts candlesticks", "cryptocurrency bitcoin neon",
        "city business skyline night", "money cash counting", "laptop trading desk dark",
    ],
    ("ставк", "спорт", "бет", "матч", "футбол", "беттинг"): [
        "soccer football stadium", "sports betting phone app", "basketball game action",
        "stadium crowd cheering", "money cash sport", "running athletics track",
    ],
}
_FOOTAGE_DEFAULT = ["money finance success", "city business skyline", "laptop work desk dark",
                    "luxury lifestyle car", "neon night city"]


def _query_for(niche: str) -> str:
    n = (niche or "").lower()
    for keys, qs in _FOOTAGE.items():
        if any(k in n for k in keys):
            return random.choice(qs)
    return random.choice(_FOOTAGE_DEFAULT)


async def _pexels_clips(key: str, query: str, k: int, work: str) -> list:
    """Качает до k вертикальных клипов по запросу. Возвращает пути."""
    import httpx
    out = []
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "orientation": "portrait", "per_page": max(k, 6), "size": "medium"},
                headers={"Authorization": key},
            )
            if r.status_code != 200:
                print("Pexels search:", r.status_code, r.text[:120], flush=True)
                return []
            vids = r.json().get("videos", [])
            random.shuffle(vids)
            for v in vids:
                if len(out) >= k:
                    break
                files = [f for f in v.get("video_files", []) if (f.get("height") or 0) >= (f.get("width") or 0)]
                if not files:
                    continue
                # берём ~1080p, НЕ 4K: иначе клип 40–50 МБ, долго качать и тяжело монтировать.
                small = [f for f in files if 0 < (f.get("width") or 0) <= 1100]
                chosen = (max(small, key=lambda f: f.get("width") or 0) if small
                          else min(files, key=lambda f: f.get("width") or 99999))
                dl = await c.get(chosen["link"])
                if dl.status_code == 200 and len(dl.content) > 10000:
                    p = os.path.join(work, f"clip_{len(out)}.mp4")
                    with open(p, "wb") as f:
                        f.write(dl.content)
                    out.append(p)
    except Exception as e:  # noqa: BLE001
        print("Pexels error:", e, flush=True)
    return out


def _caption_overlay_png(text: str, out_png: str) -> None:
    """Прозрачный полнокадровый PNG: субтитр в тёмной плашке (для overlay на видео)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font(72)
    lines = _wrap(d, text, f, W - 160)
    lh = int(f.size * 1.3)
    th = lh * len(lines)
    y0 = int(H * 0.6) - th // 2
    pad = 40
    d.rounded_rectangle([60, y0 - pad, W - 60, y0 + th + pad], radius=30, fill=(0, 0, 0, 150))
    y = y0
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) // 2, y), ln, font=f, fill="white", stroke_width=6, stroke_fill="black")
        y += lh
    img.save(out_png)


async def make_clip_video(voiceover: str, niche: str, out_path: str, *, el_key: str = None,
                          el_voice: str = None, pexels_key: str = None, work_dir: str = None) -> bool:
    """Видео на реальных Pexels-клипах + субтитры-плашки поверх + озвучка."""
    work = work_dir or (os.path.dirname(out_path) or ".")
    os.makedirs(work, exist_ok=True)

    audio = os.path.join(work, "voice.mp3")
    if not await _tts(voiceover, audio, VOICE_DEFAULT, el_key, el_voice):
        return False
    dur = await _duration(audio)
    if dur <= 0:
        return False

    clips = await _pexels_clips(pexels_key, _query_for(niche), 2, work) if pexels_key else []
    if not clips:
        return False

    cards = _chunks(voiceover)
    total = sum(len(c) for c in cards) or 1
    items, t = [], 0.0
    for c in cards:
        d = max(1.0, dur * len(c) / total)
        items.append((c, t, min(dur, t + d)))
        t += d
    caps = []
    for i, (c, s, e) in enumerate(items):
        p = os.path.join(work, f"cap_{i:03d}.png")
        _caption_overlay_png(c, p)
        caps.append((p, s, e))

    k = len(clips)
    slice_t = dur / k + 0.5
    args = ["ffmpeg", "-y"]
    for cp in clips:
        args += ["-i", os.path.abspath(cp)]
    for p, _, _ in caps:
        args += ["-loop", "1", "-i", os.path.abspath(p)]
    args += ["-i", os.path.abspath(audio)]

    fc = ""
    for i in range(k):
        fc += (f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"setsar=1,fps=30,trim=0:{slice_t:.2f},setpts=PTS-STARTPTS[c{i}];")
    fc += "".join(f"[c{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[bg];"
    prev = "bg"
    for i, (p, s, e) in enumerate(caps):
        nxt = f"o{i}"
        fc += f"[{prev}][{k + i}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[{nxt}];"
        prev = nxt
    fc = fc.rstrip(";")

    args += ["-filter_complex", fc, "-map", f"[{prev}]", "-map", f"{k + len(caps)}:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
             os.path.abspath(out_path)]
    rc = await _run(*args)
    return rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000
