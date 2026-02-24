"""Lesson flow — theory → practice → exercise → rating → awaiting_report."""
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db

logger = logging.getLogger(__name__)


def _phase_keyboard(phase: str) -> InlineKeyboardMarkup:
    buttons = {
        "theory": [[InlineKeyboardButton(text="▶️ К практике", callback_data="lesson_practice")]],
        "practice": [[InlineKeyboardButton(text="▶️ К упражнению", callback_data="lesson_exercise")]],
        "exercise": [[InlineKeyboardButton(text="✅ Урок завершён", callback_data="lesson_complete")]],
    }
    return InlineKeyboardMarkup(inline_keyboard=buttons.get(phase, []))


def _rating_keyboard() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"rating_{i}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"rating_{i}") for i in range(6, 11)]
    skip = [InlineKeyboardButton(text="Пропустить", callback_data="rating_skip")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, skip])


def _current_lesson_id(module: str) -> str:
    """Extract lesson_N id from current_module like 'm1_lesson'."""
    num = module.replace("m", "").replace("_lesson", "")
    return f"lesson_{num}"


def _next_module(current_module: str) -> str | None:
    """Return next module name or None if course complete."""
    try:
        num = int(current_module.replace("m", "").replace("_lesson", ""))
    except ValueError:
        return None
    if num >= 10:
        return None
    return f"m{num + 1}_lesson"


async def handle(message: Message, callback_data: str, state: dict,
                 telegram_id: int, first_name: str, **kwargs):
    module = state.get("current_module", "")
    phase = state.get("current_phase") or "theory"

    if module == "crisis_hold":
        await message.answer(
            "⚠️ Курс временно недоступен.\n\n"
            "Рекомендуем сначала поговорить с психологом или обратиться на горячую линию:\n"
            "📞 8-800-333-44-55 (бесплатно)\n"
            "📞 8-800-2000-122 (телефон доверия)"
        )
        return

    if callback_data == "start_course":
        module = "m1_lesson"
        phase = "theory"
        await db.update_user_state(telegram_id, current_module=module, current_phase=phase)

    # lesson_continue: use current module and phase from state as-is

    lesson_id = _current_lesson_id(module)
    lesson = await db.get_lesson(lesson_id)

    if not lesson:
        logger.error("Lesson %s not found in DB", lesson_id)
        await message.answer("⚠️ Урок не найден. Обратись к куратору.")
        return

    lesson_num = module.replace("m", "").replace("_lesson", "")

    if callback_data == "lesson_practice":
        phase = "practice"
        await db.update_user_state(telegram_id, current_phase="practice")

    elif callback_data == "lesson_exercise":
        phase = "exercise"
        await db.update_user_state(telegram_id, current_phase="exercise")

    elif callback_data == "lesson_complete":
        await db.update_user_state(telegram_id, current_phase="awaiting_rating")
        await message.answer(
            "📊 *Оцени своё состояние после упражнения*\n\n"
            "Как ты себя чувствуешь сейчас?\n"
            "_(1 — очень плохо, 10 — отлично)_",
            reply_markup=_rating_keyboard(),
        )
        return

    elif callback_data.startswith("rating_"):
        rating_val = callback_data.replace("rating_", "")
        rating = None if rating_val == "skip" else int(rating_val)

        await db.update_user_state(telegram_id, current_phase="awaiting_report")
        await db.upsert_lesson_progress(telegram_id, lesson_id, status="in_progress", rating=rating)

        reward = lesson.get("reward_rub", 200)
        await message.answer(
            "🎤 *Отправь отчёт о занятии*\n\n"
            "Расскажи голосом или текстом (30-60 секунд):\n"
            "• Как прошло упражнение?\n"
            "• Какие ощущения были?\n"
            "• Заметил ли изменения?\n\n"
            f"💰 *Вознаграждение за урок:* {reward}₽\n"
            "_(начисляется после проверки куратором)_"
        )
        return

    match phase:
        case "theory":
            await message.answer(
                f"📖 *Урок {lesson_num}: {lesson['title']}*\n\n"
                f"{lesson['theory_text']}",
                reply_markup=_phase_keyboard("theory"),
            )

        case "practice":
            await message.answer(
                f"🎯 *Практика — Урок {lesson_num}*\n\n"
                f"{lesson['practice_instructions']}",
                reply_markup=_phase_keyboard("practice"),
            )

        case "exercise":
            await message.answer(
                f"💪 *Упражнение — Урок {lesson_num}*\n\n"
                f"{lesson['exercise_instructions']}",
                reply_markup=_phase_keyboard("exercise"),
            )

        case "awaiting_rating":
            # User sent a text message instead of tapping a rating button — resend keyboard
            await message.answer(
                "📊 *Оцени своё состояние после упражнения*\n\n"
                "Как ты себя чувствуешь сейчас?\n"
                "_(1 — очень плохо, 10 — отлично)_",
                reply_markup=_rating_keyboard(),
            )

        case _:
            logger.warning("Unexpected phase '%s' in lesson handler for user %s, defaulting to theory", phase, telegram_id)
            await db.update_user_state(telegram_id, current_phase="theory")
            await message.answer(
                f"📖 *Урок {lesson_num}: {lesson['title']}*\n\n"
                f"{lesson['theory_text']}",
                reply_markup=_phase_keyboard("theory"),
            )
