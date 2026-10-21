"""POST /api/chat и POST /api/chat/tts — практика и озвучка (web-продукт).

Зеркалирует один практический ход бота (bot/flow.run_practice), но без импорта
из ``bot``: вся бизнес-логика берётся из ``core``/``storage``. Сетевые
провайдеры (LLM/TTS) инжектятся из app.state, собранного в lifespan.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.characters import character_localized, character_prompt, character_voice, get_character
from core.config import Settings
from core.profile import to_profile_snippet
from core.weak_areas import WeakAreaService
from storage.repo import Repository, UserProfile

from ..deps import get_current_tg_id, get_practice, get_tts, get_repository, get_settings_dep, resolve_locale
from ..loadguard import QueueFull
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import ChatRequest, ChatResponse, IssueOut, TTSRequest

router = APIRouter(prefix="/api", tags=["chat"])

CHAT_LLM_ERROR = "Не удалось получить ответ"
CHAT_QUOTA_ERROR = "Дневной лимит исчерпан"
CHAT_THROTTLE_ERROR = "Слишком часто пишешь — дай наставнику секунду"
QUEUE_FULL_ERROR = "Сейчас много запросов — очередь переполнена, попробуй через минуту"

logger = logging.getLogger(__name__)


def _issues_json(result) -> str:
    payload = [
        {
            "category": issue.category,
            "problem": issue.problem,
            "suggestion": issue.suggestion,
            "correction": issue.correction,
        }
        for issue in result.issues
    ]
    return json.dumps(payload, ensure_ascii=False)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    tg_id: int = Depends(get_current_tg_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
    practice=Depends(get_practice),
) -> ChatResponse:
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    if practice is None:
        raise HTTPException(status_code=503, detail="LLM не настроен")

    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded:
        raise HTTPException(status_code=429, detail=CHAT_QUOTA_ERROR)

    profile = await repo.get_profile(user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        await repo.save_profile(profile)

    throttle = getattr(request.app.state, "action_throttle", None)
    if throttle is not None and not throttle.allow(f"chat:{user.id}"):
        raise HTTPException(status_code=429, detail=CHAT_THROTTLE_ERROR)

    locale = resolve_locale(request)

    llm_guard = getattr(request.app.state, "llm_guard", None)
    try:
        snippet = to_profile_snippet(profile) or None
        char_prompt = character_prompt(profile.character)
        history = await repo.get_history(user.id, settings.max_context_messages)
        weak_svc = WeakAreaService(repo)
        weak_prompt = await weak_svc.get_top_for_prompt(user.id)

        if llm_guard is not None:
            try:
                async with llm_guard.slot():
                    result = await practice.analyze(
                        body.text,
                        history,
                        profile=snippet,
                        character_prompt=char_prompt,
                        weak_areas_prompt=weak_prompt,
                    )
            except QueueFull:
                logger.warning("Очередь LLM переполнена: user=%s", user.id)
                raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
        else:
            result = await practice.analyze(
                body.text,
                history,
                profile=snippet,
                character_prompt=char_prompt,
                weak_areas_prompt=weak_prompt,
            )

        await repo.add_user_message(
            user.id,
            body.text,
            is_correct=result.is_correct,
            issues_json=_issues_json(result),
            corrected_text=result.corrected_text,
        )
        await weak_svc.update_from_practice(user.id, result.issues, result.is_correct, result.corrected_text)
        await weak_svc.decay(user.id)
        await repo.add_assistant_message(user.id, result.spoken_reply)
    except QuotaExceeded:
        raise
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=CHAT_LLM_ERROR)

    try:
        await consume_quota(repo, settings, user.id)
    except QuotaExceeded:
        pass

    character_view = character_localized(get_character(profile.character), locale)
    return ChatResponse(
        reply=result.spoken_reply,
        tone=result.tone,
        corrected_text=result.corrected_text,
        is_correct=result.is_correct,
        next_question=result.next_question,
        issues=[IssueOut(**issue.__dict__) for issue in result.issues],
        character=character_view,
    )


@router.post("/chat/tts")
async def chat_tts(
    request: Request,
    body: TTSRequest,
    tg_id: int = Depends(get_current_tg_id),
    tts=Depends(get_tts),
) -> Response:
    if tts is None:
        raise HTTPException(status_code=503, detail="TTS не настроен")

    voice = character_voice(body.character_id)
    try:
        audio = await tts.synthesize(body.text, voice)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Не удалось синтезировать речь")
    return Response(content=audio, media_type="audio/mpeg")