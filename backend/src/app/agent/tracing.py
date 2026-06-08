import json
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config import Settings

_TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
logger = logging.getLogger(__name__)


def _to_json_safe(value: Any) -> Any:
    """
    Ensures that a given value is JSON-serializable by converting non-standard types to strings.
    Arguments: value (Any) - The data to be sanitized.
    Return value: Any - A JSON-compatible representation of the input.
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


@dataclass
class ToolTraceEvent:
    """Одно событие tool-trace: вызов MCP-инструмента с результатом/ошибкой."""
    step: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error_message: str | None = None
    duration_ms: float | None = None  # Время ответа MCP-сервера
    transport_type: str = "stdio"


@dataclass
class ToolTraceRecorder:
    """Накопитель событий tool-trace в рамках одного agent-run'а.

    Используется tool-middleware'ом в runtime.py: `start_call` засекает старт
    вызова, `record` — фиксирует завершение с результатом/ошибкой и длительностью.
    """

    events: list[ToolTraceEvent] = field(default_factory=list)
    _start_times: dict[str, float] = field(default_factory=dict, repr=False)

    def start_call(self, tool_name: str) -> None:
        """Засекает время начала вызова MCP-инструмента."""
        self._start_times[tool_name] = time.perf_counter()

    def record(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        transport: str = "stdio"
    ) -> None:
        """
        Logs the execution details of a tool, calculates duration, and stores the event.

        Arguments: tool_name (str), arguments (dict), result (optional dict), error_message (optional str), transport (str).

        Return value: None.

        """
        
        duration = None
        if tool_name in self._start_times:
            duration = (time.perf_counter() - self._start_times.pop(tool_name)) * 1000

        self.events.append(
            ToolTraceEvent(
                step=len(self.events) + 1,
                tool_name=tool_name,
                arguments=_to_json_safe(arguments),
                result=_to_json_safe(result) if result is not None else None,
                error_message=error_message,
                duration_ms=round(duration, 2) if duration is not None else None,
                transport_type=transport
            )
        )


@dataclass
class LangChainTracingConfig:
    """ 
    Data container for LangChain callback handlers and Langfuse metadata.

    Arguments: callbacks (list), metadata (dict), client (optional Langfuse).

    Return value: LangChainTracingConfig instance.
    
    """
    callbacks: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    client: Langfuse | None = None

    def flush(self) -> None:
        """
        Synchronously flushes all queued traces to the Langfuse server.
        Arguments: None.
        Return value: None.

        """
        
        if self.client is None:
            return
        try:
            self.client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed", exc_info=exc)
            return


@lru_cache(maxsize=1)
def _build_langfuse_client(settings_dict: str) -> Langfuse:
    """
    Internal cached helper to initialize a single Langfuse client instance.

    Arguments: settings_dict (str) - JSON string containing keys and environment config.

    Return value: Langfuse - An initialized client.

    """

    s = json.loads(settings_dict)
    return Langfuse(
        public_key=s["pub"],
        secret_key=s["sec"],
        base_url=s["url"],
        environment=s["env"],
    )

def build_langchain_tracing_config(
    settings: Settings,
    *,
    trace_id: str,
    provider: str,
) -> LangChainTracingConfig:
    
    """Builds a tracing configuration adapted for MCP. Adds architecture tags for filtering in Langfuse."""
    logger.debug("build_langchain_tracing_config: trace_id=%s provider=%s", trace_id, provider)
    metadata = {
        "langfuse_tags": ["pubchem-agent","mcp-architecture", provider],
        "agent_provider": provider,
        "app_trace_id": trace_id,
        "architecture": "mcp"
    }

    pub_key = settings.langfuse_public_key.get_secret_value() if settings.langfuse_public_key else None
    sec_key = settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else None

    if not pub_key or not sec_key:
        return LangChainTracingConfig(metadata = metadata)
    
    s_dict = json.dumps({
        "pub": pub_key, "sec": sec_key, 
        "url": settings.langfuse_base_url, "env": settings.environment
    })

#клиент
    client = _build_langfuse_client(s_dict)

    trace_context = {"trace_id": trace_id} if _TRACE_ID_PATTERN.fullmatch(trace_id) else None

    handler = CallbackHandler(
        public_key=pub_key,
       # update_trace=True,
        trace_context=trace_context,
    )

    return LangChainTracingConfig(
        callbacks=[handler],
        metadata=metadata,
        client=client,
    )


def build_langfuse_client_from_settings(settings: Settings) -> Langfuse | None:
    """

    Utility to create a Langfuse client directly from the app's settings object.

    Arguments: settings (Settings).

    Return value: Langfuse | None - Initialized client or None if keys are missing.

    """


    public_key = settings.langfuse_public_key.get_secret_value() if settings.langfuse_public_key else None
    secret_key = settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else None

    if not public_key or not secret_key:
        return None
    s_dict = json.dumps({
        "pub": public_key, "sec": secret_key, 
        "url": settings.langfuse_base_url, "env": settings.environment
    })
    return _build_langfuse_client(s_dict)


def record_manual_agent_trace(
    settings: Settings,
    *,
    trace_id: str,
    name: str,
    provider: str,
    model_name: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    
    """
    1. Brief description: Manually exports a complete agent execution trace to Langfuse for non-LangChain sessions.

    2. Arguments: settings, trace_id, name, provider, model_name, input_payload, output_payload, optional metadata.

    3. Return value: None.

    """
    client = build_langfuse_client_from_settings(settings)

    if client is None:
        return

    metadata_payload = dict(metadata or {})
    session_id = metadata_payload.pop("langfuse_session_id", None)
    user_id = metadata_payload.pop("langfuse_user_id", None)
    extra_tags = metadata_payload.pop("langfuse_tags", None)
    trace_tags = ["pubchem-agent", provider]
    if isinstance(extra_tags, list):
        for tag in extra_tags:
            if isinstance(tag, str) and tag not in trace_tags:
                trace_tags.append(tag)

    trace_metadata = {
        "agent_provider": provider,
        "agent_model": model_name,
        "app_trace_id": trace_id,
        **metadata_payload,
    }
    trace_context = {"trace_id": trace_id} if _TRACE_ID_PATTERN.fullmatch(trace_id) else None

    try:
        with client.start_as_current_observation(
            trace_context=trace_context,
            name=name,
            as_type="agent",
            input=_to_json_safe(input_payload),
            output=_to_json_safe(output_payload),
            metadata=_to_json_safe(trace_metadata),
            model=model_name,
        ):
            client.update_current_trace(
                name=name,
                user_id=user_id,
                session_id=session_id,
                input=_to_json_safe(input_payload),
                output=_to_json_safe(output_payload),
                metadata=_to_json_safe(trace_metadata),
                tags=trace_tags,
            )
        client.flush()
    except Exception as exc:
        logger.warning("Manual Langfuse trace export failed", exc_info=exc)
        return
