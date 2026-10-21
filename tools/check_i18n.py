#!/usr/bin/env python3
"""Проверка i18n: все ключи t('...') должны существовать в messages/ru.json и en.json.

Ловит класс багов, который не видно в типах: next-intl падает в рантайме с
MISSING_MESSAGE, если ключа нет в messages (страница просто умирает).

Использование:
    python tools/check_i18n.py            # проверить и вывести список проблем
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MESSAGES_DIR = FRONTEND / "messages"

#: useTranslations('ns') — namespace страницы; useTranslations() — корневой.
NS_RE = re.compile(r"useTranslations\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)")
ROOT_TS_RE = re.compile(r"useTranslations\(\s*\)")
#: Вызов t('key') / t("key") — только статические строки.
CALL_RE = re.compile(r"\bt\(\s*['\"]([a-zA-Z0-9_.\-]+)['\"]")
#: Динамические ключи вида t(`step.${status}`) — проверяем префикс.
DYNAMIC_RE = re.compile(r"\bt\(\s*`([^`$]*)")


def load_messages(locale: str) -> dict:
    """Читает messages/<locale>.json и разворачивает плоские ключи в дерево."""
    flat = json.loads((MESSAGES_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    tree: dict = {}
    for key, value in flat.items():
        node = tree
        parts = key.split(".")
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value
    return tree


def has_key(tree: dict, key: str) -> bool:
    node = tree
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def has_prefix(tree: dict, key: str) -> bool:
    """Префикс существует (может быть namespace'ом с потомками)."""
    node = tree
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def check_file(path: Path, trees: dict[str, dict]) -> list[str]:
    source = path.read_text(encoding="utf-8")
    problems: list[str] = []

    # namespace страницы: последний useTranslations('ns') в файле.
    namespaces = NS_RE.findall(source)
    namespace = namespaces[0] if namespaces else ""

    for key in sorted(set(CALL_RE.findall(source))):
        full = f"{namespace}.{key}" if namespace else key
        for locale, tree in trees.items():
            if not has_key(tree, full):
                problems.append(
                    f"{path.relative_to(ROOT)}: ключ '{key}' "
                    f"(-> '{full}') отсутствует в messages/{locale}.json"
                )

    for prefix in sorted(set(DYNAMIC_RE.findall(source))):
        prefix = prefix.strip().rstrip(".")
        if not prefix:
            continue
        full = f"{namespace}.{prefix}" if namespace else prefix
        for locale, tree in trees.items():
            if not has_prefix(tree, full):
                problems.append(
                    f"{path.relative_to(ROOT)}: динамический ключ '{prefix}*"
                    f"(-> '{full}*') отсутствует в messages/{locale}.json"
                )

    return problems


def main() -> int:
    trees = {locale: load_messages(locale) for locale in ("ru", "en")}
    problems: list[str] = []
    checked = 0
    for path in sorted(FRONTEND.rglob("*.tsx")):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        checked += 1
        problems.extend(check_file(path, trees))

    if problems:
        print(f"Проблемы i18n ({len(problems)}):")
        for item in problems:
            print("  -", item)
        return 1
    print(f"i18n в порядке: проверено {checked} .tsx, все ключи есть в ru и en")
    return 0


if __name__ == "__main__":
    sys.exit(main())
