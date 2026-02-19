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

PSYCHOLOGIST_SYSTEM_PROMPT = """Ты — ИИ-психолог, специализирующийся на работе с ветеранами и участниками боевых действий.
Ты помогаешь справляться с ПТСР через разговор.

Правила:
- Обращайся уважительно, без "сюсюканья"
- Учитывай военную специфику
- Не ставь диагнозов
- При признаках суицидального мышления — немедленно направляй к кризисным службам
- Emoji умеренно (🎖️, ✅)
- Ответы до 300 символов"""

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
        uploaded = genai.upload_file(tmp_path, mime_type="audio/ogg")
        model = genai.GenerativeModel(MODEL)
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
        for msg in history[-10:]:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(
            user_message,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=400,
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
