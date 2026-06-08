# API-контракт

## `GET /api/health`

Возвращает базовый статус сервиса и информацию о настроенных upstream-URL.

## `POST /api/query`

Типизированный поиск без LLM. Принимает `QueryRequest`; `input_mode` маппится на MCP-инструмент (`QueryService`).

### Пример запроса

```json
{
  "input_mode": "name",
  "identifier": "aspirin",
  "operation": "property",
  "limit": 5,
  "include_raw": false
}
```

Поля: `input_mode` (обяз.), `identifier` (обяз.), `operation` (по умолч. `property`), `limit` (1–50, по умолч. 10), `include_raw` (по умолч. `false`). Поля `domain`/`properties`/`filters`/`pagination`/`output` в запросе **не существуют**.

### Поддерживаемые режимы ввода backend

- `cid`
- `name`
- `smiles`
- `inchikey`
- `formula`

В ручном UI сейчас показаны только `cid`, `name` и `smiles`.

### Поддерживаемые операции

- `property`
- `record`
- `synonyms`

Остальные имена операций уже зарезервированы в схеме, но в этой версии ещё не включены.

### Ответ

Общий envelope содержит:

- `trace_id`
- `source`
- `status`
- `raw`
- `normalized`
- `presentation_hints`
- `warnings`
- `error`

### Что находится в `normalized`

- `query`
- `matches[]`
- `primary_result`
- `synonyms[]`

## `POST /api/interpret`

Возвращает кандидаты структурированных запросов.

### Основные поля ответа

- `candidates[]`
- `confidence`
- `ambiguities[]`
- `assumptions[]`
- `warnings[]`
- `recommended_candidate_index`
- `needs_confirmation`

`recommended_candidate_index` нужен только для выбора кандидата по умолчанию. В интерфейсе он не показывается как “рекомендация”, а используется как техническое поле.

## `POST /api/agent`

Агентный поиск: natural-language → LLM сам выбирает MCP-инструменты PubChem → ответ.

### Запрос — `AgentRequest`

```json
{ "text": "what is aspirin?", "provider": null, "include_raw": true }
```

- `text` (обяз.) — запрос на естественном языке.
- `provider` — необязательный override LLM-провайдера (`mistral`/`gemini`/`openrouter`/`nvidia`/`openai`/`ollama`); по умолчанию primary из настроек.
- Заголовок `X-Session-Id` (необяз.) — стабильный id диалога для памяти агента (LangGraph `thread_id`).

### Ответ — `AgentResponseEnvelope`

`trace_id`, `status`, `raw`, `presentation_hints` (табы `answer/compounds/analysis/tools/json`), `warnings`, `error` и `normalized`:

- `final_answer`, `explanation[]`, `parsed_query`
- `needs_clarification`, `clarification_question`
- `matches[]`, `compounds[]`, `tool_trace[]`, `referenced_cids[]`

## Коды ошибок (enum `ErrorCode`)

- `VALIDATION_ERROR`
- `NO_MATCH`
- `AMBIGUOUS_QUERY`
- `ASYNC_PENDING`
- `RATE_LIMITED`
- `UPSTREAM_TIMEOUT`
- `UPSTREAM_UNAVAILABLE`
- `UNSUPPORTED_QUERY`
- `INTERPRETATION_LOW_CONFIDENCE`
- `LLM_NOT_CONFIGURED`
- `TOOL_LOOP_ABORTED`
- `INTERNAL_ERROR`

## Следующий слой API

- `GET /api/autocomplete`
- `GET /api/compound/{cid}/bundle`
- `GET /api/jobs/{job_id}`
