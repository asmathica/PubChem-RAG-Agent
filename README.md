# PubChem RAG Agent

PubChem agent для поиска соединений по естественному языку и точным химическим идентификаторам. Текущая рабочая связка строится так:

- `LangChain` для agent runtime и tool calling
- `Chainlit` для нового UI со streaming, steps и карточкой вещества
- `FastAPI` для отдельных API endpoints
- `Langfuse` для tracing

## Что сейчас является основным

- Основной UI: `Chainlit`
- Основной agent runtime: `backend/src/app/agent/*`
- Основной доступ к PubChem: `PubChemTransport` + `PubChemAdapter`
- `frontend/` на `Next.js` остаётся как legacy MVP и не считается целевым UI для новой agent-версии

## Быстрый старт

1. Создайте локальный env:

```bash
cp backend/.env.example backend/.env
```

2. Заполните в `backend/.env` как минимум:

```env
LLM_DEFAULT_PROVIDER=modal_glm
MODAL_GLM_API_KEY=...
MODAL_GLM_MODEL=zai-org/GLM-5.1-FP8
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

3. Запустите основной dev flow одной командой:

```bash
./scripts/dev.sh
```

После запуска:

- Chainlit UI: `http://127.0.0.1:3000`
- FastAPI API: `http://127.0.0.1:8000`

## Структура

- `backend/`
  - FastAPI API
  - LangChain agent runtime
  - Chainlit entrypoint `src/chainlit_app.py`
  - PubChem adapter/transport
- `frontend/`
  - legacy Next.js UI из раннего MVP
- `infra/`
  - docker-compose для API, Chainlit UI и Redis
- `docs/`
  - knowledge files по архитектуре и промежуточным решениям

## Документация

- [backend/README.md](backend/README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/llm-providers.md](docs/llm-providers.md) — где брать ключи, лимиты, цепочка failover
- [infra/README.md](infra/README.md) — локальный Langfuse v3 (tracing)
- [readme-api.md](readme-api.md)

## Команда

- [Арина Зеркалова](https://github.com/Arina-bear)
- [Софья Поселенова](https://github.com/cakepll123-lang)
- [Иван Селиванов](https://github.com/selivan3)

## Лицензия

MIT
