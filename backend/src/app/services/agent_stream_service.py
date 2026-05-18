from collections.abc import Callable
import asyncio
from typing import Any
import uuid

from app.adapter.pubchem_adapter import PubChemAdapter
from app.agent.error_mapper import normalize_agent_exception
from app.agent.meta import build_capability_response, is_capability_question
from app.agent.model_factory import resolve_provider_model_name
from app.agent.runtime import PreparedAgentRuntime, prepare_agent_runtime
from app.agent.tracing import record_manual_agent_trace
from app.config import Settings
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.schemas.agent import AgentRequest, AgentResponseEnvelope, AgentToolTraceEntry
from app.services.agent_service import build_agent_response_envelope
import logging
logger = logging.getLogger(__name__)

class AgentStreamService:
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
        extra_callbacks: list[Any] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> AgentResponseEnvelope:
        
        resolved_trace_id = trace_id or uuid.uuid4().hex

        if is_capability_question(request.text):
            provider_name, model_name = resolve_provider_model_name(self.settings, request.provider)
            response = build_capability_response(
                trace_id=resolved_trace_id,
                request_text=request.text,
                provider=provider_name,
                model_name=model_name,
            )
            self.manual_trace_recorder(
                self.settings,
                trace_id=resolved_trace_id,
                name="pubchem-agent-capabilities",
                provider=provider_name,
                model_name=model_name,
                input_payload={
                    "text": request.text,
                    "provider": provider_name,
                },
                output_payload=response.model_dump(mode="json"),
                metadata=metadata_overrides,
            )
            return response
        logger.info(f"--- [AgentService] Инициализация рантайма (trace_id: {resolved_trace_id}) ---")
        async with self.runtime_factory(
            settings=self.settings,
            trace_id=resolved_trace_id,
            mcp_client=self.mcp_client,
            provider=request.provider,
        ) as runtime:
            logger.debug(f"Рантайм создан для провайдера: {request.provider}")
            logger.debug("Сборка конфигурации invoke_config...")

            invoke_config = dict(runtime.invoke_config)
            callbacks = list(invoke_config.get("callbacks", []))
            if extra_callbacks:
                logger.info(f"Добавление {len(extra_callbacks)} дополнительных колбэков (например, Langfuse/Tracer)")
                callbacks.extend(extra_callbacks)

            if callbacks:
                invoke_config["callbacks"] = callbacks
                logger.debug(f"Итоговое количество активных колбэков: {len(callbacks)}")

            metadata = dict(invoke_config.get("metadata", {}))
            if metadata_overrides:
                logger.info(f"Применение оверрайдов метаданных: {list(metadata_overrides.keys())}")
                metadata.update(metadata_overrides)

            logger.info(
                f"--- [AgentService] Конфигурация готова. Модель: {getattr(runtime, 'model_name', 'default')} ---"
            )
            invoke_config["metadata"] = metadata

            try:
                result = await asyncio.wait_for(
                    runtime.agent.ainvoke(
                        {"messages": [{"role": "user", "content": request.text}]},
                        config=invoke_config,
                    ),
                    timeout=max(
                        self.settings.agent_run_timeout_seconds,
                        self.settings.llm_request_timeout_seconds,
                        30.0,
                    ),
                )
                logger.info(f"Агент подключен")

            except Exception as exc:
                logger.error(f"Ошибка подключения агента в agent_stream_service: {exc}", exc_info=True)
                raise normalize_agent_exception(exc) from exc

            finally:
                try:
                    runtime.tracing.flush()
                except Exception as flush_exc:
                    logger.warning(f"Langfuse flush failed (non-fatal): {flush_exc}")

            tool_trace = [
                AgentToolTraceEntry(
                    step=event.step,
                    tool_name=event.tool_name,
                    arguments=event.arguments,
                    result=event.result,
                    error_message=event.error_message,
                )
                for event in runtime.recorder.events
            ]
            return build_agent_response_envelope(
                trace_id=resolved_trace_id,
                request=request,
                runtime=runtime,
                result=result,
                tool_trace=tool_trace,
            )
