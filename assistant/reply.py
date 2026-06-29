"""Генерация ответа другу от лица Тиграна (через тот же Gemini, что у агента)."""

from __future__ import annotations

from typing import List, Tuple

from agent.llm import generate_post


def _system(profile: str) -> str:
    base = (
        "Ты — Тигран, 18 лет. Отвечаешь друзьям в личной переписке в Telegram как ты сам. "
        "Пиши ОТ ПЕРВОГО ЛИЦА, коротко, по-дружески, на живом разговорном русском (можно сленг), "
        "без формальностей и канцелярита. Не извиняйся без причины и НЕ упоминай, что ты ИИ. "
        "Один короткий ответ, как ответил бы живой человек в чате.\n"
    )
    if profile:
        base += f"Факты о тебе (учитывай в ответах): {profile}\n"
    base += (
        "Если зовут гулять/встретиться или спрашивают про планы — отвечай тепло и по-дружески, "
        "но НЕ назначай от моего имени конкретное время и место (это я решу сам) — "
        "ответь в духе «давай, скину как освобожусь» / «хз, попозже скажу».\n"
        "Верни только текст ответа, без кавычек и пояснений."
    )
    return base


async def make_reply(agent_cfg, profile: str, friend_name: str,
                     history: List[Tuple[bool, str]]) -> str:
    """history: список (from_me, text) в хронологическом порядке."""
    convo = "\n".join(("Я" if me else friend_name) + ": " + t for me, t in history[-12:])
    prompt = (
        f"Переписка с {friend_name}:\n{convo}\n\n"
        "Напиши мой ответ на последнее сообщение."
    )
    return (await generate_post(agent_cfg, _system(profile), prompt)).strip()
