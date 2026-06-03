"""
AgentService — HTTP entry-point для LangChain агента (POST /api/agent).

Тонкая обёртка над `prepare_agent_runtime`:
1. Если вопрос про возможности агента (is_capability_question) — отдаём
   статичный capability response без вызова LLM.
2. Иначе открываем runtime context, дёргаем `agent.ainvoke(...)` с тайм-аутом,
   собираем envelope через `build_agent_response_envelope`.

Реконструкция envelope живёт в envelope_builder.py — этот модуль остаётся
тонким, всю «сборку ответа» делает один call.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.agent.meta import build_capability_response, is_capability_question
from app.agent.model_factory import resolve_provider_model_name
from app.agent.runtime import PreparedAgentRuntime, prepare_agent_runtime
from app.agent.tracing import record_manual_agent_trace
from app.config import Settings
from app.errors.models import AppError, ErrorCode
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
    ) -> AgentResponseEnvelope:
        resolved_trace_id = trace_id or uuid.uuid4().hex

        # Короткий путь: вопрос про возможности агента — без LLM-вызова.
        if is_capability_question(request.text):
            return self._handle_capability_question(request, resolved_trace_id)

        async with self.runtime_factory(
            settings=self.settings,
            trace_id=resolved_trace_id,
            mcp_client=self.mcp_client,
            provider=request.provider,
            session_id=session_id,
        ) as runtime:
            logger.info("Agent runtime ready: provider=%s", request.provider)
            try:
                result = await asyncio.wait_for(
                    runtime.agent.ainvoke(
                        {"messages": [{"role": "user", "content": request.text}]},
                        config=runtime.invoke_config,
                    ),
                    timeout=max(
                        self.settings.agent_run_timeout_seconds,
                        self.settings.llm_request_timeout_seconds,
                    ),
                )
            except asyncio.TimeoutError as exc:
                logger.error("Agent timed out (limit=%ss)", self.settings.agent_run_timeout_seconds)
                raise AppError(
                    ErrorCode.UPSTREAM_TIMEOUT,
                    "Агент слишком долго думал — попробуйте более конкретный запрос или повторите.",
                    http_status=504,
                    retriable=True,
                ) from exc

            tool_trace = _build_tool_trace(runtime)
            return build_agent_response_envelope(
                trace_id=resolved_trace_id,
                request=request,
                runtime=runtime,
                result=result,
                tool_trace=tool_trace,
            )

    def _handle_capability_question(self, request: AgentRequest, trace_id: str) -> AgentResponseEnvelope:
        """Статичный ответ на вопросы вида «что ты умеешь?»: без LLM-вызова, дёшево."""
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
        )
        return response


def _build_tool_trace(runtime: PreparedAgentRuntime) -> list[AgentToolTraceEntry]:
    """Конвертит ToolTraceRecorder events в наш AgentToolTraceEntry формат для envelope."""
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
