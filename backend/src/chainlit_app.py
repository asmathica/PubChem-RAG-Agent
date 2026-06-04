from __future__ import annotations

from typing import cast
import json
import os
import uuid

import chainlit as cl
from chainlit.input_widget import Select
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.types import ThreadDict

from app.agent.meta import is_capability_question
from app.container import AppContainer, build_container
from app.errors.models import AppError
from app.presenters.compound_card import (
    build_candidates_markdown,
    build_compound_card_props,
    build_details_markdown,
    build_structure_image_url,
    build_tool_trace_markdown,
    extract_primary_synonyms,
    select_primary_compound,
)
from app.schemas.agent import AgentRequest, AgentResponseEnvelope
import httpx
import logging

logger = logging.getLogger(__name__)

async def check_ollama_availability(base_url: str = "http://localhost:11434") -> bool:
    """True если локальная Ollama отвечает. Таймаут 2с — чтобы не вешать UI."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, timeout=2.0)
        return response.status_code == 200 and "Ollama is running" in response.text
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.warning("Ollama недоступна на %s", base_url)
        return False

def _get_or_create_container() -> AppContainer:
    container = cl.user_session.get("container")
    if container is None:
        container = build_container()
        cl.user_session.set("container", container)
    return cast(AppContainer, container)


def _current_thread_id() -> str:
    """LangGraph thread_id = id текущего Chainlit чата (свой UUID на каждый чат).
    Новый чат → свежая память агента; resume → checkpointer подхватит state по
    тому же id. Если None (вне chat lifecycle) — runtime откатится на trace_id."""
    return cast(str, cl.context.session.thread_id)


def _data_layer_ready(database_url: str, timeout: float = 2.0) -> bool:
    """Проверяет что Postgres доступен И схема Chainlit применена (таблица users).

    Защита от ошибки 'Not Found: User not found'. Недостаточно проверить только
    TCP-порт: если Postgres поднят, но схема не применена, Chainlit.get_user
    вернёт None → HTTP 404 'User not found' (ровно исходный баг). Поэтому делаем
    реальный коннект + проверяем наличие таблицы users. Любой сбой (порт закрыт,
    нет БД, нет схемы) → False → data layer не регистрируем → UI работает без
    истории чатов, но без красных ошибок.
    """
    import asyncio

    async def _check() -> bool:
        import asyncpg

        # asyncpg не понимает '+asyncpg' в схеме URL — убираем драйвер-суффикс.
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=timeout)
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
            return False
        try:
            return bool(await conn.fetchval("SELECT to_regclass('public.users') IS NOT NULL"))
        finally:
            await conn.close()

    try:
        return asyncio.run(_check())
    except RuntimeError:
        # Сюда попадаем только если loop уже запущен (нетипично на импорте
        # модуля). Безопаснее не регистрировать data layer, чем рискнуть 404.
        return False


# Data layer хранит чаты/сообщения/пользователей в Postgres. Без него Chainlit
# не показывает sidebar с историей чатов и кнопку "New Chat". Регистрируем ТОЛЬКО
# если (1) задан DATABASE_URL и (2) БД доступна со схемой — иначе graceful
# degradation в dev-режим без истории (но без ошибок 'User not found').
_DATABASE_URL = os.environ.get("DATABASE_URL")

if _DATABASE_URL and _data_layer_ready(_DATABASE_URL):
    @cl.data_layer
    def get_data_layer():
        return SQLAlchemyDataLayer(conninfo=_DATABASE_URL)

    logger.info("Chainlit data layer ВКЛЮЧЁН — история чатов сохраняется в Postgres")
elif _DATABASE_URL:
    logger.warning(
        "DATABASE_URL задан, но БД недоступна или схема не применена — data layer "
        "ОТКЛЮЧЁН (UI без истории чатов). Применить схему: "
        "psql -d chainlit -f infra/chainlit_schema.sql"
    )


@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    """Простейший dev-auth: любой username + любой password = login.
    `identifier=username` — ключ пользователя в data layer (его чаты видны
    только ему). Для production заменить на проверку DB / OAuth / SSO.
    См. https://docs.chainlit.io/authentication."""
    if username:
        return cl.User(identifier=username, metadata={"role": "user"})
    return None


