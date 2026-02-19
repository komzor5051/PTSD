"""Manager review flow — approve/reject lesson reports."""
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from ptsd_bot.db import client as db
from ptsd_bot.handlers.lesson import _next_module

logger = logging.getLogger(__name__)

REJECT_REASONS = [
    ("Отчёт слишком короткий", "short"),
    ("Упражнение не выполнено", "not_done"),
    ("Нужно больше деталей", "details"),
]


async def handle(message: Message, callback_data: str, telegram_id: int, **kwargs):
    """Handle approve/reject callbacks from manager group."""
    is_mgr = await db.rpc_is_manager(telegram_id)
    if not is_mgr:
        return  # silently ignore non-managers

    if callback_data.startswith("approve_report_"):
        # approve_report_{user_id}_{lesson_id}
        _, _, user_id_str, lesson_id = callback_data.split("_", 3)
        await _approve(message, int(user_id_str), lesson_id, telegram_id)

    elif callback_data.startswith("reject_report_"):
        # reject_report_{user_id}_{lesson_id}
        _, _, user_id_str, lesson_id = callback_data.split("_", 3)
        await _show_reject_reasons(message, int(user_id_str), lesson_id)

    elif callback_data.startswith("reject_reason_"):
        # reject_reason_{reason_code}_{user_id}_{lesson_id}
        parts = callback_data.split("_", 4)
        # format: reject_reason_{code}_{user_id}_{lesson_id}
        reason_code = parts[2]
        user_id = int(parts[3])
        lesson_id = parts[4]
        reason_text = next((r[0] for r in REJECT_REASONS if r[1] == reason_code), "Не указана")
        await _reject(message, user_id, lesson_id, telegram_id, reason_text)


async def _approve(message: Message, user_id: int, lesson_id: str, manager_id: int):
    await db.rpc_approve_report(user_id, lesson_id, manager_id, "Принято")

    lesson = await db.get_lesson(lesson_id)
    reward = lesson.get("reward_rub", 200) if lesson else 200
    await db.rpc_increment_rewards(user_id, reward)

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
        next_num = next_mod.replace("m", "").replace("_lesson", "")
        await message.bot.send_message(
            user_id,
            f"✅ *Отчёт принят!*\n\n"
            f"Начислено: *{reward}₽*\n\n"
            f"Следующий урок {next_num} доступен! 🎖️",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"▶️ Урок {next_num}", callback_data="lesson_continue"),
            ]]),
        )
    else:
        await db.update_user_state(user_id, current_module="course_complete", current_phase=None)
        await message.bot.send_message(
            user_id,
            f"🎖️ *Поздравляю! Ты завершил всю программу реабилитации!*\n\n"
            f"Начислено: *{reward}₽*\n\n"
            "Это большой шаг. Ты справился. ✅"
        )

    await message.answer(f"✅ Отчёт пользователя {user_id} принят, начислено {reward}₽")


async def _show_reject_reasons(message: Message, user_id: int, lesson_id: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=reason,
            callback_data=f"reject_reason_{code}_{user_id}_{lesson_id}",
        )]
        for reason, code in REJECT_REASONS
    ])
    await message.answer("Выбери причину отклонения:", reply_markup=keyboard)


async def _reject(message: Message, user_id: int, lesson_id: str, manager_id: int, reason: str):
    await db.rpc_reject_report(user_id, lesson_id, manager_id, reason)
    await db.update_user_state(user_id, current_phase="awaiting_report", report_status="awaiting_report")

    await message.bot.send_message(
        user_id,
        f"❌ *Отчёт отклонён*\n\n"
        f"Причина: {reason}\n\n"
        "Пожалуйста, повтори упражнение и отправь новый отчёт."
    )
    await message.answer(f"❌ Отчёт пользователя {user_id} отклонён")
