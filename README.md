<div align="center">
<img align="center" src=frontend/public/icon.svg width="25%"/>
</div>

<p align="center">
  <img src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&size=40&pause=1000&color=3e5c5e&center=true&vCenter=true&width=1000&lines=PubChem+AI+Assistant;LLM+Powered+Chemistry+Agent" />
</p>

<p align="center">

<img src="https://img.shields.io/badge/UI-Chainlit-00C6FF?style=for-the-badge"/>
<img src="https://img.shields.io/badge/Agent-LangChain-8E2DE2?style=for-the-badge"/>
<img src="https://img.shields.io/badge/API-FastAPI-0072FF?style=for-the-badge"/>
<img src="https://img.shields.io/badge/Tracing-Langfuse-FF4ECD?style=for-the-badge"/>

</p>

## ✨ Обзор

PubChem agent — ассистент поиска и сравнения свойств химических соединений, медикаментов на основании базы данных PubChem.




---

## 🧬 Архитектура

<img width="1231" height="695" alt="image" src="https://github.com/user-attachments/assets/26f99545-dd2c-401b-9a2f-3c6d2516d98e" />


## 🤖 LLM Фабрика

Система использует единый **уровень фабрики LLM**, который абстрагирует несколько провайдеров моделей (облачные + локальные) в единый интерфейс среды выполнения.

Этот уровень отвечает за:
- выбор основного LLM-провайдера
- формирование цепочки резервных вариантов среди доступных поставщиков
- обеспечение безопасных ограничений выполнения
- стандартизацию конфигурации среды выполнения
---


## ⚙️ Поддерживаемые модели

PubChem Agent построен как **multi-provider LLM система**, которая позволяет гибко переключаться между облачными и локальными моделями.

Это обеспечивает:
- устойчивость к падению API
- выбор баланса между скоростью и качеством
- возможность полностью локального запуска

---

### 🤖 Доступные LLM провайдеры

- 🟢 OpenAI (GPT модели)
- 🟣 Mistral AI
- 🔵 Google Gemini
- 🟡 NVIDIA NIM
- 🟠 OpenRouter (агрегация моделей)
- 🧪 Modal GLM (экспериментальные модели)
- 🖥 Ollama (локальные модели, полностью offline режим)

---

### 🔄 Как это работает

Система автоматически:
- выбирает primary модель из конфигурации
- подключает fallback цепочку при ошибках
- переключается между провайдерами без прерывания работы агента

👉 Это позволяет агенту оставаться доступным даже при недоступности отдельных API.

---



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

## 🚀 Дальнейшие пути расширения

PubChem Agent изначально спроектирован как расширяемая инструментальная система. Архитектура (LLM + MCP + нормализация + агентный runtime) позволяет постепенно добавлять новые источники данных и расширять возможности без изменения ядра агента.

### 🧪 Добавление новых внешних инструментов
- 🔬 ChEMBL — биоактивные молекулы и drug discovery данные  
- 🧬 DrugBank — информация о лекарствах и их мишенях  
- 🧪 AlphaFold DB (структуры белков)
- 🧪 UniChem — унификация идентификаторов между базами  
- 🌍 Wikidata / Wikipedia (общие справочные данные)  



### 🔍 Создание модулей генерации и моделирования
- 🧠 Предсказание свойств молекул (QSAR модели)
- ⚗️ Динамическое моделирование химических реакций
- 🧬 Генерация SMILES / InChI из описания
- 📉 Кластеризация и similarity search



### 🤖 Архитектурные улучшения
- 🧭 multi-step reasoning (планирование цепочек действий)
- 📚 retrieval по научным статьям (RAG поверх PubMed / Semantic Scholar)
- 🧠 memory layer для хранения пользовательских сессий
- 🧩 multi-agent режим (разные агенты под разные задачи)


### 🖥 UI и продуктовые расширения
- 📈 графы связей между веществами
- 💾 история запросов и исследований
- 🧑‍🔬 режим “лаборатории” (workflow builder)


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
