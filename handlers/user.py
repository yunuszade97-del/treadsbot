"""
User-facing bot handlers (Router).

Chat-slot based UX with inline keyboards, FSM for chat creation,
context memory per slot, and context/profile management commands.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func

from config import settings
from database.models import ThreadsProfile
from database.session import async_session
from services.ai import generate_thread
from services.usage import (
    check_and_track_usage,
    get_or_create_user,
    get_remaining_requests,
)

logger = logging.getLogger(__name__)
router = Router(name="user")

MAX_CHATS = 5


# ── FSM States ──────────────────────────────────────────────────────────


class ChatCreation(StatesGroup):
    waiting_name = State()
    waiting_style = State()


class EditStyle(StatesGroup):
    waiting_new_style = State()


# ── Keyboard builders ───────────────────────────────────────────────────


async def build_chats_keyboard(
    user_id: int, session=None
) -> InlineKeyboardMarkup:
    """Build inline keyboard with user's chat slots."""
    own_session = session is None
    if own_session:
        session = async_session()
        ctx = session
    else:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop():
            yield session

        ctx = _noop()

    async with ctx:
        user = await get_or_create_user(session, user_id)
        stmt = select(ThreadsProfile).where(ThreadsProfile.user_id == user.id)
        result = await session.execute(stmt)
        profiles = result.scalars().all()

    buttons: list[list[InlineKeyboardButton]] = []
    for p in profiles:
        prefix = "🟢" if user.active_profile_id == p.id else "📝"
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix} {p.profile_name}",
                callback_data=f"select_chat:{p.id}",
            )
        ])

    if len(profiles) < MAX_CHATS:
        buttons.append([
            InlineKeyboardButton(
                text="➕ Создать новый чат",
                callback_data="create_chat",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def active_chat_keyboard() -> InlineKeyboardMarkup:
    """Buttons shown when inside an active chat."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать стиль", callback_data="edit_style"),
            InlineKeyboardButton(text="🗑 Очистить контекст", callback_data="clear_context"),
        ],
        [
            InlineKeyboardButton(text="🔀 Сменить чат", callback_data="switch_chat"),
            InlineKeyboardButton(text="🗑 Удалить чат", callback_data="delete_chat"),
        ],
    ])


def strip_markdown(text: str) -> str:
    """Remove markdown formatting symbols from AI output."""
    # Remove bold **text** / __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Remove italic *text* / _text_
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    # Remove headers ### / ## / #
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Remove blockquote >
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
    # Remove code backticks
    text = re.sub(r'`{1,3}', '', text)
    return text.strip()


# ── /start ──────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    """Register + show chat menu."""
    await state.clear()
    async with async_session() as session:
        await get_or_create_user(session, message.from_user.id)

    kb = await build_chats_keyboard(message.from_user.id)
    await message.answer(
        "👋 <b>Добро пожаловать в Threads Copilot!</b>\n\n"
        "Выберите чат или создайте новый.\n"
        "Каждый чат — это отдельный стиль генерации с памятью контекста.\n\n"
        f"🆓 Бесплатно: <b>{settings.DAILY_FREE_LIMIT}</b> запросов/день",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── /chats & /switch ────────────────────────────────────────────────────


@router.message(Command("chats"))
@router.message(Command("switch"))
async def cmd_chats(message: types.Message, state: FSMContext) -> None:
    """Show all chat slots."""
    await state.clear()
    kb = await build_chats_keyboard(message.from_user.id)
    await message.answer(
        "📋 <b>Ваши чаты:</b>\n"
        "🟢 — активный чат\n\n"
        "Выберите чат или создайте новый:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── /clear ──────────────────────────────────────────────────────────────


@router.message(Command("clear"))
async def cmd_clear(message: types.Message) -> None:
    """Clear context of the active chat."""
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        if not user.active_profile_id:
            await message.answer("⚠️ Сначала выберите чат через /chats")
            return
        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            profile.clear_context()
            await session.commit()
            await message.answer(
                f"🗑 Контекст чата <b>{profile.profile_name}</b> очищен!",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer("⚠️ Чат не найден. Выберите через /chats")


# ── /pro_status ─────────────────────────────────────────────────────────


@router.message(Command("pro_status"))
async def cmd_pro_status(message: types.Message) -> None:
    """Show subscription tier and remaining daily requests."""
    async with async_session() as session:
        is_pro, remaining = await get_remaining_requests(
            session, message.from_user.id
        )

    if is_pro:
        text = "⭐ Вы — <b>Pro</b> пользователь. Безлимитные запросы!"
    else:
        text = (
            f"🆓 <b>Бесплатный</b> план\n"
            f"Осталось запросов сегодня: <b>{remaining}</b> / {settings.DAILY_FREE_LIMIT}"
        )

    await message.answer(text, parse_mode=ParseMode.HTML)


# ── Callback: select chat ───────────────────────────────────────────────


@router.callback_query(F.data.startswith("select_chat:"))
async def cb_select_chat(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Activate a chat slot."""
    await state.clear()
    profile_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == profile_id,
            ThreadsProfile.user_id == user.id,
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if not profile:
            await callback.answer("❌ Чат не найден", show_alert=True)
            return

        user.active_profile_id = profile.id
        await session.commit()

    await callback.message.edit_text(
        f"🟢 Активный чат: <b>{profile.profile_name}</b>\n\n"
        f"🎭 Стиль: <i>{profile.system_prompt[:100]}{'…' if len(profile.system_prompt) > 100 else ''}</i>\n\n"
        "Отправьте тему — и я создам пост!",
        parse_mode=ParseMode.HTML,
        reply_markup=active_chat_keyboard(),
    )
    await callback.answer()


# ── Callback: create chat ───────────────────────────────────────────────


@router.callback_query(F.data == "create_chat")
async def cb_create_chat(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Start FSM for creating a new chat slot."""
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        count_stmt = (
            select(func.count())
            .select_from(ThreadsProfile)
            .where(ThreadsProfile.user_id == user.id)
        )
        count_result = await session.execute(count_stmt)
        count = count_result.scalar() or 0

    if count >= MAX_CHATS:
        await callback.answer(
            f"❌ Максимум {MAX_CHATS} чатов. Удалите один, чтобы создать новый.",
            show_alert=True,
        )
        return

    await state.set_state(ChatCreation.waiting_name)
    await callback.message.edit_text(
        "📝 <b>Создание нового чата</b>\n\n"
        "Шаг 1/2: Как назовём чат?\n\n"
        "Примеры: <i>IT Блог, Мотивация, Бизнес, Лайфстайл, Юмор</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# ── FSM: chat name ──────────────────────────────────────────────────────


@router.message(ChatCreation.waiting_name)
async def fsm_chat_name(message: types.Message, state: FSMContext) -> None:
    """Receive chat name, ask for style."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Введите название чата:")
        return
    if len(name) > 128:
        await message.answer("⚠️ Слишком длинное название (макс. 128 символов)")
        return

    await state.update_data(chat_name=name)
    await state.set_state(ChatCreation.waiting_style)
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Шаг 2/2: Опишите стиль генерации.\n\n"
        "<b>Примеры:</b>\n"
        "• <i>Пиши мотивационные посты как лайф-коуч</i>\n"
        "• <i>Генерируй IT-контент просто и с юмором</i>\n"
        "• <i>Пиши как предприниматель, коротко и по делу</i>",
        parse_mode=ParseMode.HTML,
    )


# ── FSM: chat style ─────────────────────────────────────────────────────


@router.message(ChatCreation.waiting_style)
async def fsm_chat_style(message: types.Message, state: FSMContext) -> None:
    """Receive style description, create the chat slot."""
    style = (message.text or "").strip()
    if not style:
        await message.answer("⚠️ Опишите стиль генерации:")
        return

    data = await state.get_data()
    name = data["chat_name"]

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)

        profile = ThreadsProfile(
            user_id=user.id,
            profile_name=name,
            system_prompt=style,
        )
        session.add(profile)
        await session.flush()  # get profile.id

        user.active_profile_id = profile.id
        await session.commit()

    await state.clear()
    await message.answer(
        f"🎉 Чат <b>{name}</b> создан и активирован!\n\n"
        f"🎭 Стиль: <i>{style[:100]}{'…' if len(style) > 100 else ''}</i>\n\n"
        "Теперь просто отправьте тему для генерации поста.",
        parse_mode=ParseMode.HTML,
        reply_markup=active_chat_keyboard(),
    )


# ── Callback: clear context ────────────────────────────────────────────


@router.callback_query(F.data == "clear_context")
async def cb_clear_context(callback: types.CallbackQuery) -> None:
    """Clear context of the active chat."""
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        if not user.active_profile_id:
            await callback.answer("⚠️ Нет активного чата", show_alert=True)
            return
        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            profile.clear_context()
            await session.commit()
            await callback.answer("🗑 Контекст очищен!", show_alert=True)
        else:
            await callback.answer("⚠️ Чат не найден", show_alert=True)


# ── Callback: switch chat ──────────────────────────────────────────────


@router.callback_query(F.data == "switch_chat")
async def cb_switch_chat(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Show chat selection menu."""
    await state.clear()
    kb = await build_chats_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "📋 <b>Ваши чаты:</b>\n"
        "🟢 — активный чат\n\n"
        "Выберите чат или создайте новый:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    await callback.answer()


# ── Callback: delete chat ──────────────────────────────────────────────


@router.callback_query(F.data == "delete_chat")
async def cb_delete_chat(callback: types.CallbackQuery) -> None:
    """Delete the currently active chat."""
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        if not user.active_profile_id:
            await callback.answer("⚠️ Нет активного чата", show_alert=True)
            return

        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id,
            ThreadsProfile.user_id == user.id,
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if not profile:
            await callback.answer("⚠️ Чат не найден", show_alert=True)
            return

        name = profile.profile_name
        user.active_profile_id = None
        await session.delete(profile)
        await session.commit()

    kb = await build_chats_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        f"🗑 Чат <b>{name}</b> удалён.\n\n"
        "Выберите другой чат или создайте новый:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    await callback.answer()


# ── Callback: edit style ───────────────────────────────────────────────


@router.callback_query(F.data == "edit_style")
async def cb_edit_style(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Start FSM to edit the active chat's style."""
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        if not user.active_profile_id:
            await callback.answer("⚠️ Нет активного чата", show_alert=True)
            return
        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

    if not profile:
        await callback.answer("⚠️ Чат не найден", show_alert=True)
        return

    await state.set_state(EditStyle.waiting_new_style)
    await callback.message.edit_text(
        f"✏️ <b>Редактирование стиля: {profile.profile_name}</b>\n\n"
        f"Текущий стиль:\n<i>{profile.system_prompt[:200]}{'…' if len(profile.system_prompt) > 200 else ''}</i>\n\n"
        "Отправьте новое описание стиля:",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# ── FSM: edit style ────────────────────────────────────────────────────


@router.message(EditStyle.waiting_new_style)
async def fsm_edit_style(message: types.Message, state: FSMContext) -> None:
    """Receive new style and update the active profile."""
    new_style = (message.text or "").strip()
    if not new_style:
        await message.answer("⚠️ Введите новый стиль:")
        return

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        if not user.active_profile_id:
            await message.answer("⚠️ Нет активного чата")
            await state.clear()
            return
        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if not profile:
            await message.answer("⚠️ Чат не найден")
            await state.clear()
            return

        profile.system_prompt = new_style
        profile.clear_context()  # reset context with new style
        await session.commit()
        name = profile.profile_name

    await state.clear()
    await message.answer(
        f"✅ Стиль чата <b>{name}</b> обновлён!\n\n"
        f"🎭 Новый стиль: <i>{new_style[:100]}{'…' if len(new_style) > 100 else ''}</i>\n\n"
        "Контекст очищен. Отправьте тему для генерации.",
        parse_mode=ParseMode.HTML,
        reply_markup=active_chat_keyboard(),
    )


# ── Text handler (thread generation) ───────────────────────────────────


@router.message(F.text)
async def handle_text(message: types.Message) -> None:
    """Generate a Threads post using the active chat's persona + context."""
    topic = (message.text or "").strip()
    if not topic:
        return

    # Check usage limits
    async with async_session() as session:
        allowed = await check_and_track_usage(session, message.from_user.id)

    if not allowed:
        await message.answer(
            f"🚫 Дневной лимит в <b>{settings.DAILY_FREE_LIMIT}</b> запросов исчерпан.\n"
            "Перейдите на <b>Pro</b> для безлимитного доступа!",
            parse_mode=ParseMode.HTML,
        )
        return

    # Load active profile with context
    system_prompt = None
    context = None
    profile_id = None

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)

        if not user.active_profile_id:
            kb = await build_chats_keyboard(message.from_user.id, session)
            await message.answer(
                "⚠️ Сначала выберите или создайте чат:",
                reply_markup=kb,
            )
            return

        stmt = select(ThreadsProfile).where(
            ThreadsProfile.id == user.active_profile_id
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile:
            system_prompt = profile.system_prompt
            context = profile.get_context()
            profile_id = profile.id

    # Show "typing…"
    await message.bot.send_chat_action(
        chat_id=message.chat.id, action="typing"
    )

    try:
        thread_text = await generate_thread(
            topic, system_prompt=system_prompt, context=context
        )
    except Exception:
        logger.exception("LLM generation failed for user %s", message.from_user.id)
        await message.answer(
            "⚠️ Произошла ошибка при генерации. Попробуйте позже."
        )
        return

    if not thread_text:
        await message.answer("⚠️ ИИ вернул пустой ответ. Попробуйте переформулировать.")
        return

    # Clean markdown formatting
    thread_text = strip_markdown(thread_text)

    # Split into variants by ===
    variants = [v.strip() for v in thread_text.split("===") if v.strip()]

    # Save to context
    if profile_id:
        async with async_session() as session:
            stmt = select(ThreadsProfile).where(ThreadsProfile.id == profile_id)
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()
            if profile:
                profile.add_to_context(topic, thread_text)
                await session.commit()

    # Send each variant as a separate message
    if len(variants) > 1:
        for idx, variant in enumerate(variants, 1):
            await message.answer(f"📝 Вариант {idx}\n\n{variant}")
    else:
        # Single response
        for i in range(0, len(thread_text), 4000):
            await message.answer(thread_text[i : i + 4000])

