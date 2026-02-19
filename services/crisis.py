"""Crisis keyword detection. Matches logic from AI_PSYCHOLOGIST_FLOW and WEEKLY_CHECK_ANALYSIS_FLOW."""
from aiogram import Bot

CRISIS_KEYWORDS = [
    'суицид', 'самоубийств', 'убить себя', 'покончить',
    'не хочу жить', 'смысла нет', 'закончить всё',
    'уйти из жизни', 'хочу умереть', 'лучше бы я умер',
]

CRISIS_MESSAGE = (
    "🚨 *Боец, я вижу что тебе сейчас очень тяжело.*\n\n"
    "Пожалуйста, свяжись с кризисной службой прямо сейчас:\n\n"
    "📞 *8-800-333-44-55* (бесплатно, круглосуточно)\n"
    "📞 *8-800-2000-122* (телефон доверия)\n\n"
    "Ты не один. Помощь рядом."
)


def detect_crisis(text: str) -> list[str]:
    """Returns list of detected crisis keywords, empty if none."""
    text_lower = text.lower()
    return [kw for kw in CRISIS_KEYWORDS if kw in text_lower]


async def handle_crisis(bot: Bot, user_id: int, chat_id: int) -> None:
    """Send crisis message and set crisis_hold state."""
    from db import client as db

    await bot.send_message(chat_id, CRISIS_MESSAGE)
    await db.update_user_state(user_id,
        current_module="crisis_hold",
        suicide_flag=True,
    )
