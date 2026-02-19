"""All Supabase interactions. RPC names match existing SQL functions exactly."""
import asyncio

from supabase import create_client, Client

from config import settings

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


async def _run(fn):
    """Run sync supabase call in thread pool."""
    return await asyncio.to_thread(fn)


# ── User State ──────────────────────────────────────────────────────────────

async def get_user_state(telegram_id: int) -> dict | None:
    """Returns merged ptsd_users + ptsd_user_state row, or None if new user."""
    client = get_client()

    def _fetch():
        result = (
            client.table("ptsd_user_state")
            .select("*, ptsd_users!inner(*)")
            .eq("user_id", telegram_id)
            .limit(1)
            .execute()
        )
        if not result or not result.data:
            return None
        return result.data[0]

    return await _run(_fetch)


async def create_user(telegram_id: int, username: str | None, first_name: str) -> dict:
    client = get_client()

    def _create():
        client.table("ptsd_users").insert({
            "user_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "status": "active",
            "total_rewards": 0,
        }).execute()
        client.table("ptsd_user_state").insert({
            "user_id": telegram_id,
            "current_module": "idle",
            "current_phase": None,
            "risk_level": 0,
            "suicide_flag": False,
        }).execute()
        return client.table("ptsd_user_state").select("*").eq("user_id", telegram_id).single().execute().data

    return await _run(_create)


async def update_user_state(user_id: int, **fields) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_user_state").update(fields).eq("user_id", user_id).execute())


# ── Lessons ──────────────────────────────────────────────────────────────────

async def get_lesson(lesson_id: str) -> dict | None:
    client = get_client()
    result = await _run(
        lambda: client.table("ptsd_lessons").select("*").eq("id", lesson_id).limit(1).execute()
    )
    if not result or not result.data:
        return None
    return result.data[0]


async def get_lesson_progress(user_id: int) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table("ptsd_lesson_progress").select("*").eq("user_id", user_id).execute()
    )
    return result.data


async def upsert_lesson_progress(user_id: int, lesson_id: str, **fields) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_lesson_progress").upsert({
        "user_id": user_id,
        "lesson_id": lesson_id,
        **fields,
    }).execute())


# ── Reports ──────────────────────────────────────────────────────────────────

async def save_lesson_report(user_id: int, lesson_id: str, report_text: str,
                              voice_transcript: str | None, rating: int | None) -> dict:
    client = get_client()
    result = await _run(lambda: client.table("ptsd_lesson_reports").insert({
        "user_id": user_id,
        "lesson_id": lesson_id,
        "report_text": report_text,
        "voice_transcript": voice_transcript,
        "rating": rating,
        "status": "pending",
    }).execute())
    return result.data[0]


async def get_pending_reports() -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_pending_reports").execute())
    return result.data


async def rpc_approve_report(user_id: int, lesson_id: str, manager_id: int, comment: str) -> None:
    client = get_client()
    await _run(lambda: client.rpc("approve_lesson_report", {
        "p_user_id": user_id, "p_lesson_id": lesson_id,
        "p_manager_id": manager_id, "p_comment": comment,
    }).execute())


async def rpc_reject_report(user_id: int, lesson_id: str, manager_id: int, reason: str) -> None:
    client = get_client()
    await _run(lambda: client.rpc("reject_lesson_report", {
        "p_user_id": user_id, "p_lesson_id": lesson_id,
        "p_manager_id": manager_id, "p_reason": reason,
    }).execute())


async def rpc_is_manager(telegram_user_id: int) -> bool:
    client = get_client()
    result = await _run(lambda: client.rpc("is_manager", {"p_telegram_user_id": telegram_user_id}).execute())
    return bool(result.data)


async def rpc_increment_rewards(user_id: int, amount: int) -> None:
    client = get_client()
    await _run(lambda: client.rpc("increment_total_rewards", {
        "p_user_id": user_id, "p_amount": amount,
    }).execute())


# ── Questionnaire ─────────────────────────────────────────────────────────────

async def get_questions() -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table("ptsd_questions").select("*").order("question_number").execute()
    )
    return result.data


async def save_questionnaire_answer(user_id: int, question_number: int, answer_text: str) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_questionnaire_answers").upsert({
        "user_id": user_id,
        "question_number": question_number,
        "answer_text": answer_text,
    }).execute())


async def get_questionnaire_answers(user_id: int) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table("ptsd_questionnaire_answers")
        .select("*").eq("user_id", user_id).order("question_number").execute()
    )
    return result.data


async def save_questionnaire_analysis(user_id: int, ai_summary: str, risk_level: int,
                                       risk_factors: list, suicide_indicators: bool) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_questionnaire_analysis").upsert({
        "user_id": user_id,
        "ai_summary": ai_summary,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "suicide_indicators": suicide_indicators,
    }).execute())


# ── AI Chat Logs ──────────────────────────────────────────────────────────────

async def get_chat_history(user_id: int, limit: int = 20) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table("ptsd_chat_logs")
        .select("role, content")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(result.data))


async def save_chat_message(user_id: int, role: str, content: str,
                             crisis_detected: bool = False, crisis_markers: list | None = None) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_chat_logs").insert({
        "user_id": user_id, "role": role, "content": content,
        "crisis_detected": crisis_detected, "crisis_markers": crisis_markers or [],
    }).execute())


# ── Weekly Checks ─────────────────────────────────────────────────────────────

async def save_weekly_check(user_id: int, response: str, ai_analysis: str,
                             sentiment_score: int, crisis_detected: bool) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_weekly_checks").insert({
        "user_id": user_id, "user_response": response,
        "ai_analysis": ai_analysis, "sentiment_score": sentiment_score,
        "crisis_detected": crisis_detected,
    }).execute())


# ── Reminder Settings ─────────────────────────────────────────────────────────

async def upsert_reminder_settings(user_id: int, **fields) -> None:
    client = get_client()
    await _run(lambda: client.table("ptsd_reminder_settings").upsert({
        "user_id": user_id, **fields,
    }).execute())


# ── Scheduled Task Queries (via existing RPC) ─────────────────────────────────

async def rpc_get_users_for_daily_reminder(hour: int) -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_users_for_daily_reminder", {"p_hour": hour}).execute())
    return result.data


async def rpc_get_users_for_morning_check() -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_users_for_morning_check").execute())
    return result.data


async def rpc_get_users_for_weekly_check() -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_users_for_weekly_check").execute())
    return result.data


async def rpc_get_users_for_escalation(level: int) -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_users_for_escalation", {"p_level": level}).execute())
    return result.data


async def rpc_get_inactive_users(hours: int = 24) -> list[dict]:
    client = get_client()
    result = await _run(lambda: client.rpc("get_inactive_users", {"p_hours": hours}).execute())
    return result.data


async def rpc_check_morning_crisis(user_id: int) -> bool:
    client = get_client()
    result = await _run(lambda: client.rpc("check_morning_crisis", {"p_user_id": user_id}).execute())
    return bool(result.data)


async def rpc_update_activity_on_lesson(user_id: int, completed: bool) -> None:
    client = get_client()
    await _run(lambda: client.rpc("update_user_activity_on_lesson", {
        "p_user_id": user_id, "p_completed": completed,
    }).execute())
