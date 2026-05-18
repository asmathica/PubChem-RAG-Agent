"""
MODULE: PubChem Agent Schemas & Execution Logic
---------------------------------------------
PURPOSE:
Defines the data architecture and message exchange protocols for the AI agent

This file contains Pydantic models for validating incoming requests, structuring neural network responses, and tracing tool invocations.

MAIN COMPONENTS:
- AgentRequest: Validates incoming text and provider parameters.
- ParsedAgentQuery: Schema for understanding user intent (name, SMILES, formula).
- AgentFinalStructuredResponse: Strict LLM output format (response, rationale, CIDs).
- AgentNormalizedPayload: Assembles final data (search results + analytics).
- Agent_ (Class): Internal logic for invoking tools via the MCP client and maintaining a history of steps (trace).

This file provides typing and a "contract" between the frontend, agent, and MCP server.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import CompoundMatchCard, CompoundOverview, ErrorPayload, PresentationHints, WarningMessage
from app.schemas.query import QueryRequest


import json
LLMProviderName = Literal["openai", "modal_glm", "ollama", "gemini", "openrouter", "nvidia", "mistral"]


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, description="Natural-language PubChem request from the user.")
    provider: LLMProviderName | None = Field(default=None, description="Optional provider override for the agent.")
    include_raw: bool = Field(default=True, description="Include compact raw debugging payload in the response.")

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class ParsedMassRange(BaseModel):
    min_mass: float
    max_mass: float
    mass_type: Literal["molecular_weight", "exact_mass", "monoisotopic_mass"] = "molecular_weight"


class ParsedAgentQuery(BaseModel):
    model_config = ConfigDict(extra = "forbid")

    intent: str = Field(description="Short description of what the user is trying to do.")
    language: str | None = Field(default=None, description="Language the user appears to be using.")
#новый тип 
    query: QueryRequest | None = Field(
        default=None, 
        description="The structured search query to be executed."
    )
    mass_range: ParsedMassRange | None = Field(default=None, description="Mass constraint if present.")
    requested_limit: int | None = Field(default=None, ge=1, le=20, description="Number of results the user seems to want.")


class AgentFinalStructuredResponse(BaseModel):
    """Финальный ответ, который агент отдает пользователю."""
    model_config = ConfigDict(extra="forbid")

    final_answer: str = Field(description="User-facing answer grounded only in tool results.")
    explanation: list[str] = Field(
        default_factory=list,
        description="Short bullet-like reasons explaining why the selected result matches the request.",
    )
    needs_clarification: bool = Field(
        default=False,
        description="Set to true when the request is too ambiguous or underspecified for a safe lookup.",
    )
    clarification_question: str | None = Field(
        default=None,
        description="One concise clarification question to ask when needs_clarification is true.",
    )
    parsed_query: ParsedAgentQuery
    referenced_cids: list[int] = Field(
        default_factory=list,
        description="CIDs referenced in the final answer or used as the main candidates.",
    )


class AgentExecutionInfo(BaseModel):
    provider: LLMProviderName
    model: str
    text: str


class AgentToolTraceEntry(BaseModel):
    step: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_message: str | None = None


class AgentNormalizedPayload(BaseModel):
    """ нормализация данных для фронтенда"""

    request: AgentExecutionInfo
    parsed_query: ParsedAgentQuery
    final_answer: str
    explanation: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    matches: list[CompoundMatchCard] = Field(default_factory=list)
    compounds: list[CompoundOverview] = Field(default_factory=list)
    tool_trace: list[AgentToolTraceEntry] = Field(default_factory=list)
    referenced_cids: list[int] = Field(default_factory=list)


class AgentResponseEnvelope(BaseModel):
    trace_id: str
   # source: Literal["langchain-agent"] = "langchain-agent"
    status: Literal["success", "error"] = "success"
    raw: dict[str, Any] | None = None
    normalized: AgentNormalizedPayload | None = None

    presentation_hints: PresentationHints = Field(
        default_factory=lambda: PresentationHints(
            active_tab="answer",
            available_tabs=["answer", "compounds", "analysis", "tools", "json"],
        )
    )
    warnings: list[WarningMessage] = Field(default_factory=list)
    error: ErrorPayload | None = None

    class Agent_:

        """
            This agent doesn't implement the tools itself - it calls the existing
            MCP server tools (search_by_name_pubchem, search_by_smiles_pubchem, etc.)
        """

        def __init__(self, mcp_client, llm_provider: str = "openai", model: str = "gpt-4o-mini"):
            self.mcp_client = mcp_client
            self.llm_provider = llm_provider
            self.model = model
            self.tool_trace: list[AgentToolTraceEntry] = []
            self.current_step = 0
            
        def _add_trace(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any] | None = None, error: str | None = None):

            """Add entry to tool trace"""

            self.current_step += 1
            self.tool_trace.append(AgentToolTraceEntry(
            step=self.current_step,
            tool_name = tool_name,
            arguments = arguments,
            result = result,
            error_message = error
        ))
            
#вызов тулов
        async def _call_mcp_tool(self, tool_name: str, **kwargs) -> dict[str, Any]:
            """
            Call an MCP tool and parse its JSON response.
        
            Args:
                tool_name: Name of the MCP tool (e.g., "search_by_name_pubchem")
                **kwargs: Arguments for the tool
            
            Returns:
            Parsed JSON response as dict
        """
            result = await self.mcp_client.call_tool(tool_name, kwargs)
        
            if isinstance(result, str):
                return json.loads(result)
            return result
