#!/bin/bash
# Поднимает Mini App целиком: https-туннель (cloudflared) + бот.
# Сам подставляет свежий адрес туннеля в WEBAPP_URL и кнопку бота.
# Запуск:  bash start.sh      Остановка: Ctrl+C
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then echo "Нет .venv — сначала установи зависимости (см. README)"; exit 1; fi
source .venv/bin/activate

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Нет cloudflared. Установи:  brew install cloudflared"; exit 1
fi

echo "→ Запускаю https-туннель…"
cloudflared tunnel --url http://localhost:8080 --no-autoupdate > /tmp/cf_casino.log 2>&1 &
CF_PID=$!
trap 'echo; echo "Останавливаю…"; kill $CF_PID 2>/dev/null; exit 0' INT TERM

URL=""
for i in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf_casino.log | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -z "$URL" ]; then echo "Не удалось получить адрес туннеля"; kill $CF_PID; exit 1; fi
echo "→ Адрес Mini App: $URL"

# Прописываем адрес в .env (заменяем или добавляем строку WEBAPP_URL)
if grep -q '^WEBAPP_URL=' .env 2>/dev/null; then
  sed -i '' "s#^WEBAPP_URL=.*#WEBAPP_URL=$URL#" .env
else
  echo "WEBAPP_URL=$URL" >> .env
fi

echo "→ Запускаю бота (Ctrl+C — остановить всё)…"
python3 run.py
kill $CF_PID 2>/dev/null
