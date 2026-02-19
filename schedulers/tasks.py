"""Scheduled tasks — mirrors all 5 Scheduled Workflows from n8n.

Schedule (Novosibirsk time, UTC+7):
  daily_reminder     — 9:00 and 20:00 daily
  morning_check      — 10:00 daily
  weekly_check       — Sunday 19:00
  escalation         — every 30 minutes
  inactivity_push    — every 2 hours
"""
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import client as db

logger = logging.getLogger(__name__)


async def send_daily_reminders(bot: Bot, hour: int):
    """Mirror: DAILY_REMINDER_FLOW — 9:00 and 20:00."""
    users = await db.rpc_get_users_for_daily_reminder(hour)
    logger.info("Daily reminder [%d:00]: %d users", hour, len(users))

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                "🎖️ *Время занятия!*\n\n"
                "Твоя ежедневная программа реабилитации ждёт.\n"
                "Занятие займёт 10-20 минут.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="▶️ Начать занятие", callback_data="lesson_continue"),
                ]]),
            )
        except Exception as e:
            logger.warning("Failed to send reminder to %s: %s", user["user_id"], e)


async def send_morning_check(bot: Bot):
    """Mirror: MORNING_CHECK_FLOW — 10:00 daily mood survey."""
    users = await db.rpc_get_users_for_morning_check()
    logger.info("Morning check: %d users", len(users))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="😫", callback_data="morning_mood_1"),
        InlineKeyboardButton(text="😕", callback_data="morning_mood_2"),
        InlineKeyboardButton(text="😐", callback_data="morning_mood_3"),
        InlineKeyboardButton(text="🙂", callback_data="morning_mood_4"),
        InlineKeyboardButton(text="😊", callback_data="morning_mood_5"),
    ]])

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                "☀️ *Доброе утро!*\n\nКак ты себя чувствуешь сегодня?",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("Failed to send morning check to %s: %s", user["user_id"], e)


async def send_weekly_check(bot: Bot):
    """Mirror: WEEKLY_CHECK_FLOW — Sunday 19:00."""
    users = await db.rpc_get_users_for_weekly_check()
    logger.info("Weekly check: %d users", len(users))

    for user in users:
        try:
            await db.update_user_state(
                user["user_id"],
                current_module_before_weekly=user.get("current_module"),
                current_module="weekly_check",
            )
            await bot.send_message(
                user["user_id"],
                "📊 *Еженедельная проверка*\n\n"
                "Расскажи как прошла эта неделя?\n"
                "Что давалось легче? Что сложнее? Есть ли изменения в самочувствии?\n\n"
                "_(Напиши свободным текстом — 2-5 предложений)_",
            )
        except Exception as e:
            logger.warning("Failed to send weekly check to %s: %s", user["user_id"], e)


async def run_escalation(bot: Bot):
    """Mirror: ESCALATION_FLOW — every 30 min, 3 escalation levels."""
    for level in [1, 2, 3]:
        users = await db.rpc_get_users_for_escalation(level)
        for user in users:
            try:
                msg = _escalation_message(level, user.get("first_name", "боец"))
                await bot.send_message(
                    user["user_id"],
                    msg,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="▶️ Продолжить", callback_data="lesson_continue"),
                    ]]),
                )
            except Exception as e:
                logger.warning("Escalation L%d failed for %s: %s", level, user["user_id"], e)


def _escalation_message(level: int, name: str) -> str:
    messages = {
        1: f"⏰ *{name}*, напоминаю о занятии.\nПрограмма реабилитации ждёт тебя.",
        2: (f"🎖️ *{name}*, уже два дня без занятий.\n\n"
            "Регулярность — ключ к результату. Даже 10 минут сегодня важны."),
        3: (f"🤝 *{name}*, с момента последнего занятия прошло 5 дней.\n\n"
            "Может пересмотрим расписание? Выбери удобное время."),
    }
    return messages.get(level, "")


async def send_inactivity_push(bot: Bot):
    """Mirror: INACTIVITY_PUSH_FLOW — every 2h, targets 24h+ inactive users."""
    users = await db.rpc_get_inactive_users(hours=24)
    logger.info("Inactivity push: %d users", len(users))

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                "👋 Давно не виделись!\n\n"
                "Программа реабилитации ждёт тебя. Готов продолжить?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="▶️ Продолжить", callback_data="lesson_continue"),
                ]]),
            )
        except Exception as e:
            logger.warning("Inactivity push failed for %s: %s", user["user_id"], e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Create and configure AsyncIOScheduler with all 5 jobs."""
    scheduler = AsyncIOScheduler(timezone="Asia/Novosibirsk")

    # Daily reminders — 9:00 and 20:00
    scheduler.add_job(send_daily_reminders, "cron", hour=9,
                      kwargs={"bot": bot, "hour": 9}, id="reminder_morning")
    scheduler.add_job(send_daily_reminders, "cron", hour=20,
                      kwargs={"bot": bot, "hour": 20}, id="reminder_evening")

    # Morning mood check — 10:00
    scheduler.add_job(send_morning_check, "cron", hour=10,
                      kwargs={"bot": bot}, id="morning_check")

    # Weekly check — Sunday 19:00
    scheduler.add_job(send_weekly_check, "cron", day_of_week="sun", hour=19,
                      kwargs={"bot": bot}, id="weekly_check")

    # Escalation — every 30 minutes
    scheduler.add_job(run_escalation, "interval", minutes=30,
                      kwargs={"bot": bot}, id="escalation")

    # Inactivity push — every 2 hours
    scheduler.add_job(send_inactivity_push, "interval", hours=2,
                      kwargs={"bot": bot}, id="inactivity_push")

    return scheduler