def _humanize_runtime_error(exc: BaseException) -> str:
    """Короткое русское сообщение пользователю по типу исключения.

    Использует normalize_agent_exception (тот же мэппер что в AgentService),
    чтобы текст ошибки в Chainlit совпадал с тем что вернёт HTTP-роут.
    """
    from app.agent.error_mapper import normalize_agent_exception
    if isinstance(exc, Exception):
        try:
            return normalize_agent_exception(exc).message
        except Exception:  # на случай если mapper сам упал
            pass
    return "Не удалось завершить запрос — попробуйте ещё раз. Если проблема повторится, проверьте логи бэкенда."


@cl.set_starters
async def set_starters(
    current_user: cl.User | None = None,  # noqa: ARG001
    language: str = "ru-RU",
) -> list[cl.Starter]:
    is_russian = language.lower().startswith("ru")
    if is_russian:
        return [
            cl.Starter(
                label="Антибиотик по признакам",
                message="антибиотик с бензольным кольцом, молекулярная масса около 350",
            ),
            cl.Starter(
                label="Похожее на aspirin",
                message="соединение похоже на aspirin",
            ),
            cl.Starter(
                label="Молекула по описанию",
                message="найди молекулу по описанию и верни свойства",
            ),
            cl.Starter(
                label="Какие у тебя инструменты?",
                message="Какие инструменты у тебя есть?",
            ),
        ]

    return [
        cl.Starter(
            label="Antibiotic by constraints",
            message="antibiotic with a benzene ring and molecular weight around 350",
        ),
        cl.Starter(
            label="Similar to aspirin",
            message="find a compound similar to aspirin",
        ),
        cl.Starter(
            label="Find by description",
            message="find a molecule from its description and return key properties",
        ),
        cl.Starter(
            label="What tools do you have?",
            message="What tools do you have?",
        ),
    ]


# Опции дропдауна "LLM провайдер" в Chainlit settings (⚙️ в правом верхнем углу).
# Порядок повторяет fallback chain в model_factory.py: mistral → gemini → openrouter → nvidia.
# `ollama` оставлен в конце для локальной разработки. `openai` и `modal_glm` исключены:
# для openai нет ключа в .env, modal_glm — устаревший Modal-deployment.
# Fallback chain работает всегда (LLM_ENABLE_FALLBACK=true) — этот селектор задаёт только PRIMARY.
PROVIDER_OPTIONS = ["mistral", "gemini", "openrouter", "nvidia", "ollama"]


