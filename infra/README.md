# Infra

## Local Langfuse (tracing) — v3 со встроенным авто-bootstrap

`langfuse-compose.yml` поднимает полный self-hosted стек Langfuse v3
(Postgres + ClickHouse + Redis + MinIO + langfuse-web + langfuse-worker)
и **автоматически** создаёт организацию, проект, пользователя и API-ключи
через `LANGFUSE_INIT_*` переменные. Никакого ручного signup.

### Запуск

```bash
docker compose -f infra/langfuse-compose.yml up -d
```

Через ~30–40 секунд Langfuse готов:

- **UI**: <http://localhost:3030> (логин: `dev@example.com` / `dev-pass-12345`)
- **Public Key**: `pk-lf-local-dev-public`
- **Secret Key**: `sk-lf-local-dev-secret`

Project уже создан (`pubchem-rag` под организацией `pubchem-org`).

### Подключить backend

В `backend/.env`:

```env
LANGFUSE_PUBLIC_KEY=pk-lf-local-dev-public
LANGFUSE_SECRET_KEY=sk-lf-local-dev-secret
LANGFUSE_BASE_URL=http://localhost:3030
```

Перезапусти `./scripts/dev.sh`. Каждый запрос к агенту теперь создаёт
trace в Langfuse → раздел **Traces**.

### Что увидишь в UI

На один `POST /api/agent {"text":"найди парацетамол"}` — ровно **9
observations** в одном trace:

| # | Тип | Имя | Latency |
|---|---|---|---|
| 1 | GENERATION | `ChatGoogleGenerativeAI` (`gemma-4-31b-it`) | ~7s |
| 2 | TOOL | `search_compound_by_name` | ~1s |
| 3 | GENERATION | `ChatGoogleGenerativeAI` (после tool result) | ~8s |
| 4-9 | CHAIN | `LangGraph` / `model` / `tools` / `ToolCallLimitMiddleware` | <1s |

Плюс тэги `[gemini, mcp-architecture, pubchem-agent]`, input/output,
token usage (input/output/total).

### Остановка

```bash
docker compose -f infra/langfuse-compose.yml down       # сохраняет данные
docker compose -f infra/langfuse-compose.yml down -v    # сносит volumes
```

### Порты на хосте (все на `127.0.0.1`)

| Сервис | Порт | Зачем |
|---|---|---|
| `langfuse-web` | `3030` | UI + публичное API (3000 в контейнере) |
| `langfuse-postgres` | `5433` | psql/pg_dump (если нужно) |
| `langfuse-clickhouse` | `8123, 9000` | HTTP + native protocol |
| `langfuse-minio` | `9090, 9091` | S3 API + MinIO console |
| `langfuse-redis` | `6380` | redis-cli |

### Почему v3 (а не v2)

v2 single-container больше не поддерживается официально (Zod-валидация
в свежих образах требует переменных, которые v2 не документирует).
v3 с шестью сервисами — текущая поддерживаемая архитектура; для одного
разработчика занимает ~1 GB RAM в покое.

### Если что-то не запускается

```bash
# Контейнер веб-приложения — основной источник ошибок
docker logs pubchem-langfuse --tail 50

# Worker (фоновая обработка трейсов)
docker logs pubchem-langfuse-worker --tail 50

# Полный сброс (volumes тоже снести):
docker compose -f infra/langfuse-compose.yml down -v
docker compose -f infra/langfuse-compose.yml up -d
```

Частые причины 500-ок при старте:
- `ENCRYPTION_KEY` должен быть **64 hex-символа** в кавычках в YAML
  (без кавычек YAML может прочитать `0000…` как число `0`).
- `LANGFUSE_INIT_USER_EMAIL` должен быть валидным email с TLD
  (`dev@example.com`, не `dev@localhost`).

## Основной dev-стек (`docker-compose.yml`)

`docker-compose.yml` (соседний файл) собирает образ FastAPI + Chainlit
из `backend/` и поднимает Redis. **Этот compose не обязателен для
локального dev** — `./scripts/dev.sh` запускает оба процесса
напрямую через `uv run` без Docker. Используй `docker-compose.yml`
только для production-подобной проверки.
