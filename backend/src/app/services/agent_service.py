"""
AgentService — единая точка входа в LangChain агента (HTTP и Chainlit).

Тонкая обёртка над `prepare_agent_runtime`:
1. Если вопрос про возможности агента — отдаём статичный ответ без LLM.
2. Иначе открываем runtime, дёргаем `agent.ainvoke(...)` с таймаутом,
   собираем envelope через `build_agent_response_envelope`.

Параметры `extra_callbacks` и `metadata_overrides` нужны для Chainlit,
который прокидывает свои Langfuse session/user ID и tags. HTTP-роут
(`/api/agent`) их не использует.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.agent.error_mapper import normalize_agent_exception
from app.agent.meta import build_capability_response, is_capability_question
from app.agent.model_factory import resolve_provider_model_name
from app.agent.runtime import PreparedAgentRuntime, prepare_agent_runtime
from app.agent.tracing import record_manual_agent_trace
from app.config import Settings
from app.schemas.agent import AgentRequest, AgentResponseEnvelope, AgentToolTraceEntry
from app.services.envelope_builder import build_agent_response_envelope

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        settings: Settings,
        *,
        mcp_client: MultiServerMCPClient,
        runtime_factory: Callable[..., PreparedAgentRuntime] = prepare_agent_runtime,
        manual_trace_recorder: Callable[..., None] = record_manual_agent_trace,
    ) -> None:
        self.settings = settings
        self.mcp_client = mcp_client
        self.runtime_factory = runtime_factory
        self.manual_trace_recorder = manual_trace_recorder

    async def execute(
        self,
        request: AgentRequest,
        *,
        trace_id: str | None = None,
        session_id: str | None = None,
        extra_callbacks: list[Any] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> AgentResponseEnvelope:
        """Выполняет один полный agent-cycle.

        Args:
            request: текст вопроса + опциональный provider override.
            trace_id: per-request ID для observability (Langfuse).
            session_id: per-conversation ID для checkpointer'а памяти.
            extra_callbacks: доп. LangChain callbacks (например, Chainlit tracer).
            metadata_overrides: доп. ключи в metadata invoke_config
                (например, langfuse_session_id, langfuse_tags).
        """
        resolved_trace_id = trace_id or uuid.uuid4().hex

        # Короткий путь — без LLM, отдаём статичный capability ответ.
        if is_capability_question(request.text):
            return self._handle_capability_question(request, resolved_trace_id, metadata_overrides)

        async with self.runtime_factory(
            settings=self.settings,
            trace_id=resolved_trace_id,
            mcp_client=self.mcp_client,
            provider=request.provider,
            session_id=session_id,
        ) as runtime:
            invoke_config = _augment_invoke_config(
                runtime.invoke_config,
                extra_callbacks=extra_callbacks,
                metadata_overrides=metadata_overrides,
            )
            logger.info(
                "Agent runtime ready: trace_id=%s model=%s",
                resolved_trace_id, runtime.model_name,
            )

            try:
                result = await asyncio.wait_for(
                    runtime.agent.ainvoke(
                        {"messages": [{"role": "user", "content": request.text}]},
                        config=invoke_config,
                    ),
                    timeout=max(
                        self.settings.agent_run_timeout_seconds,
                        self.settings.llm_request_timeout_seconds,
                    ),
                )
            except Exception as exc:
                # Все ошибки агента (timeout, rate limit, GraphRecursionError, ...)
                # маппятся в AppError единым нормализатором.
                logger.error("Agent execution failed: %s", exc, exc_info=True)
                raise normalize_agent_exception(exc) from exc
            finally:
                # Любой исход — flush Langfuse, иначе спаны теряются если
                # процесс упадёт между вызовами.
                try:
                    runtime.tracing.flush()
                except Exception as flush_exc:
                    logger.warning("Langfuse flush failed (non-fatal): %s", flush_exc)

            return build_agent_response_envelope(
                trace_id=resolved_trace_id,
                request=request,
                runtime=runtime,
                result=result,
                tool_trace=_build_tool_trace(runtime),
            )

    def _handle_capability_question(
        self,
        request: AgentRequest,
        trace_id: str,
        metadata_overrides: dict[str, Any] | None,
    ) -> AgentResponseEnvelope:
        """Статичный ответ для вопросов «что ты умеешь?» — без LLM-call'а."""
        provider_name, model_name = resolve_provider_model_name(self.settings, request.provider)
        response = build_capability_response(
            trace_id=trace_id,
            request_text=request.text,
            provider=provider_name,
            model_name=model_name,
        )
        self.manual_trace_recorder(
            self.settings,
            trace_id=trace_id,
            name="pubchem-agent-capabilities",
            provider=provider_name,
            model_name=model_name,
            input_payload={"text": request.text, "provider": provider_name},
            output_payload=response.model_dump(mode="json"),
            metadata=metadata_overrides,
        )
        return response


def _augment_invoke_config(
    base: dict[str, Any],
    *,
    extra_callbacks: list[Any] | None,
    metadata_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Возвращает копию base invoke_config с добавленными callbacks/metadata."""
    config = dict(base)
    if extra_callbacks:
        config["callbacks"] = [*config.get("callbacks", []), *extra_callbacks]
    if metadata_overrides:
        config["metadata"] = {**config.get("metadata", {}), **metadata_overrides}
    return config


def _build_tool_trace(runtime: PreparedAgentRuntime) -> list[AgentToolTraceEntry]:
    """ToolTraceRecorder events → AgentToolTraceEntry для envelope."""
    return [
        AgentToolTraceEntry(
            step=event.step,
            tool_name=event.tool_name,
            arguments=event.arguments,
            result=event.result,
            error_message=event.error_message,
        )
        for event in runtime.recorder.events
    ]
