"""
Схемы агента: контракт данных между UI/HTTP, ядром агента и MCP-сервером.

Pydantic-модели для валидации входящего запроса (`AgentRequest`), описания
разобранного запроса (`ParsedAgentQuery`), строгого формата ответа LLM
(`AgentFinalStructuredResponse`) и нормализованного payload'а для фронтенда
(`AgentNormalizedPayload` внутри `AgentResponseEnvelope`). Финальный envelope
собирается из сырого state LangGraph в `app.services.envelope_builder`.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import CompoundMatchCard, CompoundOverview, ErrorPayload, PresentationHints, WarningMessage
from app.schemas.query import QueryRequest

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
