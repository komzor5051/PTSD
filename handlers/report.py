"""Lesson report flow — accept voice/text report, notify managers."""
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import settings
from db import client as db
from services.crisis import detect_crisis, handle_crisis

logger = logging.getLogger(__name__)


async def handle(message: Message, state: dict, telegram_id: int,
                 text: str, transcript: str | None, **kwargs):
    """Accept voice or text lesson report."""
    module = state.get("current_module", "")
    lesson_num = module.replace("m", "").replace("_lesson", "")
    lesson_id = f"lesson_{lesson_num}"
    rating = state.get("lesson_rating")

    report_text = transcript or text
    if not report_text or len(report_text.strip()) < 3:
        await message.answer(
            "❓ Не получил отчёт. Отправь голосовое сообщение или напиши текстом.\n\n"
            "Расскажи как прошло упражнение."
        )
        return

    # Crisis check — report text may contain crisis markers
    crisis_markers = detect_crisis(report_text)
    if crisis_markers:
        await handle_crisis(message.bot, telegram_id, message.chat.id)
        return

    await db.save_lesson_report(
        user_id=telegram_id,
        lesson_id=lesson_id,
        report_text=report_text,
        voice_transcript=transcript,
        rating=rating,
    )

    await db.update_user_state(telegram_id,
        current_phase="awaiting_review",
        report_status="awaiting_review",
    )

    await _notify_managers(message, telegram_id, lesson_id, lesson_num, report_text, rating)

    await message.answer(
        "✅ *Отчёт отправлен!*\n\n"
        "Куратор проверит его в течение 24 часов.\n"
        "После проверки тебе придёт уведомление."
    )


async def _notify_managers(message: Message, user_id: int, lesson_id: str,
                            lesson_num: str, report_text: str, rating: int | None):
    """Send report to manager group with approve/reject buttons."""
    user = message.chat
    first_name = user.first_name or "боец"
    username = f"@{user.username}" if getattr(user, "username", None) else str(user_id)

    rating_text = f"{rating}/10" if rating is not None else "не указана"
    truncated = report_text[:500] + "..." if len(report_text) > 500 else report_text

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принять",
                callback_data=f"approve_report_{user_id}_{lesson_id}",
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_report_{user_id}_{lesson_id}",
            ),
        ]
    ])

    try:
        await message.bot.send_message(
            chat_id=settings.MANAGER_GROUP_CHAT_ID,
            text=(
                f"📋 *Новый отчёт*\n\n"
                f"*Участник:* {first_name} ({username})\n"
                f"*Урок:* {lesson_num}\n"
                f"*Оценка состояния:* {rating_text}\n\n"
                f"*Отчёт:*\n{truncated}"
            ),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Failed to notify managers: %s", e)


async def remind_review(message: Message, state: dict, telegram_id: int, **kwargs):
    """Resend pending report to manager group as a reminder (triggered by user)."""
    from handlers.lesson import _next_module, _current_lesson_id
    module = state.get("current_module", "")
    lesson_num = module.replace("m", "").replace("_lesson", "")
    lesson_id = f"lesson_{lesson_num}"

    report = await db.get_lesson_report(telegram_id, lesson_id)

    if not report:
        # Report not pending — check if it was already approved but state wasn't updated
        any_report = await db.get_latest_lesson_report(telegram_id, lesson_id)
        if any_report and any_report.get("status") == "approved":
            # Auto-fix stuck state: advance to next lesson
            next_mod = _next_module(module)
            if next_mod:
                await db.update_user_state(telegram_id,
                    current_module=next_mod,
                    current_phase="theory",
                    report_status=None,
                )
                next_num = next_mod.replace("m", "").replace("_lesson", "")
                next_lesson = await db.get_lesson(f"lesson_{next_num}")
                await message.answer(
                    f"✅ Твой отчёт уже был принят куратором!\n\nНачинаем урок {next_num} 🎖️",
                )
                if next_lesson:
                    await message.answer(
                        f"📖 *Урок {next_num}: {next_lesson['title']}*\n\n"
                        f"{next_lesson['theory_text']}",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="▶️ К практике", callback_data="lesson_practice"),
                        ]]),
                    )
            else:
                await db.update_user_state(telegram_id, current_module="course_complete", current_phase=None)
                await message.answer("🎖️ Твой отчёт принят и курс завершён! Поздравляю!")
        else:
            await message.answer("⚠️ Отчёт не найден. Возможно, куратор уже проверяет его.")
        return

    user = message.chat
    first_name = user.first_name or "боец"
    username = f"@{user.username}" if getattr(user, "username", None) else str(telegram_id)
    rating = report.get("rating")
    report_text = report.get("report_text", "")
    rating_text = f"{rating}/10" if rating is not None else "не указана"
    truncated = report_text[:500] + "..." if len(report_text) > 500 else report_text

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_report_{telegram_id}_{lesson_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_report_{telegram_id}_{lesson_id}"),
    ]])

    try:
        await message.bot.send_message(
            chat_id=settings.MANAGER_GROUP_CHAT_ID,
            text=(
                f"🔔 *НАПОМИНАНИЕ*\n\n"
                f"*Участник:* {first_name} ({username})\n"
                f"*Урок:* {lesson_num}\n"
                f"*Оценка состояния:* {rating_text}\n\n"
                f"*Отчёт:*\n{truncated}"
            ),
            reply_markup=keyboard,
        )
        await message.answer("✅ Напоминание отправлено куратору.")
    except Exception as e:
        logger.error("Failed to send reminder to managers: %s", e)
        await message.answer("⚠️ Не удалось отправить напоминание. Попробуй позже.")
