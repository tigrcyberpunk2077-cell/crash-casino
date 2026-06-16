# Деплой на сервер (чтобы работало без ПК, бесплатно)

Бот умеет два режима:
- **polling** — локально на ноуте (`python run.py`), нужен туннель для Mini App;
- **webhook** — на сервере: один веб-сервер и отдаёт Mini App, и принимает обновления
  Telegram. Постоянный https-адрес, ничего не «засыпает» намертво, ПК не нужен.

На хостинге включается переменной `USE_WEBHOOK=true` (в Docker уже стоит).

---

## Вариант A. Render (бесплатно, через GitHub, без карты) — рекомендую

### 1. Залей код на GitHub
```bash
cd /Users/tigranpetrosan/Downloads/игра
git init
git add .
git commit -m "Crash casino"
```
Создай пустой репозиторий на github.com → выполни, что он покажет:
```bash
git remote add origin https://github.com/ТВОЙ_НИК/crash-casino.git
git branch -M main
git push -u origin main
```
> `.env`, `.venv`, `vendor`, `*.db` не попадут в репозиторий — они в `.gitignore`.
> Токен бота в репозиторий НЕ кладём, впишем его в Render отдельно.

### 2. Создай сервис на Render
1. Зарегистрируйся на https://render.com (можно через тот же GitHub).
2. **New → Web Service** → подключи свой репозиторий.
3. Render увидит `Dockerfile` (или `render.yaml`) сам. План — **Free**.
4. В разделе **Environment** добавь переменную:
   - `BOT_TOKEN` = токен от @BotFather
   
   (`USE_WEBHOOK`, `WALLET_PROVIDER`, `PORT`, `RENDER_EXTERNAL_URL` подставятся сами.)
5. **Create Web Service** → дождись сборки. Получишь адрес вида
   `https://crash-casino.onrender.com`.

Готово. Бот сам выставит webhook и кнопку «🎰 Казино» на этот постоянный адрес.
Открой бота → `/app` → играй. ПК больше не нужен.

> ⚠️ Бесплатный Render «засыпает» после ~15 мин без запросов. Первое открытие
> после простоя — медленное (~30–60 c, холодный старт), дальше быстро. Telegram
> разбудит сервис при первом сообщении. Для демо это нормально.

> ⚠️ База `casino.db` на бесплатном плане сбрасывается при передеплое (балансы
> обнулятся). Это ок для демо. Для постоянного хранения нужен платный диск или
> внешняя БД.

---

## Вариант B. Railway / Koyeb / Fly.io

Тот же `Dockerfile` подходит. Подключаешь GitHub-репозиторий, задаёшь `BOT_TOKEN`
и `USE_WEBHOOK=true`, указываешь публичный адрес сервиса в `WEBAPP_URL` (если
платформа не даёт его автоматически). Koyeb и Fly не «засыпают».

---

## Вариант C. Свой VPS

```bash
ssh root@IP_СЕРВЕРА
git clone https://github.com/ТВОЙ_НИК/crash-casino.git && cd crash-casino
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# вписать BOT_TOKEN, USE_WEBHOOK=true, WEBAPP_URL=https://твой-домен в .env
python run.py
```
Для постоянной работы — systemd-юнит + nginx/Caddy с Let's Encrypt (или постоянный
cloudflared named tunnel для бесплатного https). Скажи — пришлю готовый юнит.

---

## Локально ничего не меняется
На ноуте по-прежнему: `bash start.sh` (polling + временный туннель).
`USE_WEBHOOK` оставь `false` в локальном `.env`.
