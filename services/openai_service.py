"""OpenAI API calls: Whisper transcription and GPT-4 analysis/chat."""
import json
import tempfile
import os
from pathlib import Path

from openai import AsyncOpenAI

from ptsd_bot.config import settings

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
    """Transcribe voice message via Whisper API."""
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            result = await _client.audio.transcriptions.create(
                model="whisper-1",
                file=(filename, f, "audio/ogg"),
                language="ru",
            )
        return result.text
    finally:
        os.unlink(tmp_path)


async def analyze_questionnaire(answers: list[dict], user_name: str) -> dict:
    """Run GPT-4 analysis on 32 questionnaire answers. Returns parsed dict."""
    answers_text = "\n".join(
        f"{a['question_number']}. {a.get('question_text', '')} — {a['answer_text']}"
        for a in answers
    )
    prompt = f"Участник: {user_name}\n\nОтветы на анкету:\n{answers_text}"

    response = await _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": QUESTIONNAIRE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(response.choices[0].message.content)


async def chat_with_psychologist(history: list[dict], user_message: str) -> str:
    """Continue conversation with AI psychologist. history = list of {role, content}."""
    messages = [{"role": "system", "content": PSYCHOLOGIST_SYSTEM_PROMPT}]
    messages.extend(history[-10:])  # last 10 messages for context
    messages.append({"role": "user", "content": user_message})

    response = await _client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7,
        max_tokens=400,
    )
    return response.choices[0].message.content


async def analyze_weekly_check(response_text: str) -> dict:
    """Analyze weekly check response. Returns {ai_analysis, sentiment_score, crisis_detected}."""
    result = await _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": WEEKLY_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": response_text},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(result.choices[0].message.content)
