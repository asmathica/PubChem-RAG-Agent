from __future__ import annotations

from app.schemas.agent import (
    AgentExecutionInfo,
    AgentNormalizedPayload,
    AgentResponseEnvelope,
    LLMProviderName,
    ParsedAgentQuery,
)
from app.schemas.common import PresentationHints
from typing import Any


_RUSSIAN_MARKERS = (
    "какие инструменты",
    "какие у тебя инструменты",
    "какие у вас инструменты",
    "что ты умеешь",
    "что умеешь",
    "чем ты можешь помочь",
    "какие возможности",
    "покажи инструменты",
    "список инструментов",
)

_ENGLISH_MARKERS = (
    "what tools",
    "which tools",
    "what can you do",
    "your capabilities",
    "available tools",
    "list your tools",
)


def is_capability_question(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(marker in normalized for marker in (*_RUSSIAN_MARKERS, *_ENGLISH_MARKERS))


_STATIC_TOOL_CATALOG = (
    ("search_compound_by_name", "Поиск соединения в PubChem по названию или ключевому слову."),
    ("search_compound_by_smiles", "Поиск по SMILES-структуре."),
    ("search_compound_by_formula", "Поиск по молекулярной формуле."),
    ("search_compound_by_inchikey", "Поиск по InChIKey."),
)


def build_capability_response(
    *,
    trace_id: str,
    request_text: str,
    provider: LLMProviderName,
    model_name: str,
    mcp_tools: list[Any] | None = None,
) -> AgentResponseEnvelope:
    is_russian = any("а" <= char <= "я" or char == "ё" for char in request_text.casefold())

    header = "У меня есть такие инструменты через MCP:" if is_russian else "I have these MCP tools:"

    lines = [header]

    if mcp_tools:
        for tool in mcp_tools:
            description = (tool.description or "").split('\n')[0]
            lines.append(f"- `{tool.name}` — {description}")
    else:
        for name, description in _STATIC_TOOL_CATALOG:
            lines.append(f"- `{name}` — {description}")

    if is_russian:
        lines.extend(
            [
                "",
                "Как я работаю:",
                "1. Сначала выделяю признаки из запроса: название, синоним, SMILES, формулу или диапазон массы.",
                "2. Потом выбираю минимально необходимый инструмент, а не запускаю всё подряд.",
                "3. Если нахожу кандидатов, дозапрашиваю сводку по нужным CID и объясняю, почему результат подходит.",
                "4. Если данных не хватает, сразу задаю один уточняющий вопрос без лишних вызовов PubChem tools.",
            ]
        )
        final_answer = "\n".join(lines)
        intent = "описание возможностей PubChem-агента"
        language = "ru"

    else:
        lines.extend(
            [
                "",
                "How I work:",
                "1. I first extract useful constraints from your request: name, synonym, SMILES, formula, or mass range.",
                "2. Then I choose the minimum necessary tool instead of calling everything at once.",
                "3. If I find good candidates, I fetch summaries for the relevant CIDs and explain why they match.",
                "4. If the request is underspecified, I ask one concise clarification question instead of guessing.",
            ]
        )

        final_answer = "\n".join(lines)
        intent = "describe PubChem agent capabilities"
        language = "en"

    normalized = AgentNormalizedPayload(
        request = AgentExecutionInfo(
            provider=provider,
            model=model_name,
            text=request_text,
        ),

        parsed_query=ParsedAgentQuery(
            intent=intent,
            language=language,
        ),

        final_answer = final_answer,
        explanation = [],
        needs_clarification = False,
        clarification_question = None,
        matches = [],
        compounds = [],
        tool_trace = [],
        referenced_cids = [],
    )

    return AgentResponseEnvelope(
        trace_id=trace_id,
        status="success",
        raw=None,
        normalized=normalized,
        presentation_hints=PresentationHints(
            active_tab="answer",
            available_tabs=["answer", "analysis", "json"],
        ),
        warnings=[],
        error=None,
    )
