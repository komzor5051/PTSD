"""Questionnaire flow — 32 yes/no questions + GPT-4 analysis."""
import asyncio
import logging

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db
from services import openai_service
from services.crisis import handle_crisis

logger = logging.getLogger(__name__)


def _answer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data="answer_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="answer_no"),
    ]])


async def handle(message: Message, callback_data: str, state: dict,
                 telegram_id: int, first_name: str, **kwargs):
    current_index = state.get("screening_question_index", 0)

    if callback_data == "start_questionnaire":
        await db.update_user_state(telegram_id, screening_question_index=0, current_module="screening")
        current_index = 0

    elif callback_data in {"answer_yes", "answer_no"}:
        # Save the answer for the current question (at current_index before increment)
        answer_text = "Да" if callback_data == "answer_yes" else "Нет"
        await db.save_questionnaire_answer(telegram_id, current_index, answer_text)
        current_index += 1
        await db.update_user_state(telegram_id, screening_question_index=current_index)

    questions = await db.get_questions()
    total = len(questions)

    if current_index >= total:
        await _run_analysis(message, telegram_id, first_name)
        return

    question = questions[current_index]
    progress = f"({current_index + 1}/{total})"

    await message.answer(
        f"📋 *Вопрос {progress}*\n\n{question['question_text']}",
        reply_markup=_answer_keyboard(),
    )


async def _run_analysis(message: Message, user_id: int, first_name: str):
    """Trigger GPT-4 analysis after all 32 answers collected."""
    await message.answer(
        "✅ *Анкета завершена!*\n\n"
        "Анализирую твои ответы... Это займёт около минуты. ⏳"
    )
    asyncio.create_task(_analyze_and_respond(message, user_id, first_name))


async def _analyze_and_respond(message: Message, user_id: int, first_name: str):
    """Background task: GPT-4 analysis → save → send result."""
    try:
        answers = await db.get_questionnaire_answers(user_id)

        result = await openai_service.analyze_questionnaire(answers, first_name)

        risk_level = result.get("risk_level", 0)
        ai_summary = result.get("ai_summary", "")
        risk_factors = result.get("risk_factors", [])
        suicide_indicators = result.get("suicide_indicators", False)

        await db.save_questionnaire_analysis(user_id, ai_summary, risk_level, risk_factors, suicide_indicators)

        if suicide_indicators or risk_level >= 4:
            await db.update_user_state(user_id,
                current_module="crisis_hold",
                risk_level=risk_level,
                suicide_flag=suicide_indicators,
            )
            await handle_crisis(message.bot, user_id, message.chat.id)
            return

        risk_text = _risk_level_text(risk_level)
        factors_text = "\n".join(f"• {f}" for f in risk_factors) if risk_factors else "—"

        await db.update_user_state(user_id,
            current_module="complete",
            risk_level=risk_level,
            suicide_flag=False,
        )

        await message.answer(
            f"📊 *Результаты анализа*\n\n"
            f"{ai_summary}\n\n"
            f"*Уровень стресса:* {risk_level}/5 — {risk_text}\n\n"
            f"*Выявленные факторы:*\n{factors_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="▶️ Начать курс реабилитации", callback_data="start_course"),
            ]]),
        )

    except Exception as e:
        logger.error("Questionnaire analysis failed for user %s: %s", user_id, e)
        await message.answer(
            "⚠️ Произошла ошибка при анализе. Попробуй позже или обратись к куратору."
        )


def _risk_level_text(level: int) -> str:
    texts = {
        0: "Признаков ПТСР не выявлено",
        1: "Лёгкая степень стресса",
        2: "Умеренный стресс",
        3: "Средняя степень — рекомендуется работа со специалистом",
        4: "Высокий уровень — требуется внимание",
        5: "Критический уровень",
    }
    return texts.get(level, "Неизвестно")
