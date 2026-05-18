"""
MODULE: AI Agent Runtime Orchestrator
-------------------------------------
PURPOSE:
Responsible for assembling and configuring the AI agent lifecycle. Acts as an MCP client, connecting the language model (LLM) to the tool server.

MAIN FUNCTIONS:
- Initialization and connection to remote MCP tool servers.
- Configuring "circuit breakers" (Middleware): loop protection and step limits.
- Configuring the monitoring system (Tracing) for debugging reasoning chains.
- Assembling the final agent object, ready to execute user tasks.

This file separates the infrastructure startup logic from the implementation of the tools themselves.
"""
import json, logging
from dataclasses import dataclass
from typing import Any
from contextlib import asynccontextmanager
from langchain_mcp_adapters.client import MultiServerMCPClient

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware, wrap_tool_call
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.types import Command


from app.agent.model_factory import build_chat_model
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tracing import LangChainTracingConfig, ToolTraceRecorder, build_langchain_tracing_config
from app.config import Settings
from app.schemas.agent import LLMProviderName


def _build_tool_trace_recorder_middleware(recorder: ToolTraceRecorder) -> Any:
    """Middleware that writes every MCP tool invocation into the ToolTraceRecorder.

    Sits as the OUTERMOST tool-call middleware so it observes both real handler
    responses AND short-circuit ToolMessages produced by inner middleware
    (e.g. duplicate-call guard). Captures call name, arguments, parsed JSON
    result, and any exception or PubChem-style ``ok=False`` payload.
    """

    @wrap_tool_call(name="record_tool_invocations")
    async def record_tool_invocations(request, handler):  # noqa: ANN001
        tool_name = request.tool_call["name"]
        arguments = request.tool_call.get("args", {}) or {}
        recorder.start_call(tool_name)
        try:
            response = await handler(request)
        except Exception as exc:
            recorder.record(
                tool_name=tool_name,
                arguments=arguments,
                error_message=str(exc),
            )
            raise

        if isinstance(response, Command):
            recorder.record(tool_name=tool_name, arguments=arguments)
            return response

        result: dict[str, Any] | None = None
        error_message: str | None = None
        content = getattr(response, "content", None)

        def _parse_text_payload(text: str) -> dict[str, Any]:
            try:
                parsed = json.loads(text)
            except ValueError:
                return {"text": text}
            return parsed if isinstance(parsed, dict) else {"value": parsed}

        if isinstance(content, str):
            result = _parse_text_payload(content)
        elif isinstance(content, dict):
            result = content
        elif isinstance(content, list):
            text_chunks: list[str] = []
            for chunk in content:
                if isinstance(chunk, str):
                    text_chunks.append(chunk)
                elif isinstance(chunk, dict) and chunk.get("type") == "text":
                    text_value = chunk.get("text", "")
                    if isinstance(text_value, str):
                        text_chunks.append(text_value)
            joined = "".join(text_chunks)
            if joined:
                result = _parse_text_payload(joined)

        if isinstance(result, dict):
            if getattr(response, "status", None) == "error" or result.get("ok") is False:
                error_payload = result.get("error") or result.get("message")
                if isinstance(error_payload, dict):
                    error_message = error_payload.get("message")
                elif isinstance(error_payload, str):
                    error_message = error_payload

        recorder.record(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            error_message=error_message,
        )
        return response

    return record_tool_invocations
import logging
logger = logging.getLogger(__name__)


@dataclass
class PreparedAgentRuntime:
    agent: Any
    recorder: ToolTraceRecorder
    invoke_config: dict[str, Any]
    provider: LLMProviderName
    model_name: str
    tracing: LangChainTracingConfig
    mcp_client: MultiServerMCPClient

def _build_duplicate_tool_call_guard() -> Any:

    """The mechanism intercepts tool calls and checks whether an identical call (name + arguments) has been executed previously.
        If a duplicate is detected, tool execution is blocked,
        and the agent is instructed to use the results of the previous call.
        Returns:
        Callable: Middleware-функция для LangChain агента.
        """
    seen_signatures: set[str] = set()

    @wrap_tool_call(name="deduplicate_pubchem_tool_calls")
    async def deduplicate_pubchem_tool_calls(request, handler):  # noqa: ANN001
        signature = json.dumps(
            {
                "name": request.tool_call["name"],
                "args": request.tool_call.get("args", {}),
            },
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
                            "message": "The same PubChem tool call was already executed in this run. Reuse the previous result or answer the user directly.",
                            "retriable": False,
                            "details": None,
                        },
                    },
                    ensure_ascii=False,
                ),
                name = request.tool_call["name"],
                tool_call_id = request.tool_call["id"],
                status = "error",
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
): #-> PreparedAgentRuntime:
    """
    Initializes and assembles the AI ​​agent's runtime environment, configuring connections to MCP servers, language model (LLM) parameters, 
    loop protection, and tracing configuration. This is the central hub that transforms disparate components into a ready-to-run agent instance.
    Args: 
        settings (Settings): A global application settings object containing agent step limits, API connection parameters, provider keys, and paths to MCP scripts.

        trace_id (str): A unique trace session identifier used for monitoring agent operation and debugging call chains in LangSmith or other logging systems.
    
    Return:

    PreparedAgentRuntime: A data class (container) containing:

        agent: A constructed agent object with attached MCP tools.
        recorder: A tool for recording execution logs.
        invoke_config: Invocation settings (recursion limits, callback functions).
        provider/model_name: Metadata about the neural network used.
        tracing: Configuration for the monitoring system. 
    """
    async with mcp_client.session("pubchem") as session:

      mcp_tools = await load_mcp_tools(session)
      resolved_model = build_chat_model(settings, provider=provider)
      recorder = ToolTraceRecorder()

      middleware = [
        _build_tool_trace_recorder_middleware(recorder),
        _build_duplicate_tool_call_guard(),
        ToolCallLimitMiddleware(run_limit=max(5, settings.agent_max_steps)),
    ]

      tracing = build_langchain_tracing_config(
        settings,
        trace_id=trace_id,
        provider=resolved_model.provider,
    )

      agent = create_agent(
        model=resolved_model.instance,
        tools=mcp_tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
    )

      invoke_config: dict[str, Any] = {
        "recursion_limit": max(8, settings.agent_max_steps * 2 + 2),
        "metadata": tracing.metadata,
        "max_concurrency": 1,
        "configurable": {
        "thread_id": trace_id, # Важно для изоляции сессий
    }
    }
    
      if tracing.callbacks:
        invoke_config["callbacks"] = tracing.callbacks
        logger.info(" callbacks переданы langfuse")

      yield PreparedAgentRuntime(
        agent = agent,
        recorder = recorder,
        invoke_config = invoke_config,
        provider = resolved_model.provider,
        model_name = resolved_model.model_name,
        tracing = tracing,
        mcp_client=mcp_client
    )
