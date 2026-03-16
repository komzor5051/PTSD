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
    if settings.MANAGER_GROUP_CHAT_ID == 0:
        await message.answer("⚠️ Система отчётов временно недоступна. Обратись к куратору.")
        return

    module = state.get("current_module", "")
    if not module.startswith("m") or not module.endswith("_lesson"):
        logger.error("report.handle called with invalid module=%s for user %s", module, telegram_id)
        await message.answer("⚠️ Не могу принять отчёт — обратись к куратору.")
        return

    lesson_num = module.replace("m", "").replace("_lesson", "")
    lesson_id = f"lesson_{lesson_num}"

    progress = await db.get_lesson_progress(telegram_id)
    lesson_progress = next((p for p in progress if p.get("lesson_id") == lesson_id), None)
    rating = lesson_progress.get("rating") if lesson_progress else None

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

    sent = await _notify_managers(message, telegram_id, lesson_id, lesson_num, report_text, rating)

    if sent:
        await message.answer(
            "✅ *Отчёт отправлен!*\n\n"
            "Куратор проверит его в течение 24 часов.\n"
            "После проверки тебе придёт уведомление."
        )
    else:
        await message.answer(
            "✅ *Отчёт сохранён,* но уведомление куратору не доставлено.\n\n"
            "Попробуй нажать «Напомнить куратору» позже, или обратись к координатору.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔔 Напомнить куратору", callback_data="remind_report"),
            ]]),
        )


async def _notify_managers(message: Message, user_id: int, lesson_id: str,
                            lesson_num: str, report_text: str, rating: int | None) -> bool:
    """Send report to manager group with approve/reject buttons. Returns True if sent.

    Uses parse_mode=None so NO user content (username, report text) can break delivery.
    """
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
                f"📋 Новый отчёт\n\n"
                f"Участник: {first_name} ({username})\n"
                f"Урок: {lesson_num}\n"
                f"Оценка состояния: {rating_text}\n\n"
                f"Отчёт:\n{truncated}"
            ),
            reply_markup=keyboard,
            parse_mode=None,
        )
        return True
    except Exception as e:
        logger.error("Failed to notify managers (chat_id=%s): %s", settings.MANAGER_GROUP_CHAT_ID, e)
        return False


async def remind_review(message: Message, state: dict, telegram_id: int, **kwargs):
    """Resend pending report to manager group as a reminder (triggered by user)."""
    if settings.MANAGER_GROUP_CHAT_ID == 0:
        await message.answer("⚠️ Система отчётов временно недоступна. Обратись к куратору напрямую.")
        return

    try:
        from handlers.lesson import _next_module, _current_lesson_id
        module = state.get("current_module", "")
        if not module.startswith("m") or not module.endswith("_lesson"):
            await message.answer("⚠️ Нет активного урока. Обратись к куратору.")
            return
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

        first_name = state.get("ptsd_users", {}).get("first_name", "боец")
        user = message.chat
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
                    f"🔔 НАПОМИНАНИЕ\n\n"
                    f"Участник: {first_name} ({username})\n"
                    f"Урок: {lesson_num}\n"
                    f"Оценка состояния: {rating_text}\n\n"
                    f"Отчёт:\n{truncated}"
                ),
                reply_markup=keyboard,
                parse_mode=None,
            )
            await message.answer("✅ Напоминание отправлено куратору.")
        except Exception as e:
            logger.error("remind_review: send_message to manager group failed (chat_id=%s): %s",
                         settings.MANAGER_GROUP_CHAT_ID, e)
            await message.answer(
                "⚠️ Не удалось связаться с группой кураторов.\n\n"
                "Отчёт сохранён в системе — куратор проверит его при следующем входе."
            )

    except Exception as e:
        logger.error("remind_review failed for user %s: %s", telegram_id, e, exc_info=True)
        try:
            await message.answer("⚠️ Произошла ошибка. Попробуй позже или обратись к куратору.")
        except Exception:
            logger.error("Failed to even send error message to user %s", telegram_id)
