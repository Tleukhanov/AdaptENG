"""Шим обратной совместимости: конфигурация переехала в core.config.

``from bot.config import Settings`` и ``from bot.config import get_settings``
продолжают работать во всех старых модулях бота, тестах и провайдерах.
"""

from core.config import LLM_PRESETS, Settings, get_settings

__all__ = ["LLM_PRESETS", "Settings", "get_settings"]