@cl.on_chat_start
async def on_chat_start() -> None:
    container = _get_or_create_container()

    # Health-check Ollama делаем только если он primary (это локальный сервис, может быть
    # выключен). Для облачных провайдеров (Mistral/Gemini/OpenRouter/NVIDIA) пинговать смысла
    # нет — `Runnable.with_fallbacks(...)` в model_factory.py подменит недоступного на
    # следующего в цепочке прямо во время запроса.
    if container.settings.llm_default_provider == "ollama":
        ollama_ok = await check_ollama_availability("http://localhost:11434")
        if not ollama_ok:
            await cl.Message(content="❌ Ошибка: Локальная модель Ollama недоступна. Пожалуйста, запусти приложение Ollama в системе и обнови страницу.").send()

    # thread_id управляется Chainlit (cl.context.session.thread_id), его не нужно
    # генерировать руками — каждый новый чат в UI получает свой UUID автоматически.

    # Initial value селектора: дефолт из .env (LLM_DEFAULT_PROVIDER), если он в списке;
    # иначе откатываемся на первый элемент (mistral).
    default_provider = container.settings.llm_default_provider
    initial = default_provider if default_provider in PROVIDER_OPTIONS else PROVIDER_OPTIONS[0]

    # ChatSettings.send() рендерит панель и сразу возвращает текущие значения виджетов.
    # Фиксируем выбор в user_session — он используется в on_message ниже как provider.
    settings = await cl.ChatSettings(
        [
            Select(
                id="llm_provider",
                label="LLM провайдер (primary; fallback chain активен в любом случае)",
                values=PROVIDER_OPTIONS,
                initial_value=initial,
            ),
        ]
    ).send()
    cl.user_session.set("llm_provider", settings["llm_provider"])


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    """Срабатывает когда пользователь меняет провайдер в Chainlit settings панели
    ПОСЛЕ старта чата. Обновляем user_session — следующий on_message пойдёт на новый primary."""
    cl.user_session.set("llm_provider", settings["llm_provider"])


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    """Срабатывает когда пользователь кликает по старому чату в sidebar.
    Chainlit сам отрисует прошлые сообщения из data layer (мы их не трогаем),
    а нам нужно восстановить контейнер DI и last-known provider для этой
    сессии. LangGraph checkpointer подхватит свой state по thread_id автоматически
    при первом on_message — он хранит state per-thread, и thread_id у resume чата
    тот же, что был при on_chat_start."""
    _get_or_create_container()
    container = cl.user_session.get("container")
    metadata = thread.get("metadata") or {}
    provider = metadata.get("agent_provider") or _resolve_session_provider(cast(AppContainer, container))
    cl.user_session.set("llm_provider", provider)


@cl.on_chat_end
async def on_chat_end() -> None:
    container = cl.user_session.get("container")
    if container is not None:
        await cast(AppContainer, container).close()


def _chainlit_metadata(session_id: str, provider: str) -> dict[str, str | list[str]]:
    """Метаданные для Langfuse: связывают трейсы с chat'ом и пользователем
    в одной surface ('chainlit'), добавляют tags для фильтрации."""
    return {
        "surface": "chainlit",
        "chainlit_session_id": session_id,
        "langfuse_session_id": session_id,
        "langfuse_user_id": session_id,
        "langfuse_tags": ["pubchem-agent", provider, "chainlit"],
        "agent_provider": provider,
    }


def _resolve_session_provider(container: AppContainer) -> str:
    """Provider текущей Chainlit-сессии: явный выбор из ⚙️ Settings или дефолт."""
    return cast(str, cl.user_session.get("llm_provider") or container.settings.llm_default_provider)


async def _send_agent_answer(content: str, elements: list[cl.Element] | None = None) -> None:
    """Отправляет финальный ответ ассистента как root-level сообщение (parent_id=None).

    Зачем форсим parent_id=None: Chainlit в Message.__post_init__ привязывает
    сообщение к последнему открытому cl.Step. Промежуточные cl.Step ("Поиск",
    "Интерпретация") при cot='hidden' НЕ персистятся в data layer, поэтому ответ
    с parentId на них при resume становится orphan'ом — фронт не может отрисовать
    сообщение с несуществующим родителем. Из-за этого в истории чата были видны
    только запросы пользователя, но не ответы агента. Root-level (parent_id=None)
    сохраняется и восстанавливается корректно.
    """
    msg = cl.Message(content=content, elements=elements or [], author="PubChem Agent")
    msg.parent_id = None
    await msg.send()


def _build_primary_compound_elements(
    response: AgentResponseEnvelope,
    primary,
) -> tuple[list[cl.Element], list[cl.Element]]:
    """Inline-карточка (CompoundCardV2) + sidebar (свойства markdown) для primary compound.

    Картинку структуры здесь НЕ добавляем (ни в карточку, ни в sidebar) — она
    встроена в markdown текста ответа (см. on_message), чтобы молекула
    персистилась и была видна при resume истории чата, без дублей в live.
    """
    synonyms = extract_primary_synonyms(response, primary.cid)
    inline = [
        cl.CustomElement(
            # V2 в имени — чтобы браузер не отдавал кэш старой /public/elements/CompoundCard.jsx;
            # Chainlit 2.11 не делает version-hash в URL, перебить кеш можно только через имя.
            name="CompoundCardV2",
            props=build_compound_card_props(
                primary,
                explanation=response.normalized.explanation if response.normalized else None,
                synonyms=synonyms,
            ),
            display="inline",
        ),
    ]
    sidebar = [
        cl.Text(
            name="Свойства вещества",
            content=build_details_markdown(response),
            display="side",
        ),
    ]
    return inline, sidebar


