# Стек

> Канон архитектуры — [architecture.md](architecture.md). Здесь — список технологий (актуально на 2026-06-08).

## Backend / агент

- Python `>=3.11`, `uv`
- **LangChain 1.x** (`create_agent`) + **LangGraph 1.x** (граф агента, middleware, checkpointer)
- **MCP**: `mcp>=1.5` (FastMCP-сервер инструментов) + `langchain-mcp-adapters` (клиент, stdio-subprocess)
- **FastAPI** + `uvicorn` — HTTP API (:8000)
- **Chainlit `>=2`** — UI (:3000), `backend/src/chainlit_app.py`
- LLM-провайдеры: `langchain-openai` (Mistral / OpenRouter / NVIDIA / OpenAI — OpenAI-совместимые), `langchain-google-genai` (Gemini), `langchain-ollama` (локально)
- `rdkit` — нормализация SMILES в structural/similarity инструментах
- `httpx` — raw PUG REST; `pubchempy` — только в неподключённом типизированном слое
- `pydantic v2` + `pydantic-settings`, `orjson`, `tenacity`
- Хранилища: `sqlalchemy[asyncio]` + `asyncpg` / `psycopg` — история чатов Chainlit + LangGraph Postgres checkpointer
- `langfuse>=3` — трейсинг
- `pytest` + `respx`

## UI

- **Chainlit** — единственный живой UI (`CompoundCardV2` + `ElementSidebar`, кастомный логотип `public/logo_*.png`).
- `frontend/` (Next.js 16 / React 19) — **мёртвый legacy MVP**: не запускается, не целевой UI, оставлен только физически.

## Инфраструктура

- `infra/docker-compose.yml` — сервисы `api`, `chainlit`, `redis` (redis в runtime НЕ используется — кэш in-memory `TTLCache`, и тот в неподключённом слое)
- `infra/langfuse-compose.yml` — self-host Langfuse v3
- `infra/chainlit_schema.sql` — Postgres-схема истории чатов
- Postgres: история чатов (`DATABASE_URL`) + память агента (`AGENT_CHECKPOINT_POSTGRES_URL`, fallback на InMemorySaver)

## Источники данных

- `PubChem PUG REST` — источник правды (через 7 MCP-инструментов)
- `PUG View` — не включён

## Чего здесь нет

- vector DB / embeddings / классической RAG-инфраструктуры (название «RAG» историческое)
- прямого обращения браузера к PubChem
