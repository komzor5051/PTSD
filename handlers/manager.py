"""Manager review flow — approve/reject lesson reports."""
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db
from handlers.lesson import _next_module

logger = logging.getLogger(__name__)

# manager_id → (user_id, lesson_id) — ожидаем ввод причины отклонения
_pending_rejections: dict[int, tuple[int, str]] = {}


async def handle(message: Message, callback_data: str, telegram_id: int, **kwargs):
    """Handle approve/reject callbacks from manager group."""
    if callback_data.startswith("approve_report_"):
        parts = callback_data.split("_", 3)
        if len(parts) != 4:
            await message.answer("⚠️ Некорректный callback кнопки.")
            return
        _, _, user_id_str, lesson_id = parts
        try:
            user_id = int(user_id_str)
        except ValueError:
            await message.answer(f"⚠️ Некорректный user_id в callback: {user_id_str!r}")
            return
        await _approve(message, user_id, lesson_id, telegram_id)

    elif callback_data.startswith("reject_report_"):
        parts = callback_data.split("_", 3)
        if len(parts) != 4:
            await message.answer("⚠️ Некорректный callback кнопки.")
            return
        _, _, user_id_str, lesson_id = parts
        try:
            user_id = int(user_id_str)
        except ValueError:
            await message.answer(f"⚠️ Некорректный user_id в callback: {user_id_str!r}")
            return
        await _ask_reject_reason(message, user_id, lesson_id, telegram_id)


async def handle_rejection_reason(message: Message, telegram_id: int, text: str, **kwargs):
    """Called when manager types rejection reason after clicking Отклонить."""
    pending = _pending_rejections.pop(telegram_id, None)
    if not pending:
        return
    user_id, lesson_id = pending
    await _reject(message, user_id, lesson_id, telegram_id, text.strip())


async def _approve(message: Message, user_id: int, lesson_id: str, manager_id: int):
    # Validate lesson_id format (e.g. "lesson_1" .. "lesson_10")
    lesson_num_str = lesson_id.replace("lesson_", "")
    if not lesson_num_str.isdigit():
        await message.answer(
            f"⚠️ Устаревшая кнопка (lesson_id={lesson_id!r}).\n"
            "Попроси участника заново отправить отчёт."
        )
        return

    # ── Phase 1: DB operations (critical) ────────────────────────────────────
    # If anything here fails, we abort and show manager an error.
    # State is advanced BEFORE reward so a reward failure never leaves user stuck.
    try:
        # Idempotency check — prevent double reward if two managers click simultaneously
        report = await db.get_latest_lesson_report(user_id, lesson_id)
        if not report or report.get("status") != "pending":
            await message.answer("ℹ️ Отчёт уже обработан.")
            return

        await db.rpc_approve_report(user_id, lesson_id, manager_id, "Принято")

        lesson_num = lesson_id.replace("lesson_", "")
        current_module = f"m{lesson_num}_lesson"
        next_mod = _next_module(current_module)

        if next_mod:
            await db.update_user_state(user_id,
                current_module=next_mod,
                current_phase="theory",
                report_status=None,
            )
            await db.rpc_update_activity_on_lesson(user_id, completed=True)
        else:
            await db.update_user_state(user_id, current_module="course_complete", current_phase=None)

        lesson = await db.get_lesson(lesson_id)
        reward = lesson.get("reward_rub", 200) if lesson else 200
        await db.rpc_increment_rewards(user_id, reward)

    except Exception as e:
        logger.error("DB error during approve for user %s lesson %s: %s", user_id, lesson_id, e)
        await message.answer(f"⚠️ Ошибка БД при принятии отчёта: {e}")
        return

    # ── Phase 2: Notify user (best-effort) ───────────────────────────────────
    # DB is already committed. Telegram delivery failure must NOT roll back state
    # or block manager confirmation. Manager always sees the real outcome.
    try:
        if next_mod:
            next_num = next_mod.replace("m", "").replace("_lesson", "")
            next_lesson_id = f"lesson_{next_num}"
            next_lesson = await db.get_lesson(next_lesson_id)

            await message.bot.send_message(
                user_id,
                f"✅ *Отчёт принят!*\n\n"
                f"Начислено: *{reward}₽*\n\n"
                f"Начинаем урок {next_num}! 🎖️",
            )

            if next_lesson:
                await message.bot.send_message(
                    user_id,
                    f"📖 *Урок {next_num}: {next_lesson['title']}*\n\n"
                    f"{next_lesson['theory_text']}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="▶️ К практике", callback_data="lesson_practice"),
                    ]]),
                )
            else:
                logger.error("Next lesson %s not found in DB during approve", next_lesson_id)
                await message.bot.send_message(
                    user_id,
                    f"▶️ Урок {next_num} готов к прохождению.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=f"▶️ Урок {next_num}", callback_data="lesson_continue"),
                    ]]),
                )
        else:
            await message.bot.send_message(
                user_id,
                f"🎖️ *Поздравляю! Ты завершил всю программу реабилитации!*\n\n"
                f"Начислено: *{reward}₽*\n\n"
                "Это большой шаг. Ты справился. ✅"
            )

    except Exception as e:
        logger.error("Failed to notify user %s after approve (DB already committed): %s", user_id, e)
        await message.answer(
            f"✅ Отчёт пользователя {user_id} принят, начислено {reward}₽.\n"
            f"⚠️ Уведомление участнику не доставлено — скажи ему написать /start."
        )
        return

    await message.answer(f"✅ Отчёт пользователя {user_id} принят, начислено {reward}₽")


async def _ask_reject_reason(message: Message, user_id: int, lesson_id: str, manager_id: int):
    """Store pending rejection and ask manager to type reason."""
    _pending_rejections[manager_id] = (user_id, lesson_id)
    await message.answer(
        f"✍️ Напиши причину отклонения отчёта пользователя {user_id} следующим сообщением."
    )


async def _reject(message: Message, user_id: int, lesson_id: str, manager_id: int, reason: str):
    # ── Phase 1: DB operations ────────────────────────────────────────────────
    try:
        await db.rpc_reject_report(user_id, lesson_id, manager_id, reason)
        await db.update_user_state(user_id, current_phase="awaiting_report", report_status="awaiting_report")
    except Exception as e:
        logger.error("DB error during reject for user %s lesson %s: %s", user_id, lesson_id, e)
        await message.answer(f"⚠️ Ошибка БД при отклонении отчёта: {e}")
        return

    # ── Phase 2: Notify user (best-effort) ───────────────────────────────────
    try:
        await message.bot.send_message(
            user_id,
            f"❌ *Отчёт отклонён*\n\n"
            f"Причина: {reason}\n\n"
            "Пожалуйста, повтори упражнение и отправь новый отчёт."
        )
    except Exception as e:
        logger.error("Failed to notify user %s after reject (DB already committed): %s", user_id, e)
        await message.answer(
            f"❌ Отчёт пользователя {user_id} отклонён.\n"
            f"⚠️ Уведомление участнику не доставлено — скажи ему написать /start."
        )
        return

    await message.answer(f"❌ Отчёт пользователя {user_id} отклонён")
