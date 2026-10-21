"""Все ключи i18n, которые использует фронт, должны существовать в messages/.

next-intl падает в рантайме с MISSING_MESSAGE, если ключа нет: страница
умирает целиком (проверено в проде — экран урока падал на lesson.generating.*).
Такие ошибки не видны в TypeScript, поэтому ловим их отдельным тестом.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_all_frontend_i18n_keys_exist():
    """tools/check_i18n.py возвращает 0, если все ключи на месте."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_i18n.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
