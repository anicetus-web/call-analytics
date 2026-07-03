# Call Analytics

Система анализа звонков: менеджеры загружают записи через Telegram-бота,
Whisper транскрибирует, LLM оценивает по настроенным метрикам, результаты
доступны через веб-панель.

## Стек

| Слой | Технология |
|------|-----------|
| API | Python 3.12, FastAPI, asyncpg |
| БД | PostgreSQL 16 |
| Очередь | asyncio.Queue (single-process) |
| Бот | aiogram 3 |
| AI | OpenAI Whisper API + GPT-4o-mini |
| Хранилище | Yandex Cloud Object Storage (S3) |
| Фронтенд | React + TypeScript + Vite, nginx |
| Деплой | Docker Compose |

## Быстрый старт

### 1. Конфиг

```bash
cp .env.example .env
# Заполните все поля — особенно JWT_SECRET_KEY и BOT_SECRET
# Генерация секрета: python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Lockfile фронтенда (обязательно перед первой сборкой)

```bash
cd frontend
npm install          # генерирует package-lock.json
git add package-lock.json
cd ..
```

`npm ci` в Dockerfile требует `package-lock.json` — без него сборка упадёт.
Это намеренно: без lockfile сборки недетерминированы.

### 3. Запуск

```bash
docker compose up --build
```

Compose запустит:

| Сервис | Роль |
|--------|------|
| `db` | PostgreSQL |
| `migrate` | Запускает `alembic upgrade head` один раз и завершается |
| `api` | FastAPI (HTTP, без бота и воркера) |
| `worker` | Telegram-бот + очередь задач (один инстанс, ВСЕГДА) |
| `frontend` | nginx: статика React + проксирование `/api/` |

> ⚠️ **`worker` должен быть ровно одним инстансом.** Очередь живёт в памяти процесса.
> `api` можно масштабировать горизонтально (`docker compose up --scale api=3`), `worker` — нет.

### 4. Первый администратор

Менеджеры авторизуются через Telegram, но у веб-панели логин/пароль — а изначально
в базе нет ни одного администратора. Создайте первого вручную:

```bash
docker compose exec api python -m scripts.create_admin <login> <пароль> "<Имя>"
```

### 5. Проверка

```
http://localhost:3000  → веб-панель (войти под логином из шага 4)
http://localhost:8000/health  → API health
```

## Структура проекта

```
call-analytics/
├── alembic/                # Миграции БД
│   └── versions/
│       ├── 0001_baseline.py                     # Полная начальная схема
│       ├── 0002_backfill_original_file_path.py  # Для апгрейда с предыдущих версий
│       └── 0003_fix_calls_index.py              # Индекс calls в соответствие с моделью
├── api/
│   ├── auth.py             # JWT + rate limiter на логин
│   ├── main.py              # FastAPI app, lifespan
│   └── routes/              # users, projects, metrics, calls, analytics, internal
├── bot/
│   ├── handlers.py         # aiogram handlers
│   ├── runtime.py          # Общая логика запуска бота+воркера
│   ├── states.py           # FSM состояния
│   └── worker_main.py      # Entrypoint воркер-процесса
├── database/
│   ├── base.py             # DeclarativeBase + ReprMixin
│   ├── connection.py       # Async engine, get_db, AsyncSessionLocal
│   ├── models.py           # SQLAlchemy ORM модели
│   └── __init__.py
├── scripts/
│   ├── create_admin.py     # Создание первого администратора (см. "Быстрый старт")
│   └── start_api.sh        # Entrypoint для API на Render (миграции + uvicorn)
├── services/
│   ├── analyzer.py         # LLM анализ + парсинг ответов
│   ├── call_processor.py   # Пайплайн: конвертация → транскрипция → анализ
│   ├── file_converter.py   # FFmpeg обёртка
│   ├── quota.py            # QuotaExhaustedError — общий для analyzer и transcription
│   ├── storage.py          # Yandex Cloud S3
│   ├── task_queue.py       # asyncio очередь задач
│   └── transcription.py    # Whisper API
├── frontend/
│   ├── src/                     # React/TypeScript
│   ├── Dockerfile               # Multi-stage: npm ci build + nginx
│   └── nginx.conf.template      # SPA + /api/ proxy + security headers (envsubst на старте)
├── config.py               # Pydantic Settings с валидацией
├── docker-compose.yml
├── Dockerfile
├── render.yaml              # Render Blueprint (демо-деплой)
└── requirements.txt
```

## Миграции

При изменении моделей:

```bash
# Генерация (с запущенной БД):
alembic revision --autogenerate -m "описание изменения"

# Применение:
alembic upgrade head

# Откат:
alembic downgrade -1
```

> После автогенерации переименуйте файл и `revision =` в нём под конвенцию
> `NNNN_description`, как у существующих миграций (Alembic по умолчанию
> генерирует случайный хэш, а не порядковый номер). Держите id коротким:
> `alembic_version.version_num` — `VARCHAR(32)`, слишком длинный id уронит
> апгрейд с малопонятной ошибкой усечения строки.

## Переменные окружения

Все переменные описаны в `.env.example` с комментариями.

Критичные:
- `DATABASE_URL` — PostgreSQL, обязательно `postgresql+asyncpg://`
- `JWT_SECRET_KEY` — минимум 16 символов, не должен начинаться с `change-me`
- `BOT_SECRET` — pre-shared secret между ботом и API
- `TELEGRAM_BOT_TOKEN` — токен бота из @BotFather
- `S3_*` — реквизиты Yandex Cloud Object Storage

## Архитектурные ограничения и известный технический долг

- **JWT в localStorage** — уязвим к XSS. Для публичного деплоя заменить на httpOnly cookie.
  Конкретные шаги миграции — в комментарии наверху `frontend/src/api.ts`.
- **In-memory rate limiter** — сбрасывается при рестарте процесса, не синхронизируется
  между репликами API. Для публичного API заменить на Redis-backed (например, slowapi).
- **In-memory task queue** — `worker` должен быть одним инстансом. При росте нагрузки
  заменить на Celery + Redis.
- **Per-project авторизация** — оба администратора (Влад, Катя) видят все проекты.
  Если нужна изоляция — добавить FK `projects.admin_id → users.id`.
