"""Reminder settings — snooze, change time, pause week."""
from datetime import datetime, timedelta

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from ptsd_bot.db import client as db


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏰ Утро (9:00)", callback_data="change_to_morning"),
            InlineKeyboardButton(text="🌆 Вечер (20:00)", callback_data="change_to_evening"),
        ],
        [InlineKeyboardButton(text="😴 Отложить на 3 часа", callback_data="snooze_3h")],
        [InlineKeyboardButton(text="⏸ Пауза на неделю", callback_data="pause_week")],
    ])


async def handle(message: Message, callback_data: str, telegram_id: int, **kwargs):
    match callback_data:
        case "show_reminder_settings":
            await message.answer(
                "⚙️ *Настройки напоминаний*\n\nВыбери опцию:",
                reply_markup=_settings_keyboard(),
            )

        case "change_to_morning":
            await db.upsert_reminder_settings(telegram_id,
                reminder_time_preference="morning", reminder_hour=9)
            await message.answer("✅ Напоминания переставлены на *9:00*.")

        case "change_to_evening":
            await db.upsert_reminder_settings(telegram_id,
                reminder_time_preference="evening", reminder_hour=20)
            await message.answer("✅ Напоминания переставлены на *20:00*.")

        case "snooze_3h":
            snooze_until = datetime.now() + timedelta(hours=3)
            await db.upsert_reminder_settings(telegram_id,
                pause_until=snooze_until.isoformat())
            await message.answer("😴 Напоминания отложены на 3 часа.")

        case "pause_week":
            pause_until = datetime.now() + timedelta(days=7)
            await db.upsert_reminder_settings(telegram_id,
                pause_until=pause_until.isoformat())
            await message.answer(
                "⏸ Напоминания приостановлены на неделю.\n\n"
                "Программа будет ждать тебя. 🎖️"
            )
