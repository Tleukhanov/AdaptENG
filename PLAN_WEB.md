# PLAN_WEB — AdaptENG: перевод продукта в Web

## Статус
- **Фаза C — выполнена**:
  - `api/routers/lessons.py` — порт урока из Mini App: `POST /api/lesson/new|answer|finish|voice` (квота до/после, контекст урока, план темы, заметка/XP через `ProgressService`, слова в SRS, голосовая реплика base64 → STT → оценка). Контракт ответов совпадает с мини-app. Провайдеры LLM/STT в `app.state` с мягким фолбэком.
  - `api/routers/progress.py` — `GET /api/progress` (агрегированный прогресс + тема следующего урока + число слов к повтору), `GET /api/review/due` + `POST /api/review/answer` (SRS-повторение).
  - `api/deps.py` — `get_stt`; `api/schemas.py` — модели урока/голоса/прогресса.
  - Фронт: `/lesson` (старт → презентация → карточки «Знаю/Повторю» → квиз с мгновенной подсветкой → диалог с выбором реплики + голосовой записью (MediaRecorder→base64) + TTS → итог с XP/след. темой), `/progress` (статистика, следующая тема, «Повторить слова»), демо-режим без API; ссылки с дашборда.
  - Адаптер серверной деки (`apiDeckToLocal`) + демо-дека `sampleDeck(locale)`.
  - Тесты: `tests/test_lessons.py` (+13) — полный сьют **529 passed, 5 skipped**.
- **Фаза B — выполнена**:
  - `PUT /api/me/character` — выбор/смена наставника (валидация id, создание профиля при отсутствии).
  - `POST /api/chat` — живой чат с персонажем: полностью повторяет практический ход бота (квота → профиль-сниппет → character-промпт → weak areas → PracticeService → запись сообщений и статистики → списание квоты), без импорта из `bot`.
  - `POST /api/chat/tts` — синтез речи персонажа (голос из `character_voice`), возвращает audio/mpeg.
  - `api/quota.py` — два шага квоты (проверка до, списание после; безопасен для unlimited/подписки).
  - LLM/TTS в `app.state` с мягким фолбэком: нет провайдера → `/api/chat*` отвечает 503, api не падает.
  - Фронт: страница `/chat` (шапка с аватаром-градиентом персонажа, баблы, индикатор печати, передача ввода, микрофон-заглушка, переключатель наставника), выбор наставника с карточек лендинга (PUT + редирект в `/chat`), демо-режим без API работает без логина.
  - Тесты: `tests/test_chat.py` (6) — полный сьют **516 passed, 5 skipped**.
- **Фаза A — выполнена (ветка `feat/adapteng-web`)**:
  - `core/config.py` — общие настройки (из `bot/config.py` сделан шим).
  - `core/tg_auth.py` — HMAC-проверка Telegram Login Widget.
  - `core/characters.py` — персонажи с RU/EN-полями (`name`/`tagline`/`description`/`backstory`), `avatar`, `palette`.
  - `api/` — FastAPI-сервис: `GET /api/health`, `POST /api/auth/tg` (JWT), `GET /api/me`, `GET /api/characters?lang=`.
  - `frontend/` — Next.js 15 + Tailwind v4 + next-intl: лендинг с героем и галереей персонажей, вход через Telegram, `/dashboard` (профиль).
  - Тесты: `tests/test_tg_auth.py`, `tests/test_api.py`.
