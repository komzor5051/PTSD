"""Onboarding flow — mirrors ONBOARDING_FLOW.json."""
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from db import client as db


def _welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, начать", callback_data="onboarding_accept")],
        [InlineKeyboardButton(text="ℹ️ Подробнее о программе", callback_data="onboarding_info")],
    ])


def _consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен, продолжить", callback_data="consent_yes")],
        [InlineKeyboardButton(text="❌ Не сейчас", callback_data="consent_no")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="restart_onboarding")],
    ])


def _reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Утром (9:00)", callback_data="reminder_morning")],
        [InlineKeyboardButton(text="🌆 Вечером (20:00)", callback_data="reminder_evening")],
    ])


async def handle_new_user(message: Message, telegram_id: int, **kwargs):
    """Create new user record and send welcome message."""
    user = message.chat
    await db.create_user(telegram_id, getattr(user, "username", None), user.first_name or "боец")

    await message.answer(
        f"🎖️ *Приветствую, {user.first_name or 'боец'}!*\n\n"
        "Я — система психологической реабилитации для участников боевых действий.\n\n"
        "Программа включает:\n"
        "• 10 занятий по работе с ПТСР\n"
        "• Поддержку ИИ-психолога\n"
        "• Вознаграждение за прохождение\n\n"
        "Готов начать?",
        reply_markup=_welcome_keyboard(),
    )


async def handle_return_user(message: Message, telegram_id: int, first_name: str, state: dict, **kwargs):
    """Welcome back existing user — mirrors 'Format Return Message' node in MASTER_ROUTER_v2."""
    state = state or {}
    module = state.get("current_module", "idle")
    phase = state.get("current_phase")

    # If user was in AI chat, reset to idle first (mirrors 'Reset State If AI Chat' node)
    if module == "ai_chat":
        await db.update_user_state(telegram_id, current_module="idle")
        module = "idle"

    # Determine context-aware status text and primary action button
    if phase == "awaiting_review":
        status = "Твой отчёт на проверке у куратора."
        action_btn = InlineKeyboardButton(text="🔄 Проверить статус", callback_data="check_review_status")
    elif phase == "awaiting_report":
        status = "Ожидается твой отчёт по уроку."
        action_btn = InlineKeyboardButton(text="📝 Отправить отчёт", callback_data="lesson_continue")
    elif module in ("idle", ""):
        status = "Рад снова тебя видеть."
        action_btn = InlineKeyboardButton(text="▶️ Начать программу", callback_data="onboarding_accept")
    elif module == "screening":
        status = "У тебя есть незавершённая анкета."
        action_btn = InlineKeyboardButton(text="▶️ Продолжить анкету", callback_data="questionnaire_continue")
    elif module == "complete":
        status = "Анкета пройдена. Можно начинать курс."
        action_btn = InlineKeyboardButton(text="▶️ Начать курс", callback_data="start_course")
    elif module == "crisis_hold":
        status = ("Рекомендуем обратиться к специалисту.\n\n"
                  "📞 8-800-333-44-55 (бесплатно)\n"
                  "📞 8-800-2000-122 (телефон доверия)")
        action_btn = InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")
    elif module == "course_complete":
        status = "Поздравляю! Ты прошёл весь курс."
        action_btn = InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")
    elif module == "weekly_check":
        status = "Ожидается твой ответ на еженедельную проверку. Напиши свободным текстом как прошла неделя."
        action_btn = InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")
    elif module.startswith("m"):
        lesson_num = module.replace("m", "").replace("_lesson", "")
        phase_names = {"theory": "теории", "practice": "практики", "exercise": "упражнения"}
        phase_text = phase_names.get(phase or "theory", "занятия")
        status = f"Урок {lesson_num}. Ты на этапе {phase_text}."
        action_btn = InlineKeyboardButton(text="▶️ Продолжить урок", callback_data="lesson_continue")
    else:
        status = "Рад снова тебя видеть."
        action_btn = InlineKeyboardButton(text="▶️ Начать программу", callback_data="onboarding_accept")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [action_btn],
        [InlineKeyboardButton(text="💬 Поговорить с психологом", callback_data="chat_psychologist")],
        [InlineKeyboardButton(text="⚙️ Настройки напоминаний", callback_data="show_reminder_settings")],
    ])

    await message.answer(
        f"🎖️ *С возвращением, {first_name}!*\n\n{status}\n\nЧто хочешь сделать?",
        reply_markup=keyboard,
    )


async def handle(message: Message, callback_data: str, telegram_id: int,
                 first_name: str, **kwargs):
    """Handle all onboarding callbacks."""
    match callback_data:
        case "onboarding_accept" | "restart_onboarding":
            await message.answer(
                "📋 *Согласие на участие в программе*\n\n"
                "Программа реабилитации включает психологические упражнения и анкетирование.\n"
                "Данные обрабатываются конфиденциально и используются только для оценки твоего состояния.\n\n"
                "Ты согласен участвовать?",
                reply_markup=_consent_keyboard(),
            )

        case "onboarding_info":
            await message.answer(
                "ℹ️ *О программе реабилитации*\n\n"
                "Программа разработана военными психологами и включает:\n\n"
                "🔹 Скрининг для оценки уровня стресса\n"
                "🔹 10 структурированных занятий\n"
                "🔹 Практические упражнения\n"
                "🔹 Поддержку ИИ-психолога 24/7\n"
                "🔹 Денежное вознаграждение за прохождение (до 2700₽)\n\n"
                "Программа занимает 10-20 минут в день.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Начать программу", callback_data="onboarding_accept")],
                ]),
            )

        case "consent_yes":
            await db.update_user_state(telegram_id, current_module="idle")
            await message.answer(
                "✅ *Отлично!*\n\n"
                "Выбери удобное время для ежедневных напоминаний о занятиях:",
                reply_markup=_reminder_keyboard(),
            )

        case "consent_no" | "pause_onboarding":
            await db.update_user_state(telegram_id, current_module="idle")
            await message.answer(
                "Понял. Если захочешь вернуться — просто напиши /start.\n\n"
                "Программа будет ждать тебя. 🎖️"
            )

        case "reminder_morning":
            await db.upsert_reminder_settings(telegram_id, reminder_time_preference="morning", reminder_hour=9)
            await db.update_user_state(telegram_id, current_module="screening", screening_question_index=0)
            await message.answer(
                "✅ Напоминания настроены на *9:00*.\n\n"
                "Теперь пройдём короткую анкету — это поможет оценить твоё текущее состояние "
                "и подобрать программу именно для тебя.\n\n"
                "32 вопроса, ответы: Да / Нет.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="▶️ Начать анкету", callback_data="start_questionnaire")],
                ]),
            )

        case "reminder_evening":
            await db.upsert_reminder_settings(telegram_id, reminder_time_preference="evening", reminder_hour=20)
            await db.update_user_state(telegram_id, current_module="screening", screening_question_index=0)
            await message.answer(
                "✅ Напоминания настроены на *20:00*.\n\n"
                "Теперь пройдём короткую анкету — это поможет оценить твоё текущее состояние.\n\n"
                "32 вопроса, ответы: Да / Нет.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="▶️ Начать анкету", callback_data="start_questionnaire")],
                ]),
            )
