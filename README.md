# tg-relay

**Прозрачный HTTP-шлюз к Telegram Bot API.** Меняете в своём фреймворке базовый
URL — и бот продолжает работать без единой другой правки в коде.

```
Напрямую:     https://api.telegram.org/bot<TOKEN>/<method>
Через шлюз:   https://relay.example.com/k/<KEY>/bot<TOKEN>/<method>
```

Любой метод, любое тело, любой код ответа проходят насквозь байт в байт. Шлюз не
знает семантику методов Telegram и не держит их белого списка: он проксирует,
считает потребление и следит за лимитами — и всё.

> 🌐 **Не хотите держать свой сервер?** Готовый управляемый шлюз с личным
> кабинетом, ключами, графиками и журналом ошибок —
> **[tg-relay.scriptora.ru](https://tg-relay.scriptora.ru)**.
> Документация по подключению — [tg-relay.scriptora.ru/docs](https://tg-relay.scriptora.ru/docs),
> статус узлов — [tg-relay.scriptora.ru/status](https://tg-relay.scriptora.ru/status).
> В этом репозитории — открытый код самого шлюза, который там работает.

## Возможности

- **Токен бота не сохраняется нигде** — ни в логах, ни в базе, ни в метриках.
  Наружу попадает только отпечаток: первые 12 символов SHA-256.
- **База не на пути запроса.** Ключи и счётчики живут в памяти узла. Если
  PostgreSQL упал, боты продолжают работать на последнем известном состоянии.
- **Long polling из коробки.** `getUpdates` с `timeout` до 60 с держится без
  обрывов и без буферизации.
- **Потоковая передача** загрузок и скачиваний файлов: тело не копится в памяти.
- **Проекты и ключи** с ротацией без простоя; ключи хранятся только хешем.
- **Лимиты тарифа**: запросы в секунду, активные боты в месяц, трафик в месяц.
  Ошибки шлюза приходят в формате Bot API, поэтому фреймворки разбирают их штатно.
- **Наблюдаемость**: JSON-логи, метрики Prometheus, `/healthz` и `/readyz`,
  почасовая статистика и журнал ошибок в базе для своих дашбордов.
- **Горизонтальное масштабирование**: узлы взаимозаменяемы, а счётчики в базе
  прибавляются, а не перезаписываются.
- **Корректная остановка**: по сигналу узел сразу становится неготовым, а висящие
  long poll получают время, чтобы завершиться.

## Содержание

- [Быстрый старт](#быстрый-старт)
- [Подключение бота](#подключение-бота)
- [Управление проектами и ключами](#управление-проектами-и-ключами)
- [Настройки](#настройки)
- [Ответы шлюза](#ответы-шлюза)
- [Наблюдаемость](#наблюдаемость)
- [Боевое развёртывание](#боевое-развёртывание)
- [Архитектура](#архитектура)
- [Разработка](#разработка)
- [Безопасность](#безопасность)
- [Лицензия](#лицензия)

## Быстрый старт

### Docker Compose: шлюз и PostgreSQL

```bash
git clone <repo-url> tg-relay && cd tg-relay
make env    # .env со случайным паролем базы и ключом первого проекта
make up     # docker compose up -d --build
```

`make env` напечатает ключ вида `rl_live_…` — сохраните его. Проверка:

```bash
curl http://localhost:8080/readyz
curl http://localhost:8080/k/<KEY>/bot<TOKEN>/getMe
```

### Автономный режим: один контейнер без базы

Если нужен просто прокси с одним ключом, без лимитов и учёта:

```bash
docker build -t tg-relay .
docker run -p 8080:8080 -e BOOTSTRAP_KEY=rl_live_$(openssl rand -hex 16) tg-relay
```

### Без Docker

```bash
pip install .
BOOTSTRAP_KEY=rl_live_my_secret_key tg-relay serve
```

Нужен Python 3.11+.

## Подключение бота

Везде `https://relay.example.com` — адрес вашего шлюза, а `KEY` — ключ проекта.

<details open>
<summary><b>aiogram 3</b></summary>

```python
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

api = TelegramAPIServer(
    base="https://relay.example.com/k/KEY/bot{token}/{method}",
    file="https://relay.example.com/k/KEY/file/bot{token}/{path}",
)
bot = Bot(token=TOKEN, session=AiohttpSession(api=api))
```
</details>

<details>
<summary><b>python-telegram-bot 20+</b></summary>

```python
from telegram.ext import Application

app = (
    Application.builder()
    .token(TOKEN)
    .base_url("https://relay.example.com/k/KEY/bot")
    .base_file_url("https://relay.example.com/k/KEY/file/bot")
    .build()
)
```
</details>

<details>
<summary><b>pyTelegramBotAPI (telebot)</b></summary>

```python
from telebot import apihelper

apihelper.API_URL = "https://relay.example.com/k/KEY/bot{0}/{1}"
apihelper.FILE_URL = "https://relay.example.com/k/KEY/file/bot{0}/{1}"
```
</details>

<details>
<summary><b>grammY</b></summary>

```ts
import { Bot } from "grammy";

const bot = new Bot(TOKEN, { client: { apiRoot: "https://relay.example.com/k/KEY" } });
```
</details>

<details>
<summary><b>Telegraf</b></summary>

```ts
import { Telegraf } from "telegraf";

const bot = new Telegraf(TOKEN, { telegram: { apiRoot: "https://relay.example.com/k/KEY" } });
```
</details>

<details>
<summary><b>node-telegram-bot-api</b></summary>

```js
const TelegramBot = require("node-telegram-bot-api");

const bot = new TelegramBot(TOKEN, { polling: true, baseApiUrl: "https://relay.example.com/k/KEY" });
```
</details>

<details>
<summary><b>Go: go-telegram-bot-api v5</b></summary>

```go
bot, err := tgbotapi.NewBotAPIWithAPIEndpoint(token, "https://relay.example.com/k/KEY/bot%s/%s")
```
</details>

<details>
<summary><b>curl</b></summary>

```bash
curl "https://relay.example.com/k/KEY/bot$TOKEN/getMe"
```
</details>

Примеры для других языков и библиотек — в
[документации сервиса](https://tg-relay.scriptora.ru/docs).

## Управление проектами и ключами

Проект — это единица лимитов и учёта. У проекта может быть несколько ключей: так
ключ меняется без простоя (выпустили новый → переключили ботов → отключили старый).

```bash
tg-relay create-project --name acme --rate 30 --bots 100 --gb 50
tg-relay add-key --project 1
tg-relay list-projects
tg-relay disable-key --key rl_live_...
tg-relay disable-project --project 1
tg-relay migrate
```

В Docker Compose то же самое: `make cli ARGS="list-projects"`.

Ключ печатается **один раз**: в базе лежит только его SHA-256. Новый или
отключённый ключ начинает действовать на всех узлах в течение `KEY_CACHE_TTL`
(по умолчанию 30 с).

`BOOTSTRAP_KEY` создаёт проект `bootstrap` только на **пустой** базе. Дальше
проектами управляют через CLI.

## Настройки

Все настройки задаются переменными окружения. Если значение некорректно, шлюз
не запустится и назовёт переменную с ошибкой.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL. Без неё шлюз работает в автономном режиме |
| `BOOTSTRAP_KEY` | — | Ключ первого проекта; в автономном режиме это единственный ключ |
| `UPSTREAM_URL` | `https://api.telegram.org` | Куда проксировать (например, свой `telegram-bot-api`) |
| `LISTEN_HOST` / `LISTEN_PORT` | `0.0.0.0` / `8080` | Адрес и порт, на которых слушает шлюз |
| `UPSTREAM_CONNECT_TIMEOUT` | `10` | Таймаут соединения с upstream, с |
| `UPSTREAM_READ_TIMEOUT` | `0` | `0` — без ограничения. **Иное значение ломает long polling** |
| `UPSTREAM_WRITE_TIMEOUT` | `120` | Таймаут отправки тела, с |
| `UPSTREAM_KEEPALIVE` | `90` | Сколько держать простаивающее соединение с upstream, с |
| `MAX_CONNECTIONS` | `2000` | Предел соединений к upstream |
| `MAX_BODY_BYTES` | `62914560` | Предел тела запроса (60 МиБ) |
| `ENFORCE_LIMITS` | `true` | Проверять лимиты проектов (402/429) |
| `STATS_ENABLED` | `true` | Писать почасовую статистику и журнал ошибок в базу |
| `KEY_CACHE_TTL` | `30` | Период перечитывания ключей и итогов месяца, с |
| `USAGE_FLUSH_INTERVAL` | `10` | Период сброса учёта в базу, с |
| `LAST_REQUEST_FLUSH_INTERVAL` | `2` | Период сброса «последнего запроса» проекта, с |
| `SHUTDOWN_GRACE` | `90` | Сколько ждать висящие запросы при остановке, с |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT` | `json` | `json` или `text` |
| `NODE_NAME` | `edge-1` | Имя узла в логах |

## Ответы шлюза

Свои ошибки шлюз отдаёт в формате Bot API:

```json
{"ok": false, "error_code": 429, "description": "Too Many Requests: gateway rate limit",
 "parameters": {"retry_after": 1}}
```

| Код | Когда |
|---|---|
| `401` | Ключ проекта неизвестен или отключён |
| `402` | Исчерпан месячный лимит: трафик или число ботов |
| `413` | Тело больше `MAX_BODY_BYTES` |
| `429` | Превышен лимит запросов проекта (есть заголовок `Retry-After`) |
| `502` | Upstream недоступен |
| `504` | Upstream не ответил вовремя |

Ошибки самого Telegram, включая его собственный `429` со своим `retry_after`,
проходят насквозь без изменений.

## Наблюдаемость

| Эндпоинт | Назначение |
|---|---|
| `GET /healthz` | Процесс жив; пока отвечает, всегда `200` |
| `GET /readyz` | Узел готов к трафику: ключи загружены и остановка не идёт; иначе `503` |
| `GET /metrics` | Метрики Prometheus |

Метрики: `relay_requests_total{project,code}`, `relay_request_seconds`
(без long polling), `relay_inflight_requests`, `relay_rejections_total{reason}`,
`relay_key_cache_size`, `relay_key_cache_stale`. Метка `project` — числовой id,
никаких имён, ключей и токенов.

Всплеск `relay_rejections_total{reason="unauthorized"}` означает, что кто-то
перебирает ключи. `relay_key_cache_stale == 1` означает, что база недоступна и
узел работает на последнем кэше.

При `STATS_ENABLED=true` шлюз пишет в базу данные для дашбордов: `request_stats`
(почасовые запросы, ошибки, p50/p95), `request_errors` (последние 500 ошибок
проекта) и `project_last_request`. Схема лежит в
[`migrations/`](src/tg_relay/adapters/storage/postgres/migrations).

## Боевое развёртывание

- **TLS.** Поставьте перед шлюзом обратный прокси. Готовый пример для Caddy —
  [`deploy/Caddyfile`](deploy/Caddyfile). Важно: без буферизации
  (`flush_interval -1`), без таймаута чтения и без сжатия ответов.
- **Несколько узлов.** Запустите несколько экземпляров с одним `DATABASE_URL` за
  балансировщиком, который смотрит в `/readyz`. Миграции накатывает один узел под
  advisory-lock. Rate limit считается на узел; общий лимит на кластер потребует
  отдельного адаптера (например, Redis).
- **Остановка.** `stop_grace_period` в оркестраторе должен быть больше
  `SHUTDOWN_GRACE`, иначе висящие long poll оборвутся.
- **Свой Bot API server.** `UPSTREAM_URL=http://telegram-bot-api:8081` — шлюз
  работает с любым совместимым upstream.

## Архитектура

Гексагональная архитектура (Ports & Adapters) и цепочка фильтров запроса. Ядро не
знает ни про Starlette, ни про httpx, ни про PostgreSQL: оно общается с внешним
миром через протоколы-порты, а конкретные адаптеры связываются в одном месте —
`bootstrap.py`.

```
src/tg_relay/
├── domain/          модели, правила, ошибки — только стандартная библиотека
├── ports/           контракты: KeySource, UsageRepository, StatsRepository, Upstream, RequestObserver
├── application/     сценарии: ProxyService, фильтры, учёт, статистика, фоновые задачи
│   └── filters/     Auth → Quota → RateLimit → BodyLimit
├── adapters/
│   ├── http/        Starlette: маршруты, пробы, потоковый ответ
│   ├── upstream/    httpx: потоковая передача в Bot API
│   ├── storage/     PostgreSQL (asyncpg + SQL-миграции) и статический ключ
│   └── observability/  JSON-логи, Prometheus
├── bootstrap.py     composition root: сборка узла из настроек
├── config.py        настройки из окружения с валидацией
├── server.py        uvicorn с корректной остановкой
└── cli.py           tg-relay serve | migrate | create-project | ...
```

Подробный разбор с диаграммами и ответами на вопрос «почему так» —
в [docs/architecture.md](docs/architecture.md).

## Разработка

```bash
python -m venv .venv && . .venv/bin/activate
make install     # pip install -e ".[dev]"
make check       # ruff + mypy --strict + pytest
```

Тесты на PostgreSQL запускаются, если задан `TEST_DATABASE_URL`. **База будет
очищена**, используйте отдельную:

```bash
docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=test postgres:16-alpine
TEST_DATABASE_URL=postgres://postgres:test@localhost:55432/postgres make test
```

В тестах совместимости работают настоящие aiogram 3 и requests поверх
подставного Bot API ([`tests/support/fake_telegram.py`](tests/support/fake_telegram.py)).
Нагрузочный замер запускается командой `make bench`.

Как предложить изменения, описано в [CONTRIBUTING.md](CONTRIBUTING.md).

## Безопасность

- Токен бота живёт только в памяти, на время запроса. Access-лог uvicorn выключен,
  а логгеры httpx и httpcore подняты до `WARNING`, потому что они пишут URL
  с токеном. Отсутствие токена в логах и метриках проверяют тесты.
- Ключи проектов хранятся хешем SHA-256.
- Upstream фиксирован настройкой, редиректы не выполняются: запрос с токеном
  нельзя увести на чужой хост.
- Контейнер работает от непривилегированного пользователя с ФС только для чтения.

Уязвимость? Сообщите о ней приватно, как описано в [SECURITY.md](SECURITY.md).

## Лицензия

[MIT](LICENSE). Управляемая версия шлюза — [tg-relay.scriptora.ru](https://tg-relay.scriptora.ru).
