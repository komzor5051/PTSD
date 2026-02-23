"""Weekly check + morning mood response handlers."""
import asyncio
import logging
from datetime import date

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db
from services import openai_service
from services.crisis import handle_crisis

logger = logging.getLogger(__name__)


async def handle(message: Message, state: dict, telegram_id: int, text: str, **kwargs):
    """Handle user's text response to weekly check question."""
    if not text:
        await message.answer("Напиши как ты себя чувствуешь на этой неделе.")
        return

    await message.answer("⏳ Записываю и анализирую...")

    try:
        result = await openai_service.analyze_weekly_check(text)
    except Exception as e:
        logger.error("Weekly check analysis failed: %s", e)
        result = {"ai_analysis": "", "sentiment_score": 0, "crisis_detected": False}

    sentiment = result.get("sentiment_score", 0)
    crisis = result.get("crisis_detected", False)
    analysis = result.get("ai_analysis", "")

    await db.save_weekly_check(telegram_id, text, analysis, sentiment, crisis)

    prev_module = state.get("current_module_before_weekly") or "idle"
    await db.update_user_state(telegram_id, current_module=prev_module)

    if crisis:
        await handle_crisis(message.bot, telegram_id, message.chat.id)
        return

    await message.answer(
        "✅ Спасибо за честный ответ.\n\n"
        f"{analysis}\n\n"
        "Продолжай программу — это важно для твоего восстановления. 🎖️",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="▶️ Продолжить занятия", callback_data="lesson_continue"),
        ]]),
    )


async def handle_morning_mood(message: Message, callback_data: str, telegram_id: int, **kwargs):
    """Handle morning mood selection (morning_mood_1 .. morning_mood_5)."""
    mood_score = int(callback_data.replace("morning_mood_", ""))

    from db.client import get_client
    client = get_client()

    await asyncio.to_thread(lambda: client.table("ptsd_morning_checks").upsert(
        {"user_id": telegram_id, "mood_score": mood_score, "check_date": date.today().isoformat()},
        on_conflict="user_id,check_date",
    ).execute())

    crisis = await db.rpc_check_morning_crisis(telegram_id)

    if crisis:  # 3 consecutive days with mood=1 → real crisis pattern
        await handle_crisis(message.bot, telegram_id, message.chat.id)
        return

    if mood_score <= 2:
        # Bad day, but not a crisis pattern — supportive message without crisis_hold
        await message.answer(
            "Вижу, что сегодня непросто. Это нормально — бывают тяжёлые дни.\n\n"
            "Если хочешь поговорить — психолог на связи.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")],
                [InlineKeyboardButton(text="▶️ Продолжить занятие", callback_data="lesson_continue")],
            ]),
        )
        return

    mood_emojis = {3: "😐", 4: "🙂", 5: "😊"}
    emoji = mood_emojis.get(mood_score, "")

    await message.answer(
        f"✅ Записал — {emoji}\n\n"
        "Готов к занятию сегодня?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать занятие", callback_data="lesson_continue")],
            [InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")],
        ]),
    )
