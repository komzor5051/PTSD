"""Main message router — mirrors MASTER_ROUTER_v2 routing logic exactly."""
import logging

from aiogram import Router
from aiogram.types import Message, CallbackQuery

from db import client as db
from services.crisis import detect_crisis, handle_crisis

logger = logging.getLogger(__name__)
main_router = Router()


async def _get_voice_text(message: Message) -> str | None:
    """Download and transcribe voice message. Returns None if not a voice."""
    if not message.voice:
        return None
    from services.openai_service import transcribe
    file = await message.bot.get_file(message.voice.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    return await transcribe(file_bytes.read(), "voice.ogg")


def _determine_routing(state: dict | None, callback: str, text: str) -> str:
    """Pure routing logic. Maps to Determine Routing node in MASTER_ROUTER_v2."""
    # Manager callbacks bypass state check — managers may not have a bot state
    if (callback.startswith("approve_report_") or callback.startswith("reject_report_") or
            callback.startswith("reject_reason_")):
        return "manager_review"

    if state is None:
        return "new_user"

    module = state.get("current_module", "idle")
    phase = state.get("current_phase")

    # /start always shows return menu — must be before any module-based routing
    if text == "/start":
        return "return_user"

    # Morning mood response
    if callback.startswith("morning_mood_"):
        return "morning_check_response"

    # Onboarding callbacks
    if callback in {"onboarding_accept", "onboarding_info", "consent_yes", "consent_no",
                    "restart_onboarding", "pause_onboarding", "reminder_morning", "reminder_evening"}:
        return "onboarding"

    # Reminder settings
    if (callback.startswith("snooze_") or callback.startswith("change_to_") or
            callback in {"pause_week", "show_reminder_settings"}):
        return "reminder_settings"

    # Psychologist
    if callback == "chat_psychologist" or module == "ai_chat":
        return "psychologist"

    # Weekly check response
    if module == "weekly_check":
        return "weekly_check"

    # Awaiting report (voice or text)
    if phase == "awaiting_report":
        return "report"

    # Awaiting manager review — show status
    if phase == "awaiting_review":
        return "show_review_status"

    # Questionnaire
    if (callback in {"start_questionnaire", "questionnaire_continue"} or
            module == "screening" or callback in {"answer_yes", "answer_no"}):
        return "questionnaire"

    # Lesson flow
    if (callback in {"start_course", "lesson_continue", "lesson_complete"} or
            callback.startswith("lesson_") or callback.startswith("rating_") or
            (module and module.startswith("m"))):
        return "lesson"

    return "idle_menu"


@main_router.message()
async def handle_message(message: Message):
    telegram_id = message.from_user.id
    text = message.text or ""

    # Transcribe voice if needed
    transcript = None
    if message.voice:
        try:
            transcript = await _get_voice_text(message)
            text = transcript or ""
        except Exception as e:
            logger.error("Voice transcription failed: %s", e)
            await message.answer("❌ Не удалось распознать голосовое. Попробуй ещё раз или напиши текстом.")
            return

    state = await db.get_user_state(telegram_id)
    routing = _determine_routing(state, "", text)
    await _dispatch(message, state, routing, text, transcript, callback_data="", telegram_id=telegram_id)


@main_router.callback_query()
async def handle_callback(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    callback_data = callback.data or ""

    await callback.answer()  # Remove loading spinner

    # Delete the previous message with buttons (mirrors n8n deleteMessage pattern)
    try:
        await callback.message.delete()
    except Exception:
        pass  # continueOnFail: true

    state = await db.get_user_state(telegram_id)
    routing = _determine_routing(state, callback_data, "")
    await _dispatch(callback.message, state, routing, "", None, callback_data=callback_data, telegram_id=telegram_id)


async def _dispatch(message: Message, state: dict | None, routing: str,
                    text: str, transcript: str | None, callback_data: str,
                    telegram_id: int | None = None):
    """Dispatch to the appropriate handler module."""
    from handlers import (
        onboarding, questionnaire, lesson, report,
        manager, psychologist, weekly_check, reminder_settings,
    )

    # telegram_id must come from from_user.id (not message.chat.id which is wrong in group chats)
    effective_id = telegram_id if telegram_id is not None else message.chat.id

    ctx = {
        "message": message,
        "state": state,
        "text": text,
        "transcript": transcript,
        "callback_data": callback_data,
        "telegram_id": effective_id,
        "user_id": effective_id,
        "first_name": (state or {}).get("ptsd_users", {}).get("first_name", "боец") if state else "боец",
    }

    match routing:
        case "new_user":
            await onboarding.handle_new_user(**ctx)
        case "return_user":
            await onboarding.handle_return_user(**ctx)
        case "onboarding":
            await onboarding.handle(**ctx)
        case "questionnaire":
            await questionnaire.handle(**ctx)
        case "lesson":
            await lesson.handle(**ctx)
        case "report":
            await report.handle(**ctx)
        case "manager_review":
            await manager.handle(**ctx)
        case "show_review_status":
            await message.answer("⏳ Твой отчёт на проверке у куратора. Ожидай — обычно до 24 часов.")
        case "psychologist":
            await psychologist.handle(**ctx)
        case "weekly_check":
            await weekly_check.handle(**ctx)
        case "morning_check_response":
            await weekly_check.handle_morning_mood(**ctx)
        case "reminder_settings":
            await reminder_settings.handle(**ctx)
        case "idle_menu":
            await _send_idle_menu(message, state)
        case _:
            await _send_idle_menu(message, state)


async def _send_idle_menu(message: Message, state: dict | None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not state:
        return

    module = state.get("current_module", "idle")
    first_name = state.get("ptsd_users", {}).get("first_name", "боец") if state else "боец"
    total_rewards = state.get("ptsd_users", {}).get("total_rewards", 0) if state else 0

    if module == "course_complete":
        text = f"🎖️ *{first_name}, ты завершил программу!*\n\nНакоплено наград: *{total_rewards}₽*"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist"),
        ]])
    elif module and module.startswith("m"):
        lesson_num = module.replace("m", "").replace("_lesson", "")
        text = f"👋 *{first_name}*, продолжаем реабилитацию.\n\nТекущий урок: *{lesson_num}*"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Продолжить урок", callback_data="lesson_continue")],
            [InlineKeyboardButton(text="💬 Психолог", callback_data="chat_psychologist")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="show_reminder_settings")],
        ])
    else:
        text = f"👋 *{first_name}*, рад видеть тебя снова."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist"),
        ]])

    await message.answer(text, reply_markup=keyboard)
