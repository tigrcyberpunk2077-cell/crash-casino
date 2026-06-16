# 🎰 Crash Casino — учебный Telegram-бот

Демонстрационный Telegram-бот с игрой **Crash** на **тестовых монетах tTON**
(без реальной ценности). Проект создан для изучения:

- архитектуры Telegram-бота на **aiogram 3** (роутеры, FSM, inline-клавиатуры);
- **provably-fair** механики (commit-reveal, проверяемая честность раунда);
- живой игровой логики в реальном времени (растущий множитель, гонки cashout/crash);
- интеграции с блокчейном **TON testnet** (опционально).

> ⚠️ **Важно.** Это не азартная игра на реальные деньги. По умолчанию валюта —
> виртуальные фишки, выдаваемые «краном». Реальный приём денег под ставки без
> лицензии незаконен в большинстве юрисдикций — не используйте этот код для
> такого. Азартные игры могут вызывать зависимость.

## Как работает Crash

Множитель растёт от `1.00x` по экспоненте. Игрок должен нажать **«Забрать»** до
того, как раунд «крашнется» в заранее определённой точке. Забрал на `2.00x` →
выигрыш = ставка × 2. Не успел → ставка сгорает. House edge ≈ 1%.

## Быстрый старт (демо, без блокчейна)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# открой .env и впиши BOT_TOKEN от @BotFather

python3 run.py
```

В Telegram: `/start` → «Депозит» → «Получить из крана» → «Играть в Crash».

## 🎨 Mini App (красивое веб-приложение)

`python3 run.py` поднимает **и бота, и веб-сервер Mini App** на
`http://localhost:8080`. Это полноценный экран Crash с анимацией (космос, ракета
на неоновой кривой, взрыв при краше), лентой истории, лидербордом и нижней
навигацией. Игра идёт в реальном времени по WebSocket — сервер единственный
источник правды, множитель из браузера не подделать.

**Посмотреть дизайн прямо сейчас (в браузере):**
открой `http://localhost:8080` в Safari/Chrome. Работает гостевой режим — жми
кнопку с балансом (＋), чтобы получить тестовые монеты, и играй.

**Только превью дизайна, без бота и токена:**

```bash
python3 tools/preview_webapp.py   # наполняет демо-данными, http://localhost:8080
```

**Открыть внутри Telegram** (нужен публичный `https`, Telegram не пускает http):

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8080      # выдаст https-адрес
```

Полученный `https://...trycloudflare.com` впиши в `WEBAPP_URL` в `.env`,
перезапусти `python3 run.py` — в боте появится кнопка-меню «🎰 Казино»
(и команда `/app`), открывающая Mini App прямо в Telegram.

## Тесты ядра (без зависимостей)

```bash
python3 tests/run_tests.py
```

Проверяют формулу provably-fair (включая распределение и house edge), кривую
множителя и денежные единицы.

## Режим TON testnet (опционально)

Включает реальные on-chain депозиты и выводы в **тестовой сети TON** (монеты без
ценности, берутся из testnet-крана `@testgiver_ton_bot`).

```bash
pip install tonutils
```

В `.env`:

```
WALLET_PROVIDER=ton
TON_MNEMONIC=<24 слова отдельного testnet-кошелька>
TON_API_KEY=<ключ toncenter testnet>
```

- **Депозит.** Пользователь переводит tTON на адрес кошелька бота с
  **комментарием = его Telegram ID**. Фоновый воркер опрашивает toncenter v3,
  находит входящие переводы и зачисляет баланс (дедуп по хэшу транзакции).
- **Вывод.** Бот подписывает перевод с горячего кошелька на адрес игрока.

> Используйте **отдельный testnet-кошелёк** только для этого бота. Никогда не
> вставляйте сюда сид-фразу кошелька с реальными активами.

## Структура

```
run.py                     запуск
casino/
  config.py                конфиг из .env
  db.py                    SQLite (aiosqlite), балансы в nanoTON, атомарные операции
  provably_fair.py         commit-reveal + формула точки краша  ← покрыто тестами
  crash_engine.py          кривая множителя во времени          ← покрыто тестами
  units.py                 nanoTON ↔ tTON                       ← покрыто тестами
  keyboards.py             inline-клавиатуры
  states.py                FSM
  wallet/                  faucet (демо) и ton (testnet) провайдеры
  services/games.py        рантайм активных раундов (в чате)
  handlers/                common / balance / crash
  webapp/                  Mini App: aiohttp-сервер + WebSocket
    server.py              раздача статики, WS-протокол игры
    auth.py                проверка Telegram initData
    crash_session.py       серверный стор раундов          ← покрыто тестами
    static/                index.html / style.css / app.js (фронтенд + canvas)
tools/preview_webapp.py    dev-сервер только для Mini App (демо-данные)
tests/                     run_tests / integration / webapp / e2e
```

## Честность (Provably Fair)

```
crash_point = f( HMAC_SHA256(server_seed, "client_seed:nonce") )
```

До раунда бот показывает `SHA-256(server_seed)`. После — раскрывает `server_seed`,
и любой может пересчитать точку краша и убедиться, что результат не подделан.
`client_seed` можно задать самому командой `/seed`.
