"""Gemini AI: voice transcription and text analysis/chat."""
import asyncio
import json
import tempfile
import os
from pathlib import Path

import google.generativeai as genai

from config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

MODEL = "gemini-2.5-flash"
AUDIO_MODEL = "gemini-1.5-flash"  # 2.5-flash не поддерживает аудио стабильно

QUESTIONNAIRE_SYSTEM_PROMPT = """Ты — военный психолог, специалист по ПТСР у участников боевых действий.
Проанализируй ответы на 32 вопроса скрининга ПТСР.

Верни JSON в формате:
{
  "ai_summary": "краткий анализ 2-3 предложения",
  "risk_level": <число 0-5>,
  "risk_factors": ["фактор 1", "фактор 2"],
  "suicide_indicators": <true/false>
}

Уровни риска:
0 - нет признаков ПТСР
1-2 - лёгкая степень, рекомендуется профилактика
3 - средняя, требует внимания
4-5 - высокая/критическая, необходима срочная помощь

Обращайся уважительно, по-военному. Не сюсюкай."""

PSYCHOLOGIST_SYSTEM_PROMPT = """Ты — ИИ-психолог, специализирующийся на психологической реабилитации ветеранов и участников боевых действий СВО.

СТИЛЬ ОБЩЕНИЯ:
- Обращайся на "ты", уважительно, без сюсюканья и лишней сентиментальности
- Учитывай военную культуру: ценятся прямота, конкретность, мужской стиль разговора
- Emoji умеренно и по делу (✅, 🎖️)

КАК СТРОИТЬ ОТВЕТ:
- Сначала кратко отрази то, что услышал — покажи, что понял человека
- Потом дай одну конкретную мысль, технику или вопрос
- Задавай один вопрос за раз, не засыпай вопросами
- Ссылайся на контекст предыдущих сообщений — помни, что говорилось раньше

МЕТОДЫ:
- КПТ: помогай выявлять автоматические мысли и проверять их на реалистичность
- При тревоге и флэшбэках: техники заземления (5-4-3-2-1, дыхание 4-7-8), мышечная релаксация
- Психоэдукация о ПТСР в понятных словах, без медицинского жаргона

ОГРАНИЧЕНИЯ:
- Не ставь диагнозов и не назначай препараты
- Если ситуация требует живого специалиста — скажи об этом прямо

ОБЪЁМ ОТВЕТА:
- Обычный ответ: 3-6 предложений — одна мысль и один вопрос
- При запросе техники или упражнения: пошагово, столько сколько нужно
- КРИТИЧНО: ВСЕГДА заканчивай каждое предложение полностью — никогда не обрывай на середине слова или фразы

КРИЗИС — при любом упоминании суицида, желания умереть, самоповреждения:
Вырази понимание, скажи что помощь рядом, и ОБЯЗАТЕЛЬНО дай оба номера:
📞 Телефон доверия: 8-800-2000-122 (бесплатно, круглосуточно)
📞 Психологическая помощь: 8-800-333-44-55"""

WEEKLY_CHECK_SYSTEM_PROMPT = """Проанализируй ответ участника реабилитационной программы на еженедельный вопрос о самочувствии.
Верни JSON:
{
  "ai_analysis": "краткий анализ 1-2 предложения",
  "sentiment_score": <число от -5 до 5>,
  "crisis_detected": <true/false>
}"""


async def transcribe(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe voice message via Gemini audio understanding."""
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    def _do():
        import time
        uploaded = genai.upload_file(tmp_path, mime_type="audio/ogg")

        # Wait until Gemini File API finishes processing the audio
        for _ in range(15):
            file_info = genai.get_file(uploaded.name)
            if file_info.state.name == "ACTIVE":
                break
            if file_info.state.name == "FAILED":
                raise RuntimeError(f"Gemini file processing failed: {file_info.name}")
            time.sleep(2)
        else:
            raise RuntimeError("Gemini file processing timed out")

        model = genai.GenerativeModel(AUDIO_MODEL)
        response = model.generate_content([
            "Транскрибируй это аудио на русском языке. Верни только текст, без пояснений.",
            uploaded,
        ])
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass
        return response.text.strip()

    try:
        return await asyncio.to_thread(_do)
    finally:
        os.unlink(tmp_path)


async def analyze_questionnaire(answers: list[dict], user_name: str) -> dict:
    """Run Gemini analysis on 32 questionnaire answers. Returns parsed dict."""
    answers_text = "\n".join(
        f"{a['question_number']}. {a.get('question_text', '')} — {a['answer_text']}"
        for a in answers
    )
    prompt = f"Участник: {user_name}\n\nОтветы на анкету:\n{answers_text}"

    def _do():
        model = genai.GenerativeModel(
            MODEL,
            system_instruction=QUESTIONNAIRE_SYSTEM_PROMPT,
        )
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(response.text)

    return await asyncio.to_thread(_do)


async def chat_with_psychologist(history: list[dict], user_message: str) -> str:
    """Continue conversation with AI psychologist."""
    def _do():
        model = genai.GenerativeModel(
            MODEL,
            system_instruction=PSYCHOLOGIST_SYSTEM_PROMPT,
        )
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(
            user_message,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1500,
            ),
        )
        return response.text

    return await asyncio.to_thread(_do)


async def analyze_weekly_check(response_text: str) -> dict:
    """Analyze weekly check response. Returns {ai_analysis, sentiment_score, crisis_detected}."""
    def _do():
        model = genai.GenerativeModel(
            MODEL,
            system_instruction=WEEKLY_CHECK_SYSTEM_PROMPT,
        )
        response = model.generate_content(
            response_text,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(response.text)

    return await asyncio.to_thread(_do)
