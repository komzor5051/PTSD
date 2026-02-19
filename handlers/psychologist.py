"""AI Psychologist flow — GPT-4 chat with history and crisis detection."""
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db
from services import openai_service
from services.crisis import detect_crisis, handle_crisis, CRISIS_MESSAGE

logger = logging.getLogger(__name__)


async def handle(message: Message, callback_data: str, state: dict,
                 telegram_id: int, text: str, **kwargs):
    # Entry point — switching to ai_chat mode
    if callback_data == "chat_psychologist":
        prev_module = state.get("current_module", "idle")
        await db.update_user_state(telegram_id,
            current_module="ai_chat",
            ai_chat_return_module=prev_module,
        )
        await message.answer(
            "💬 *ИИ-психолог на связи*\n\n"
            "Расскажи, что тебя беспокоит. Я здесь чтобы выслушать и помочь.\n\n"
            "_Чтобы вернуться в программу, нажми кнопку ниже._",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Вернуться к занятиям", callback_data="return_to_lesson"),
            ]]),
        )
        return

    if callback_data == "return_to_lesson":
        return_module = state.get("ai_chat_return_module") or "idle"
        await db.update_user_state(telegram_id, current_module=return_module)
        fresh_state = await db.get_user_state(telegram_id)
        first_name = (state.get("ptsd_users") or {}).get("first_name", "боец")
        from handlers.onboarding import handle_return_user
        await handle_return_user(
            message=message,
            telegram_id=telegram_id,
            first_name=first_name,
            state=fresh_state,
            callback_data="",
            text="",
            transcript=None,
            user_id=telegram_id,
        )
        return

    # Regular message in ai_chat mode
    if not text:
        await message.answer("Напиши мне что-нибудь или отправь голосовое.")
        return

    # Crisis detection
    markers = detect_crisis(text)
    crisis_detected = bool(markers)

    await db.save_chat_message(telegram_id, "user", text,
                                crisis_detected=crisis_detected, crisis_markers=markers)

    if crisis_detected:
        await handle_crisis(message.bot, telegram_id, message.chat.id)
        await db.save_chat_message(telegram_id, "assistant", CRISIS_MESSAGE, crisis_detected=True)
        return

    history = await db.get_chat_history(telegram_id)
    openai_history = [{"role": h["role"], "content": h["content"]} for h in history]

    try:
        response = await openai_service.chat_with_psychologist(openai_history, text)
    except Exception as e:
        logger.error("Psychologist GPT-4 call failed: %s", e)
        await message.answer("⚠️ Временная ошибка. Попробуй чуть позже.")
        return

    await db.save_chat_message(telegram_id, "assistant", response)

    await message.answer(
        response,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 К занятиям", callback_data="return_to_lesson"),
        ]]),
    )