- **Запуск локально**: 1) `uvicorn api.main:app --port 8000` (+ `.env` с `JWT_SECRET`, `API_INSECURE_AUTH=1` для отладки входа); 2) `cd frontend && npm install && npm run dev` с `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- **Деплой**: `Procfile` получил процесс `api` (для `adapteng-api`: `heroku ps:scale web=0 api=1`). Развёртывание трёх приложений Heroku — Фаза D.
- **Заметка по авторизации**: для MVP токен хранится в `localStorage` и шлётся в `Authorization`. В проде (отдельные домены web/api) желательно HttpOnly-cookie + проксирование `/api/*` через Next.js — отложено до Фазы D.

## 1. Идея и позиционирование
**AdaptENG** — персональный AI-репетитор английского с адаптивным обучением и AI-персонажами. Web-версия — самостоятельный продукт (свой домен, лендинг), бот остаётся доп. каналом.

- Брендинг: **AdaptENG** = adaptive + English («язык», «адаптация»).
- Домен-плейсхолдер: `adapteng.app` (или `.com`) — финализируем до деплоя.
- Язык интерфейса: **двуязычный RU/EN** с переключателем; по умолчанию берём `language_code` из Telegram.

## 2. Целевая архитектура
```
         ┌─ Telegram Bot (aiogram) + Mini App (web/) — остаётся, чат-канал
Общее ядро │
 core/ + storage/ ┤
         └─ FastAPI (api/) ←── Next.js + Tailwind (frontend/)
               │                                └─ лендинг, персонажи, уроки
           PostgreSQL (общая)
```
- Общий движок `core/` и `storage/` — уже не зависят от Telegram, переиспользуются и ботом, и api.
- Один пользователь и один прогресс на обоих каналах (связь по `tg_id`).

## 3. Структура репозитория (monorepo)
| Каталог | Что это |
|---|---|
| `frontend/` | Next.js (React) + Tailwind + i18n — новый web-продукт |
| `api/` | FastAPI-сервис, использует `core/` и `storage/` как библиотеку |
| `core/`, `storage/`, `bot/`, `web/` | существующее — не ломаем |
| `PLAN_WEB.md` | этот документ |

## 4. Деплой (Heroku, 3 приложения из одного репо)
1. `adapteng-api` — Python: `web: uvicorn api.main:app --port $PORT`; владеет `heroku-postgresql`.
2. `adapteng-web` — Node: Next.js standalone; `NEXT_PUBLIC_API_URL=https://adapteng-api.herokuapp.com`.
3. `adapteng-bot` — текущий бот; БД через `heroku addons:attach adapteng-api::DATABASE`.
4. Telegram Login Widget: включить у бота в BotFather + привязать домен.

## 5. Авторизация
- **Telegram Login Widget** (`POST /api/auth/tg`): серверная HMAC-проверка (логика уже есть в `bot/webapp.py`, выносим в общий модуль), сессия — HttpOnly cookie + JWT.
- Пользователь из бота подхватывается автоматически (тот же `tg_id`, сохраняется прогресс).
- Без паролей и email-инфры. Позже — опционально email.

## 6. Двуязычность (RU/EN)
- **Frontend:** Next.js App Router + `next-intl`; `frontend/messages/{ru,en}.json`; middleware-локаль `ru|en`; дефолт из `language_code` Telegram, ручной переключатель в шапке.
- **Персонажи:** данные локализуются в `core/characters.py` — поля `name_ru/name_en`, `tagline_ru/tagline_en`, `description_ru/en`, `backstory_ru/en` (fallback — EN). Арты общие.
- **API:** локаль через `Accept-Language` / `?lang=`; в ответах LLM объяснения остаются на русском для обучения (текущее поведение), копия интерфейса — на выбранной локали.

## 7. Персонажи — главная фича
- Расширить модель персонажа: `avatar` (AI-арт WebP), `color_palette`, `tagline`, `backstory`, локализованные поля.
- AI-арты: 6 персонажей в едином стиле → `frontend/public/characters/*.webp`.
- Показ: карточки на лендинге, экран выбора наставника, аватар в шапке и чат-бабблах, голосовое приветствие.

## 8. Фазы

### Фаза A — Каркас продукта («wow»-витрина)
- `api/`: FastAPI, общий `Settings`, CORS, `/api/health`, DI сервисов из core.
- Auth `POST /api/auth/tg`, `GET /api/me`, logout.
- Лендинг AdaptENG (RU/EN): hero + галерея персонажей + вход через Telegram.
- **Критерий:** вход по TG → лендинг с персонажами, прогресс юзера из бота на месте.

### Фаза B — Персонажи в действии
- `GET /api/characters`, `PUT /api/me/character`, TTS приветствие.
- Экран выбора наставника + постоянный аватар в UI.
- Живой чат с персонажем (текст): `POST /api/chat` (профиль+character-промпт из `core/practice.py`), стриминг SSE.
- **Критерий:** выбрал персонажа — он отвечает голосом и текстом, стиль соблюдается.

### Фаза C — Полный цикл обучения
- Порт эндпоинтов урока (`deck/new|answer|finish`) из `bot/mini_api.py` в FastAPI с cookie-auth.
- React-экраны: Урок (Презентация→Карточки→Квиз→Диалог→Финиш), Прогресс, Достижения, Лидерборд, «Повторить слова»; голос (MediaRecorder → `/api/voice/answer`, TTS карточек).
- **Критерий:** урок в браузере даёт те же XP/SRS/заметки, что из бота (общая БД).

### Фаза D — Интеграция и продукт
- Ссылки «открыть в web» из бота, единые напоминания.
- README-кейс «как показывать продукт», тесты API.
- Монетизация (Kaspi) остаётся в боте; card-оплата в web — потом.

## 9. Риски и решения
- **LLM медленный** → стриминг SSE + loading-экраны.
- **Monorepo на Heroku** → 3 app с python/node билдпаками (стандартно).
- **Разъезд данных бот/web** → одна БД, общий `core/`; персонажи и ролики определены в одном месте.
- **DESIGN-риск**: без дизайнера держим стиль через Tailwind-токены + арты в одном стиле.

## 10. Оценка
A: ~3–4 дня · B: ~4–5 дней · C: ~5–6 дней · D: ~2–3 дня → ~2 недели до показываемого продукта.

## 11. Открытые вопросы
1. Домен финально: `adapteng.app` / `.com` / `.com.ru`?
2. Первый публичный релиз: лендинг+персонажи (A+B) или сразу полный урок в браузере (A→C)?
3. Объяснения LLM: оставить на русском или переводить на язык интерфейса?