"""Gemini AI: voice transcription and text analysis/chat (google-genai SDK)."""
import asyncio
import json

from google import genai
from google.genai import types

from config import settings

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


MODEL = "gemini-2.0-flash"
AUDIO_MODEL = "gemini-2.0-flash"

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

PSYCHOLOGIST_SYSTEM_PROMPT_TEMPLATE = """Ты — военный психолог с опытом работы с ветеранами и участниками боевых действий. Твоя роль — оказывать психологическую поддержку бойцам, вернувшимся из зоны СВО.

ИМЯ ПОЛЬЗОВАТЕЛЯ: {first_name}

ВАЖНЫЕ ПРАВИЛА:
1. Обращайся к пользователю на "ты" и по имени
2. Говори уважительно и прямо, без "сюсюканья" и чрезмерной мягкости
3. Используй методы КПТ (когнитивно-поведенческая терапия) и ДБТ (диалектическая поведенческая терапия)
4. Будь эмпатичен, но не жалей — поддерживай
5. Отвечай кратко и по существу (2-4 абзаца максимум)
6. Учитывай военную специфику и культуру
7. Помни контекст предыдущих сообщений

КРИЗИСНЫЕ СИТУАЦИИ:
Если пользователь упоминает суицид, самоповреждение, желание умереть или "закончить всё" — ОБЯЗАТЕЛЬНО:
1. Вырази поддержку и понимание
2. Скажи, что эти чувства временны и помощь доступна
3. ВСЕГДА добавь контакты помощи:
   📞 Телефон доверия: 8-800-2000-122 (бесплатно, круглосуточно)
   📞 Психологическая помощь: 8-800-333-44-55

НИКОГДА не игнорируй кризисные сигналы!"""

WEEKLY_CHECK_SYSTEM_PROMPT = """Проанализируй ответ участника реабилитационной программы на еженедельный вопрос о самочувствии.
Верни JSON:
{
  "ai_analysis": "краткий анализ 1-2 предложения",
  "sentiment_score": <число от -5 до 5>,
  "crisis_detected": <true/false>
}"""


async def transcribe(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe voice message via Gemini inline audio."""
    def _do():
        client = get_client()
        response = client.models.generate_content(
            model=AUDIO_MODEL,
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type="audio/ogg"),
                "Транскрибируй это аудио на русском языке. Верни только текст, без пояснений.",
            ],
        )
        return response.text.strip()

    return await asyncio.to_thread(_do)


async def analyze_questionnaire(answers: list[dict], user_name: str) -> dict:
    """Run Gemini analysis on 32 questionnaire answers. Returns parsed dict."""
    answers_text = "\n".join(
        f"{a['question_number']}. {a.get('question_text', '')} — {a['answer_text']}"
        for a in answers
    )
    prompt = f"Участник: {user_name}\n\nОтветы на анкету:\n{answers_text}"

    def _do():
        client = get_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=QUESTIONNAIRE_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(response.text)

    return await asyncio.to_thread(_do)


async def chat_with_psychologist(history: list[dict], user_message: str,
                                  first_name: str = "боец") -> str:
    """Continue conversation with AI psychologist."""
    system_prompt = PSYCHOLOGIST_SYSTEM_PROMPT_TEMPLATE.format(first_name=first_name)

    def _do():
        client = get_client()
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])],
            ))

        chat = client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=1500,
            ),
            history=gemini_history,
        )
        response = chat.send_message(user_message)
        return response.text

    return await asyncio.to_thread(_do)


async def analyze_weekly_check(response_text: str) -> dict:
    """Analyze weekly check response. Returns {ai_analysis, sentiment_score, crisis_detected}."""
    def _do():
        client = get_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=response_text,
            config=types.GenerateContentConfig(
                system_instruction=WEEKLY_CHECK_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(response.text)

    return await asyncio.to_thread(_do)
