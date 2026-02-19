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
    is_mgr = await db.rpc_is_manager(telegram_id)
    if not is_mgr:
        return  # silently ignore non-managers

    if callback_data.startswith("approve_report_"):
        _, _, user_id_str, lesson_id = callback_data.split("_", 3)
        await _approve(message, int(user_id_str), lesson_id, telegram_id)

    elif callback_data.startswith("reject_report_"):
        _, _, user_id_str, lesson_id = callback_data.split("_", 3)
        await _ask_reject_reason(message, int(user_id_str), lesson_id, telegram_id)


async def handle_rejection_reason(message: Message, telegram_id: int, text: str, **kwargs):
    """Called when manager types rejection reason after clicking Отклонить."""
    pending = _pending_rejections.pop(telegram_id, None)
    if not pending:
        return
    user_id, lesson_id = pending
    await _reject(message, user_id, lesson_id, telegram_id, text.strip())


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


async def _ask_reject_reason(message: Message, user_id: int, lesson_id: str, manager_id: int):
    """Store pending rejection and ask manager to type reason."""
    _pending_rejections[manager_id] = (user_id, lesson_id)
    await message.answer(
        f"✍️ Напиши причину отклонения отчёта пользователя {user_id} следующим сообщением."
    )


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
