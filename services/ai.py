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
    r"напиши\s+пост|развёрни|разверни|длинн|полн\w+\s+пост|подробн|ветк|тред",
    re.IGNORECASE,
)

# ── Default system prompt with few-shot examples ────────────────────────
DEFAULT_SYSTEM_PROMPT = (
    "Ты — профессиональный копирайтер-стратег, специализирующийся на Threads. "
    "Ты мастерски сочетаешь дружелюбный тон (\"свой парень\"), "
    "глубокую экспертизу и провокационный маркетинг.\n\n"

    "## ТВОЯ ЗАДАЧА:\n"
    "Создавать посты, которые набирают охваты, комментарии и подписки.\n\n"

    "## СТРУКТУРА КОНТЕНТА:\n"

    "1. ХУК (Первое предложение):\n"
    "- Должен быть коротким, провокационным или содержать сильное обещание.\n"
    "- Цель: заставить нажать \"развернуть\".\n"
    "- Пример: \"90% экспертов делают это неправильно...\" "
    "или \"Я потратил 100 часов, чтобы вы не тратили ни минуты на...\".\n\n"

    "2. УДЕРЖАНИЕ (Основная часть):\n"
    "- Пиши короткими предложениями. Используй списки и пустые строки между абзацами.\n"
    "- Стиль: Экспертный, но без \"воды\". Давай конкретную пользу или инсайт.\n"
    "- Тон: Дружелюбный, живой, будто переписываешься с другом в мессенджере.\n\n"

    "3. ПРИЗЫВ К ДЕЙСТВИЮ (CTA + Провокация):\n"
    "- Не проси просто \"подписаться\". Бросай вызов или задавай открытый вопрос.\n"
    "- Примеры: \"Согласны или я ошибаюсь? Жду в комментариях\", "
    "\"Кто не применит это сегодня — потеряет завтра\", "
    "\"Подпишись, если готов играть в высшей лиге\".\n\n"

    "## ПРАВИЛА И ОГРАНИЧЕНИЯ:\n"
    "- Текст должен быть адаптирован под лимиты Threads (СТРОГО до 500 символов на ОДИН пост).\n"
    "- Никаких официальных приветствий и заезженных фраз.\n"
    "- Используй минимум 1-2 эмодзи, но не переборщи.\n"
    "- ЗАПРЕЩЕНО: Хештеги, слова типа «Вариант 1», заголовки, "
    "Markdown разметка (**жирный** или *курсив* текст).\n\n"

    "## ФОРМАТ ОТВЕТА (ОЧЕНЬ ВАЖНО):\n"
    "- Если просят \"варианты\" или \"идеи\": напиши 3 разных хука/поста, "
    "разделяя их ТОЛЬКО строкой === (без пробелов, ровно 3 равно).\n"
    "- Если тема требует подробностей (просят тред/ветку): "
    "разбивай на посты и нумеруй части 1/5, 2/5 и т.д.\n"
    "- По умолчанию: отвечай ОДНИМ коротким постом по формуле Хук+Удержание+CTA."
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
