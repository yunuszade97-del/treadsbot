"""
AI service — generates Threads-style posts via OpenRouter.

Uses the ``openai`` library pointed at OpenRouter's API-compatible endpoint.
"""

from __future__ import annotations

import logging
import re

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

# ── OpenRouter-compatible async client ──────────────────────────────────
client = AsyncOpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# ── Keywords that trigger "long post" mode ──────────────────────────────
_LONG_KEYWORDS = re.compile(
    r"напиши\s+пост|развёрни|разверни|длинн|полн\w+\s+пост|подробн",
    re.IGNORECASE,
)

# ── Default system prompt with few-shot examples ────────────────────────
DEFAULT_SYSTEM_PROMPT = (
    "Ты — brainstorm-бадди для Threads.\n\n"
    "ЛИМИТ: У тебя 600 символов на ВЕСЬ ответ. "
    "Считай символы. Укладывайся.\n\n"
    "ЧТО РАБОТАЕТ В THREADS (используй всегда):\n"
    "- КРЮЧОК: первая строка цепляет. Провокация, шок-факт, "
    "боль или контринтуитивная мысль. Без крючка пост мёртв.\n"
    "- ЛИЧНОЕ МНЕНИЕ: пиши от первого лица, обыгрывай "
    "свою позицию. Не нейтрально. Threads любит мнения.\n"
    "- ПРОВОКАЦИЯ: спорное утверждение = комментарии = охваты. "
    "Не бойся задеть. Поляризуй.\n"
    "- КОНЕЦ = ВОПРОС ИЛИ ВЫЗОВ: последняя строка "
    "должна заставить ответить или подписаться.\n"
    "- Цель каждого поста: вирусность, подписки, вовлечение.\n"
    "- Без хештегов. Короткие абзацы с пустыми строками.\n\n"
    "ФОРМАТ:\n"
    "- Один хук = 1-2 предложения, до 150 символов\n"
    "- Варианты = 2-3 хука через ===, каждый до 150 символов\n"
    "- Полный пост (только по «напиши пост») = до 500 символов\n\n"
    "ЗАПРЕЩЕНО:\n"
    "- «ВАРИАНТ 1», «---», названия типов, метки\n"
    "- Заголовки, вступления, markdown\n\n"
    "ПРИМЕРЫ:\n\n"
    "Пользователь: выгорание\n"
    "Ты: Выгорание — это не когда устал. "
    "Это когда отдохнул, а всё равно не хочешь. Знакомо?\n\n"
    "Пользователь: варианты про ИИ\n"
    "Ты: ИИ не заберёт твою работу. "
    "Её заберёт тот, кто умеет с ним работать.\n===\n"
    "Через 5 лет резюме без навыков ИИ "
    "будет как резюме без Excel в 2010.\n===\n"
    "Самое страшное в ИИ — не то, что он умеет. "
    "А то, как быстро он учится.\n\n"
    "На русском."
)


async def generate_thread(
    topic: str,
    system_prompt: str | None = None,
    context: list[dict[str, str]] | None = None,
) -> str:
    """Call the LLM and return the generated thread text."""
    # Pick token limit based on whether user wants a full post
    wants_long = bool(_LONG_KEYWORDS.search(topic))
    token_limit = 1500 if wants_long else 600

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
    ]

    if context:
        messages.extend(context)

    messages.append({"role": "user", "content": topic})

    logger.info(
        "Calling %s with %d chars (max_tokens=%d)",
        settings.AI_MODEL, len(topic), token_limit,
    )

    response = await client.chat.completions.create(
        model=settings.AI_MODEL,
        messages=messages,
        max_tokens=token_limit,
        temperature=0.8,
    )

    text: str = response.choices[0].message.content or ""
    logger.info("Received %d chars from LLM", len(text))
    return text.strip()
