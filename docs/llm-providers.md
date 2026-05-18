# LLM-провайдеры PubChem-RAG-Agent

Полный гайд по тому, **где брать ключи**, **какие лимиты у каждого провайдера**
и **в каком порядке агент перебирает провайдеры** при ошибках.

---

## Цепочка failover (default chain)

```
┌─────────────────────────────┐
│ 1. Mistral Medium 3.5       │ ← Primary
│    (mistral-medium-3.5)     │   60 RPM / 1B токенов в месяц
└──────────────┬──────────────┘
               │ если упало
┌──────────────▼──────────────┐
│ 2. Google Gemma 4 / Gemini  │
│    (gemma-4-31b-it)         │   ~15 RPM / 500 RPD
└──────────────┬──────────────┘
               │ если упало
┌──────────────▼──────────────┐
│ 3. OpenRouter Gemma         │
│    (google/gemma-4-31b-it)  │   ~20 RPM (shared free pool)
└──────────────┬──────────────┘
               │ если упало
┌──────────────▼──────────────┐
│ 4. NVIDIA Llama 3.3 70B     │ ← Last resort
│    (meta/llama-3.3-70b-…)   │   40 RPM (медленнее, ~40-60s)
└─────────────────────────────┘
```

Реализация: LangChain `Runnable.with_fallbacks(...)` в
[`backend/src/app/agent/model_factory.py`](../backend/src/app/agent/model_factory.py).
При старте uvicorn ты видишь верифицирующую строку:

```
!!! FAILOVER: Mistral chat model wired with fallbacks →
    gemini:gemma-4-31b-it,
    openrouter:google/gemma-4-31b-it:free,
    nvidia:meta/llama-3.3-70b-instruct
```

Чтобы отключить fallback (для отладки) — `LLM_ENABLE_FALLBACK=false` в `.env`.

---

## Откуда брать ключи

### 1. Mistral La Plateforme — основная модель

| Параметр | Значение |
|---|---|
| Где получить | <https://console.mistral.ai/home?profile_dialog=api-keys> → **Create new key** |
| Формат ключа | `<32 alnum chars>` (без префикса) |
| Free tier RPM | **60** (1 запрос/сек) |
| Free tier TPM | 500 000 токенов/мин |
| Free tier monthly | **1 000 000 000** токенов в месяц |
| Tool calling | Нативный ✅ |
| Рекомендуемая модель | `mistral-medium-3.5` (frontier, agentic-optimized) |
| Альтернативы | `magistral-small-latest` (Small 4, быстрее), `mistral-large-latest` (Large 3, мощнее) |
| Документация | <https://docs.mistral.ai> |

**В `backend/.env`:**
```env
MISTRAL_API_KEY=<твой ключ>
MISTRAL_BASE_URL=https://api.mistral.ai/v1
MISTRAL_MODEL=mistral-medium-3.5
```

---

### 2. Google AI Studio (Gemini / Gemma)

| Параметр | Значение |
|---|---|
| Где получить | <https://aistudio.google.com/app/apikey> → **Create API key** |
| Формат ключа | `AIzaSy...` (39 символов) |
| Free tier RPM | 15 |
| Free tier RPD | 500 запросов в день |
| Free tier TPM | 250 000 токенов/мин |
| Tool calling | Нативный (function calling в формате OpenAPI) ✅ |
| Рекомендуемая модель | `gemma-4-31b-it` |
| Альтернативы | `gemini-3-flash-preview` (5 RPM, новее), `gemini-3.1-flash-lite-preview` (15 RPM) |
| ⚠️ Регион | Бывает блок по гео — нужен VPN/exit в supported region |
| Документация | <https://ai.google.dev/gemini-api/docs> |

**В `backend/.env`:**
```env
GOOGLE_API_KEY=<твой ключ>
GEMINI_MODEL=gemma-4-31b-it
```

---

### 3. OpenRouter

| Параметр | Значение |
|---|---|
| Где получить | <https://openrouter.ai/workspaces/default/keys> → **Create key** |
| Формат ключа | `sk-or-v1-<64 hex chars>` |
| Free tier RPM | **20** на модель (shared free pool) |
| Free tier RPD | 50 без credits / 1000 с $10+ credits на счёте |
| Tool calling | Зависит от модели — у бесплатных Gemma поддерживается ✅ |
| Рекомендуемая модель | `google/gemma-4-31b-it:free` |
| Альтернативы | `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen3-coder:free` |
| Документация | <https://openrouter.ai/docs/api/reference/limits> |

**Совет:** если упираешься в `429 — rate-limited upstream`, прицепи свой собственный
Google API ключ в OpenRouter dashboard:
<https://openrouter.ai/settings/integrations>. После этого OpenRouter будет ходить в
Gemma твоим ключом, а не из shared пула, и квоты будут только твои.

**В `backend/.env`:**
```env
OPENROUTER_API_KEY=<твой ключ>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemma-4-31b-it:free
```

---

### 4. NVIDIA NIM (build.nvidia.com)