@cl.on_message
async def on_message(message: cl.Message) -> None:
    container = _get_or_create_container()
    session_id = _current_thread_id()
    provider = _resolve_session_provider(container)
    trace_id = uuid.uuid4().hex

    request = AgentRequest(text=message.content, provider=provider, include_raw=True)
    metadata_overrides = _chainlit_metadata(session_id, provider)

    async def _execute() -> AgentResponseEnvelope:
        return await container.agent_service.execute(
            request,
            trace_id=trace_id,
            session_id=session_id,
            metadata_overrides=metadata_overrides,
        )

    try:
        if is_capability_question(message.content):
            response = await _execute()
        else:
            async with cl.Step(name="Поиск в PubChem") as step:
                step.output = "Ищу кандидатов в PubChem и собираю ключевые свойства..."
                response = await _execute()
                step.output = "Поиск завершён."
    except AppError as error:
        await _send_agent_answer(error.message)
        return
    except Exception as exc:
        await _send_agent_answer(_humanize_runtime_error(exc))
        return

    normalized = response.normalized
    if normalized is None:
        await _send_agent_answer("Не удалось получить итоговый ответ от агента.")
        return

    parsed_query_payload = normalized.parsed_query.model_dump(mode="json", exclude_none=True)
    async with cl.Step(name="Интерпретация запроса", show_input="json") as step:
        step.input = {"query": message.content}
        step.output = json.dumps(parsed_query_payload, ensure_ascii=False, indent=2)

    primary = select_primary_compound(response)
    inline_elements: list[cl.Element] = []
    sidebar_elements: list[cl.Element] = []
    if primary is not None:
        inline_elements, sidebar_elements = _build_primary_compound_elements(response, primary)

    if normalized.tool_trace:
        async with cl.Step(name="Использованные инструменты", type="tool") as step:
            step.output = build_tool_trace_markdown(response)

    if len(normalized.matches) > 1:
        sidebar_elements.append(
            cl.Text(
                name="candidates",
                content=build_candidates_markdown(normalized.matches[1:]),
                display="side",
            )
        )

    explanation_block = ""
    if normalized.explanation:
        explanation_block = "\n\nПочему результат подходит:\n" + "\n".join(
            f"- {item}" for item in normalized.explanation[:4]
        )
    clarification_block = ""
    if normalized.needs_clarification and normalized.clarification_question:
        clarification_block = f"\n\nУточнение:\n{normalized.clarification_question}"

    # Картинку структуры встраиваем прямо в markdown текста ответа. Так молекула
    # видна ВСЕГДА: и при живом запросе, и при resume истории чата. Иначе она
    # жила только в CustomElement-карточке (CompoundCardV2), а Chainlit не
    # персистит elements без storage client → в истории оставался один текст.
    structure_block = ""
    if primary is not None:
        structure_url = build_structure_image_url(primary.cid)
        structure_block = f"\n\n![Структура {primary.title or f'CID {primary.cid}'}]({structure_url})"

    logger.debug(
        "render: inline=%d sidebar=%d cid=%s",
        len(inline_elements), len(sidebar_elements),
        primary.cid if primary else None,
    )

    await _send_agent_answer(
        f"{normalized.final_answer}{explanation_block}{clarification_block}{structure_block}",
        elements=inline_elements,
    )

    if sidebar_elements:
        sidebar_title = f"Подробности — {primary.title or 'вещество'}" if primary else "Подробности"
        await cl.ElementSidebar.set_title(sidebar_title)
        await cl.ElementSidebar.set_elements(sidebar_elements, key=trace_id)
