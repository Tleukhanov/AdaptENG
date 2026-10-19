#!/usr/bin/env bash
# Деплой AdaptENG на Heroku: API (FastAPI) + Web (Next.js standalone).
#
# Использование (после `heroku login`):
#   bash tools/deploy.sh
#
# Переменные окружения (необязательно):
#   API_APP   — имя API-приложения   (по умолчанию adapteng-api)
#   WEB_APP   — имя web-приложения   (по умолчанию adapteng-web)
#   DOMAIN    — кастомный домен      (по умолчанию adapteng.app)
#   BRANCH    — ветка для деплоя     (по умолчанию текущая)
#   DRY_RUN=1 — только показать команды, ничего не выполнять

set -euo pipefail

API_APP="${API_APP:-adapteng-api}"
WEB_APP="${WEB_APP:-adapteng-web}"
DOMAIN="${DOMAIN:-adapteng.app}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
DRY_RUN="${DRY_RUN:-0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_PREFIX="[deploy]"

say() { printf '%s %s\n' "$LOG_PREFIX" "$1"; }
die() { printf '%s ОШИБКА: %s\n' "$LOG_PREFIX" "$1" >&2; exit 1; }

run() {
  say "$*"
  [ "$DRY_RUN" = "1" ] || eval "$@"
}

require_heroku() {
  command -v heroku >/dev/null 2>&1 || die "heroku CLI не найден: npm i -g heroku"
  heroku auth:whoami >/dev/null 2>&1 || die "сначала выполни: heroku login"
}

ensure_clean_tree() {
  if [ -n "$(git status --porcelain)" ]; then
    die "есть незакоммиченные изменения — закоммить их перед деплоем"
  fi
}

create_app() {
  local app="$1"
  if heroku apps:info --app "$app" >/dev/null 2>&1; then
    say "приложение $app уже существует"
  else
    say "создаём приложение $app"
    run "heroku apps:create $app"
  fi
}

deploy_api() {
  create_app "$API_APP"
  say "конфигурация API"
  run "heroku config:set --app $API_APP \
    API_INSECURE_AUTH=0 \
    API_CORS_ORIGINS=https://$DOMAIN,https://www.$DOMAIN \
    LLM_MAX_CONCURRENCY=8 \
    LLM_QUEUE_MAX=64 \
    API_RATE_LIMIT_PER_MIN=240"
  if [ -z "$(heroku config:get --app "$API_APP" DATABASE_URL 2>/dev/null)" ]; then
    say "PostgreSQL не привязан — подключаем существующий аддон, если он есть"
    # Сначала пробуем подключить уже купленный аддон (данные сохраняются),
    # и только если его нет — создаём новый.
    attached=""
    for plan in heroku-postgresql heroku-postgresql:essential-0; do
      if heroku addons:attach "$plan" --app "$API_APP" 2>/dev/null; then
        attached="$plan"
        break
      fi
    done
    if [ -z "$attached" ]; then
      say "аддона нет — создаём heroku-postgresql:essential-0"
      run "heroku addons:create heroku-postgresql:essential-0 --app $API_APP"
    else
      say "привязан аддон $attached (данные на месте)"
    fi
  else
    say "DATABASE_URL уже задан — существующую БД не трогаем"
  fi
  say "деплой api"
  run "heroku builds:create --app $API_APP --strategy heroku"
  run "heroku ps:scale api=1 web=0 --app $API_APP"
  say "подключаем ту же БД к боту (общий прогресс)"
  run "heroku addons:attach heroku-postgresql --app adapteng-bot 2>/dev/null || true"
  say "схема применится сама при старте (CREATE TABLE IF NOT EXISTS)"
  say "включаем ежедневные бэкапы БД"
  run "heroku addons:modify heroku-postgresql --app $API_APP \
    plan=essential-0 backup_hour=3 backup_retention_days=7 2>/dev/null || true"
}

deploy_web() {
  if heroku apps:info --app "$WEB_APP" >/dev/null 2>&1; then
    say "приложение $WEB_APP уже существует"
  else
    say "создаём $WEB_APP с Node-билдпаком (веб живёт в frontend/)"
    run "heroku create $WEB_APP --buildpack heroku/nodejs"
  fi
  say "деплой web: пушим поддерево frontend, его Procfile становится корневым"
  run "git subtree split --prefix=frontend -b deploy/$WEB_APP"
  run "git push $WEB_APP deploy/$WEB_APP:master --force"
  run "heroku config:set --app $WEB_APP \
    NEXT_PUBLIC_API_URL=https://$API_APP.herokuapp.com \
    NEXT_TELEMETRY_DISABLED=1"
  run "heroku ps:scale web=1 --app $WEB_APP"
  say "проверка: heroku logs --tail --app $WEB_APP"
}

attach_domain() {
  say "домены"
  run "heroku domains:add $DOMAIN --app $WEB_APP || true"
  run "heroku domains:wait $DOMAIN --app $WEB_APP || true"
}

smoke() {
  say "проверка /api/health"
  run "curl -fsS https://$API_APP.herokuapp.com/api/health"
  say "проверка сайта"
  run "curl -fsSI https://$DOMAIN | head -n 1 || true"
}

main() {
  require_heroku
  ensure_clean_tree
  say "ветка: $BRANCH"
  deploy_api
  deploy_web
  attach_domain
  smoke
  say "готово: https://$DOMAIN (API: https://$API_APP.herokuapp.com)"
  say "не забудь: heroku config:set --app $API_APP JWT_SECRET=\$(openssl rand -hex 32)"
}

main "$@"