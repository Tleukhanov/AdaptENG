"""GET /api/health — живость сервиса для Heroku-проверок."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Живость сервиса + признак доступности серверного распознавания речи.

    Фронт спрашивает это один раз: если STT на сервере не настроен, микрофон
    сразу работает через браузер (без лишней загрузки аудио).
    """
    stt = getattr(request.app.state, "stt", None)
    return HealthResponse(stt_available=stt is not None)