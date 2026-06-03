"""
Сборка runtime'а LangGraph-агента: model + MCP tools + middleware + checkpointer.

Главное:
- `prepare_agent_runtime(...)` — async context manager. Открывает MCP-сессию,
  собирает агент через `create_agent(...)`, отдаёт готовый `PreparedAgentRuntime`.
- Middleware-стек (в порядке вложенности):
    1. tool-trace recorder        — пишет каждый tool-call в ToolTraceRecorder
    2. duplicate-call guard       — блокирует повторный tool-call с теми же args
    3. ToolCallLimitMiddleware    — hard limit на число tool-вызовов за run
    4. ContextEditingMiddleware   — дропает старые ToolMessages при >60k токенов
- Checkpointer (LangGraph state per `thread_id`) — singleton через persistence.py.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ToolCallLimitMiddleware,
    wrap_tool_call,
)
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.types import Command

from app.agent.model_factory import build_chat_model
from app.agent.persistence import get_checkpointer
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tracing import (
    LangChainTracingConfig,
    ToolTraceRecorder,
    build_langchain_tracing_config,
)
from app.config import Settings
from app.schemas.agent import LLMProviderName

logger = logging.getLogger(__name__)


@dataclass
class PreparedAgentRuntime:
    """Готовый к запуску агент + всё что нужно для одного invoke."""

    agent: Any
    recorder: ToolTraceRecorder
    invoke_config: dict[str, Any]
    provider: LLMProviderName
    model_name: str
    tracing: LangChainTracingConfig
    mcp_client: MultiServerMCPClient


def _build_tool_trace_recorder_middleware(recorder: ToolTraceRecorder) -> Any:
    """Пишет каждый MCP tool-вызов в ToolTraceRecorder.

    Стоит САМЫМ ВНЕШНИМ tool-middleware'ом — видит и реальные ответы handler'а,
    и short-circuit ToolMessages от внутренних middleware (напр. duplicate guard).
    Захватывает имя инструмента, аргументы, распарсенный JSON-результат и любую
    ошибку (включая PubChem-style `ok=False`).
    """

    @wrap_tool_call(name="record_tool_invocations")
    async def record_tool_invocations(request, handler):  # noqa: ANN001
        tool_name = request.tool_call["name"]
        arguments = request.tool_call.get("args", {}) or {}
        recorder.start_call(tool_name)
        try:
            response = await handler(request)
        except Exception as exc:
            recorder.record(tool_name=tool_name, arguments=arguments, error_message=str(exc))
            raise

        # Command-ответ (резкий control-flow) — просто пишем факт вызова без payload'а.
        if isinstance(response, Command):
            recorder.record(tool_name=tool_name, arguments=arguments)
            return response

        result = _extract_tool_result_dict(response)
        error_message = _extract_error_message(response, result)

        recorder.record(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            error_message=error_message,
        )
        return response

    return record_tool_invocations


def _extract_tool_result_dict(response: Any) -> dict[str, Any] | None:
    """Парсит content tool-ответа в dict. MCP отдаёт JSON-строку в content[0].text,
    бывает list[ContentItem] или сразу dict — нормализуем к одному виду."""
    content = getattr(response, "content", None)

    def _parse_text(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    if isinstance(content, str):
        return _parse_text(content)
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text_chunks: list[str] = []
        for chunk in content:
            if isinstance(chunk, str):
                text_chunks.append(chunk)
            elif isinstance(chunk, dict) and chunk.get("type") == "text":
                text_value = chunk.get("text", "")
                if isinstance(text_value, str):
                    text_chunks.append(text_value)
        joined = "".join(text_chunks)
        return _parse_text(joined) if joined else None
    return None


def _extract_error_message(response: Any, result: dict[str, Any] | None) -> str | None:
    """Достаёт текст ошибки из PubChem-style payload `{ok: false, error: ...}`."""
    if not isinstance(result, dict):
        return None
    if getattr(response, "status", None) != "error" and result.get("ok") is not False:
        return None
    payload = result.get("error") or result.get("message")
    if isinstance(payload, dict):
        return payload.get("message")
    if isinstance(payload, str):
        return payload
    return None


def _build_duplicate_tool_call_guard() -> Any:
    """Блокирует повторный tool-call с теми же args в рамках одного run'а.

    Сравнивает (name, args) по JSON-сериализации. На повтор отдаёт ToolMessage
    с `ok=False, code=DUPLICATE_TOOL_CALL` — это сигнал агенту "используй
    предыдущий результат, а не дергай API снова".
    """
    seen_signatures: set[str] = set()

    @wrap_tool_call(name="deduplicate_pubchem_tool_calls")
    async def deduplicate_pubchem_tool_calls(request, handler):  # noqa: ANN001
        signature = json.dumps(
            {"name": request.tool_call["name"], "args": request.tool_call.get("args", {})},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if signature in seen_signatures:
            return ToolMessage(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "DUPLICATE_TOOL_CALL",
                            "message": (
                                "The same PubChem tool call was already executed in this run. "
                                "Reuse the previous result or answer the user directly."
                            ),
                            "retriable": False,
                            "details": None,
                        },
                    },
                    ensure_ascii=False,
                ),
                name=request.tool_call["name"],
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        seen_signatures.add(signature)
        return await handler(request)

    return deduplicate_pubchem_tool_calls


@asynccontextmanager
async def prepare_agent_runtime(
    settings: Settings,
    trace_id: str,
    mcp_client: MultiServerMCPClient,
    provider: LLMProviderName | None = None,
    session_id: str | None = None,
):
    """Открывает MCP-сессию и собирает готовый к запуску LangGraph-агент.

    Args:
        settings: глобальная конфигурация (timeouts, ключи, agent_max_steps).
        trace_id: уникальный per-request id для observability (Langfuse).
        mcp_client: singleton MCP-клиент (создаётся в container.py).
        provider: явный выбор LLM-провайдера; None = settings.llm_default_provider.
        session_id: стабильный per-conversation id для LangGraph thread_id
            (чтобы checkpointer подхватил историю). None → fallback на trace_id,
            тогда память живёт только в рамках одного запроса.

    Yields:
        PreparedAgentRuntime — агент + recorder + invoke_config.
    """
    async with mcp_client.session("pubchem") as session:
        mcp_tools = await load_mcp_tools(session)
        resolved_model = build_chat_model(settings, provider=provider)
        recorder = ToolTraceRecorder()

        middleware = [
            _build_tool_trace_recorder_middleware(recorder),
            _build_duplicate_tool_call_guard(),
            ToolCallLimitMiddleware(run_limit=max(5, settings.agent_max_steps)),
            # 60k токенов ≈ половина floor'а 128k (NVIDIA Llama 3.3 70B).
            # При превышении старые ToolMessages дропаются ПЕРЕД LLM-call;
            # checkpointer хранит полную историю, LLM видит trim'нутый view.
            ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=60_000, keep=5)],
            ),
        ]

        tracing = build_langchain_tracing_config(
            settings,
            trace_id=trace_id,
            provider=resolved_model.provider,
        )

        # Singleton checkpointer: AsyncPostgresSaver если задан
        # AGENT_CHECKPOINT_POSTGRES_URL, иначе InMemorySaver.
        checkpointer = await get_checkpointer(settings)

        agent = create_agent(
            model=resolved_model.instance,
            tools=mcp_tools,
            system_prompt=SYSTEM_PROMPT,
            middleware=middleware,
            checkpointer=checkpointer,
        )

        # thread_id ДОЛЖЕН быть стабильным per-conversation, чтобы checkpointer
        # подтянул историю. session_id (Chainlit chat_id или X-Session-Id header)
        # живёт весь чат; trace_id — короткий per-request, для observability.
        conversation_thread_id = session_id or trace_id

        invoke_config: dict[str, Any] = {
            "recursion_limit": max(8, settings.agent_max_steps * 2 + 2),
            "metadata": tracing.metadata,
            "max_concurrency": 1,
            "configurable": {"thread_id": conversation_thread_id},
        }
        if tracing.callbacks:
            invoke_config["callbacks"] = tracing.callbacks
            logger.debug("Langfuse callbacks подключены к invoke_config")

        yield PreparedAgentRuntime(
            agent=agent,
            recorder=recorder,
            invoke_config=invoke_config,
            provider=resolved_model.provider,
            model_name=resolved_model.model_name,
            tracing=tracing,
            mcp_client=mcp_client,
        )