| Параметр | Значение |
|---|---|
| Где получить | <https://build.nvidia.com> → выбрать любую модель → **Get API Key** |
| Формат ключа | `nvapi-<long string>` |
| Free tier RPM | **40** на endpoint модели |
| Free credits | 1000 inference credits при регистрации |
| Tool calling | Нативный ✅ |
| Рекомендуемая модель | `meta/llama-3.3-70b-instruct` (70B, проверенный tool calling) |
| Альтернативы | `nvidia/llama-3.3-nemotron-super-49b-v1` (49B, NVIDIA-tuned, быстрее), `mistralai/mixtral-8x22b-instruct-v0.1` (8x22B MoE) |
| ⚠️ EOL модели | `z-ai/glm4.7` сняли 2026-05-14 (410 Gone). Проверяй актуальный список: `curl -H "Authorization: Bearer $NVIDIA_API_KEY" https://integrate.api.nvidia.com/v1/models` |
| Документация | <https://docs.api.nvidia.com/nim> |

**В `backend/.env`:**
```env
NVIDIA_API_KEY=<твой ключ>
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=meta/llama-3.3-70b-instruct
```

---

## Rate limits в коде

Каждый провайдер имеет process-wide token bucket (LangChain `InMemoryRateLimiter`).
Все они меньше документированных free-tier cap'ов, чтобы переждать clock skew без 429:

| Провайдер | Cap upstream | В коде |
|---|---|---|
| Mistral | 60 RPM | **55 RPM** (`llm_rate_limit_mistral_rpm`) |
| NVIDIA NIM | 40 RPM | **35 RPM** (`llm_rate_limit_nvidia_rpm`) |
| OpenRouter | 20 RPM | **18 RPM** (`llm_rate_limit_openrouter_rpm`) |
| Google AI | 15 RPM | **13 RPM** (`llm_rate_limit_gemini_rpm`) |

Переопределить можно через ENV-переменную с тем же именем (uppercase).

---

## Quick start

1. **Получить минимум один ключ** (рекомендуется Mistral — самый щедрый):
   ```bash
   open https://console.mistral.ai/home?profile_dialog=api-keys
   ```

2. **Заполнить `backend/.env`** (скопировать из `.env.example` и подставить ключи):
   ```bash
   cd backend
   cp .env.example .env
   $EDITOR .env  # добавить MISTRAL_API_KEY (и опционально ключи остальных)
   ```

3. **Запустить dev-стек** (FastAPI :8000 + Chainlit :3000):
   ```bash
   ./scripts/dev.sh
   ```

4. **Проверить через curl**:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/agent \
        -H "Content-Type: application/json" \
        -d '{"text":"find aspirin"}' | jq
   ```

   Ожидаемый ответ:
   ```json
   {
     "status": "success",
     "normalized": {
       "request": {"provider": "mistral", "model": "mistral-medium-3.5"},
       "referenced_cids": [2244],
       "final_answer": "**Aspirin** - **PubChem CID:** 2244 - ..."
     }
   }
   ```

   Поле `provider` подскажет, какой именно провайдер ответил. Если, например,
   `provider="gemini"` — значит Mistral вернул ошибку, и chain advance'нул
   до Google.

---

## Сменить primary провайдера

Просто поменяй `LLM_DEFAULT_PROVIDER` в `.env`:

```env
LLM_DEFAULT_PROVIDER=mistral     # default (Mistral Medium 3.5)
LLM_DEFAULT_PROVIDER=nvidia      # → chain Nvidia → Mistral → OpenRouter → Gemini
LLM_DEFAULT_PROVIDER=gemini      # → chain Gemini → OpenRouter → NVIDIA
LLM_DEFAULT_PROVIDER=openrouter  # → openrouter без fallback
LLM_DEFAULT_PROVIDER=openai      # → openai без fallback (нужен OPENAI_API_KEY)
LLM_DEFAULT_PROVIDER=ollama      # → local Ollama без fallback (нужен запущенный ollama)
```

Каждый "primary" имеет свою цепочку fallback'ов — см. [`model_factory.py`](../backend/src/app/agent/model_factory.py).

---

## Что делать когда всё падает

Если ВСЕ четыре провайдера упали одновременно (редко, но бывает):

1. Chainlit UI покажет humanized сообщение:
   _"Языковая модель временно недоступна (5xx у провайдера). Попробуйте ещё раз через несколько секунд."_
2. FastAPI вернёт `status="error", error.code="UPSTREAM_UNAVAILABLE"`.
3. Логи бэкенда (`docker logs` или вывод `uvicorn`) покажут traceback каждого провайдера в цепочке.

Типовые причины:
- **Google FAILED_PRECONDITION** → проверить регион/VPN.
- **OpenRouter 429 "temporarily rate-limited upstream"** → прицепить свой
  Google ключ в <https://openrouter.ai/settings/integrations> или подождать ~1 минуту.
- **NVIDIA 410 Gone** → модель снята с production, проверь актуальный список через
  `curl /v1/models` и поменяй `NVIDIA_MODEL`.
- **Mistral 401** → ключ истёк или отозван, создай новый.
