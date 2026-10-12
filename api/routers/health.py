"""GET /api/health — живость сервиса для Heroku-проверок."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()