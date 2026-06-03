"""
Реконструкция `AgentResponseEnvelope` из LangGraph state.

LangGraph `create_agent(...).ainvoke(...)` возвращает сырой state dict
(`messages`, `structured_response`), а не нашу envelope-модель. Здесь —
все helpers, которые из этого state + tool_trace собирают финальную
структуру для API/UI: final_answer, parsed_query, matches, compounds,
explanation, clarification, warnings.

Используется из `AgentService` и `AgentStreamService` одинаково.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.runtime import PreparedAgentRuntime
from app.schemas.agent import (
    AgentExecutionInfo,
    AgentNormalizedPayload,
    AgentRequest,
    AgentResponseEnvelope,
    AgentToolTraceEntry,
    ParsedAgentQuery,
)
from app.schemas.common import CompoundMatchCard, CompoundOverview, WarningMessage
from app.schemas.query import QueryRequest

# Маппинг MCP-tool name → input_mode для реконструкции `parsed_query`.
# Имена СИНХРОНИЗИРОВАНЫ с реальными MCP tools (app/agent/mcp_tools/*).
# Раньше тут были устаревшие имена `search_by_name_pubchem` и т.п. — после
# переименования tools на стороне Арины этот маппинг остался pre-existing
# broken: input_mode никогда не заполнялся, explanation был пустым.
MCP_LOOKUP_MAP = {
    "search_compound_by_name": "name",
    "search_compound_by_smiles": "smiles",
    "search_compound_by_formula": "formula",
    "search_compound_by_inchikey": "inchikey",
    "search_by_similar_mol_pubchem": "smiles_similar",
    "search_substructure_pubchem": "smiles_substructure",
}

# Placeholder из _fallback_answer — выносим в константу чтобы сравнивать
# через `==` (раньше было `.startswith(...)` по магической строке — хрупко).
_NO_ANSWER_PLACEHOLDER = "Агент завершил работу, но не сформировал отдельный текстовый ответ."


# ─── final_answer helpers ──────────────────────────────────────────────────


def _fallback_answer(result: dict[str, Any]) -> str:
    """Берёт последний непустой AIMessage из state. Если такого нет — placeholder."""
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            if message.content.strip():
                return message.content.strip()
    return _NO_ANSWER_PLACEHOLDER


def _contains_cyrillic(text: str) -> bool:
    """True если в строке есть кириллица. Диапазон U+0400-U+04FF покрывает
    все кириллические буквы (заглавные/строчные/ё), без необходимости casefold."""
    return any("Ѐ" <= char <= "ӿ" for char in text)


def _fallback_compound_answer(
    request_text: str,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> str:
    """Формирует короткое описание найденного вещества на языке запроса.
    Используется когда LLM вернул пустой/generic-ответ, но tool_trace
    содержит реальные данные из PubChem."""
    is_russian = _contains_cyrillic(request_text)
    primary_compound = compounds[0] if compounds else None
    primary_match = matches[0] if matches else None

    if primary_compound is not None:
        title = primary_compound.title or f"CID {primary_compound.cid}"
        formula = primary_compound.molecular_formula or "—"
        weight = primary_compound.molecular_weight
        if is_russian:
            weight_block = f", молекулярная масса {weight:.4f} г/моль" if weight is not None else ""
            return (
                f"Наиболее подходящее вещество в PubChem — {title} (CID {primary_compound.cid}). "
                f"Формула: {formula}{weight_block}."
            )
        weight_block = f", molecular weight {weight:.4f} g/mol" if weight is not None else ""
        return f"The best PubChem match is {title} (CID {primary_compound.cid}). Formula: {formula}{weight_block}."

    if primary_match is not None:
        title = primary_match.title or f"CID {primary_match.cid}"
        formula = primary_match.molecular_formula or "—"
        if is_russian:
            return f"Наиболее подходящий кандидат в PubChem — {title} (CID {primary_match.cid}). Формула: {formula}."
        return f"The best PubChem candidate is {title} (CID {primary_match.cid}). Formula: {formula}."

    if is_russian:
        return "Мне не удалось уверенно подобрать вещество по текущему запросу."
    return "I could not confidently identify a matching compound for the current request."


# ─── parsed_query / explanation / clarification reconstruction ─────────────


def _infer_parsed_query(request_text: str, tool_trace: list[AgentToolTraceEntry]) -> ParsedAgentQuery:
    """Восстанавливает структуру запроса (input_mode + identifier) из первого
    распознанного MCP tool-call'а в tool_trace."""
    language = "ru" if _contains_cyrillic(request_text) else "en"
    target_event = next((e for e in tool_trace if e.tool_name in MCP_LOOKUP_MAP), None)

    query_obj: QueryRequest | None = None
    if target_event is not None:
        input_mode = MCP_LOOKUP_MAP[target_event.tool_name]
        # MCP-tools принимают аргумент с именем = input_mode ("name", "smiles",
        # "formula", "inchikey"), а не "identifier".
        identifier = (
            target_event.arguments.get(input_mode)
            or target_event.arguments.get("identifier")
            or ""
        )
        query_obj = QueryRequest(
            input_mode=input_mode,
            identifier=identifier,
            limit=target_event.arguments.get("limit", 10),
        )

    return ParsedAgentQuery(
        intent="Scientific chemical lookup via MCP tools",
        language=language,
        query=query_obj,
    )


def _infer_clarification(
    final_answer: str,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> tuple[bool, str | None]:
    """Эвристика: если агент задал вопрос вместо ответа — это clarification.
    Возвращает (флаг_нужно_уточнить, текст_уточняющего_вопроса)."""
    lowered = final_answer.casefold()
    clarification_markers = (
        "уточ", "укажите", "какой именно",
        "please clarify", "could you clarify", "can you clarify",
        "please specify", "which one do you mean",
    )
    needs_clarification = not matches and not compounds and (
        final_answer.strip().endswith("?")
        or any(marker in lowered for marker in clarification_markers)
    )
    return needs_clarification, final_answer if needs_clarification else None


# Шаблоны строк explanation, по input_mode и языку (ru, en).
_EXPLANATION_TEMPLATES: dict[str, tuple[str, str]] = {
    "name":     ("Запрос интерпретирован как поиск по названию: {id}.",
                 "The request was interpreted as a name search: {id}."),
    "smiles":   ("Использована химическая структура (SMILES): {id}.",
                 "The chemical structure (SMILES) was used: {id}."),
    "formula":  ("Поиск выполнен по молекулярной формуле: {id}.",
                 "The search was performed by molecular formula: {id}."),
    "cid":      ("Запрос выполнен по прямому идентификатору PubChem CID: {id}.",
                 "The query was executed by direct PubChem CID: {id}."),
    "inchikey": ("Поиск по InChIKey: {id}.",
                 "Search by InChIKey: {id}."),
}


def _infer_explanation(
    request_text: str,
    *,
    parsed_query: ParsedAgentQuery,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
    needs_clarification: bool,
) -> list[str]:
    """Восстановление логики «почему агент ответил именно так» — для UI."""
    if needs_clarification or parsed_query.query is None:
        return []

    is_russian = _contains_cyrillic(request_text)
    mode = parsed_query.query.input_mode
    identifier = parsed_query.query.identifier
    explanation: list[str] = []

    template = _EXPLANATION_TEMPLATES.get(mode)
    if template is not None:
        ru, en = template
        explanation.append((ru if is_russian else en).format(id=identifier))

    primary = compounds[0] if compounds else None
    if primary is not None:
        title = primary.title or f"CID {primary.cid}"
        formula = primary.molecular_formula or "—"
        if is_russian:
            explanation.append(f"Итоговый кандидат — {title} (CID {primary.cid}) с формулой {formula}.")
        else:
            explanation.append(f"The selected candidate is {title} (CID {primary.cid}) with formula {formula}.")
    elif matches:
        title = matches[0].title or f"CID {matches[0].cid}"
        if is_russian:
            explanation.append(f"PubChem вернул кандидат {title} (CID {matches[0].cid}) как лучший доступный матч.")
        else:
            explanation.append(f"PubChem returned {title} (CID {matches[0].cid}) as the best available match.")

    # Дедупликация с сохранением порядка, top-4.
    return list(OrderedDict.fromkeys(explanation))[:4]


def _collect_referenced_cids(
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> list[int]:
    """Собирает все CID'ы, упомянутые в matches/compounds, без дубликатов и в порядке появления."""
    seen: OrderedDict[int, None] = OrderedDict()
    for compound in compounds:
        seen.setdefault(compound.cid, None)
    for match in matches:
        seen.setdefault(match.cid, None)
    return list(seen.keys())


# ─── extraction of matches/compounds from tool_trace ────────────────────────


def _parse_event_payload(event: AgentToolTraceEntry) -> dict[str, Any] | None:
    """Парсит JSON payload из tool-event'а в dict или возвращает None при ошибке."""
    raw = event.result
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    if isinstance(raw, dict):
        return raw
    return None


def _collect_compounds(
    tool_trace: list[AgentToolTraceEntry],
) -> tuple[list[CompoundMatchCard], list[CompoundOverview]]:
    """Парсит tool_trace, валидирует JSON через Pydantic, дедуплицирует по CID.

    Возвращает (matches, compounds) — два списка без дубликатов, в порядке
    появления в trace.
    """
    match_map: OrderedDict[int, CompoundMatchCard] = OrderedDict()
    compound_map: OrderedDict[int, CompoundOverview] = OrderedDict()

    for event in tool_trace:
        result_data = _parse_event_payload(event)
        if result_data is None or not result_data.get("ok", False):
            continue

        # 1. Массив matches.
        for match in result_data.get("matches") or []:
            try:
                validated = CompoundMatchCard.model_validate(match)
                match_map.setdefault(validated.cid, validated)
            except ValidationError:
                continue

        # 2. Одиночный compound (CompoundOverview).
        compound = result_data.get("compound")
        if compound is not None:
            try:
                validated_overview = CompoundOverview.model_validate(compound)
                compound_map.setdefault(validated_overview.cid, validated_overview)
            except ValidationError:
                pass

        # 3. Standalone CID на верхнем уровне (get_by_cid и подобные).
        cid_val = result_data.get("cid")
        if cid_val is not None:
            try:
                cid_int = int(cid_val)
            except (TypeError, ValueError):
                continue
            if cid_int not in match_map:
                match_map[cid_int] = CompoundMatchCard(
                    cid=cid_int,
                    title=result_data.get("resolved_title") or f"CID {cid_int}",
                    molecular_formula=result_data.get("molecular_formula"),
                    molecular_weight=result_data.get("molecular_weight"),
                )

    return list(match_map.values()), list(compound_map.values())


def _build_warnings(normalized: AgentNormalizedPayload) -> list[WarningMessage]:
    """Диагностика для UI: что пошло не так в этом запросе (если что-то)."""
    warnings: list[WarningMessage] = []
    if normalized.needs_clarification:
        warnings.append(WarningMessage(
            code="NEEDS_CLARIFICATION",
            message="Запрос требует уточнения перед надёжным поиском в PubChem.",
        ))
    if not normalized.tool_trace:
        warnings.append(WarningMessage(
            code="NO_TOOL_USAGE",
            message="Агент не вызвал PubChem tools. Ответ мог остановиться на этапе уточнения.",
        ))
    return warnings


# ─── main entry point ──────────────────────────────────────────────────────


def build_agent_response_envelope(
    trace_id: str,
    request: AgentRequest,
    runtime: PreparedAgentRuntime,
    result: dict[str, Any],
    tool_trace: list[AgentToolTraceEntry],
) -> AgentResponseEnvelope:
    """Финальная сборка envelope из сырого LangGraph state.

    Алгоритм:
    1. extract `matches`/`compounds` из tool_trace
    2. final_answer = последний AIMessage; если пустой и есть данные —
       подменяем на fallback_compound_answer
    3. восстанавливаем parsed_query из первого распознанного tool-call'а
    4. clarification — эвристика по тексту final_answer
    5. explanation — шаблоны по input_mode + языку
    6. warnings — диагностика для UI
    """
    execution_info = AgentExecutionInfo(
        provider=runtime.provider,
        model=runtime.model_name,
        text=request.text,
    )

    matches, compounds = _collect_compounds(tool_trace)

    final_answer = _fallback_answer(result)
    # Если LLM не дал свой текст (placeholder), но в trace есть compound'ы —
    # синтезируем короткий ответ из данных PubChem.
    if final_answer == _NO_ANSWER_PLACEHOLDER and (matches or compounds):
        final_answer = _fallback_compound_answer(request.text, matches, compounds)

    parsed_query = _infer_parsed_query(request.text, tool_trace)
    needs_clarification, clarification_question = _infer_clarification(
        final_answer, matches, compounds,
    )
    explanation = _infer_explanation(
        request.text,
        parsed_query=parsed_query,
        matches=matches,
        compounds=compounds,
        needs_clarification=needs_clarification,
    )

    normalized = AgentNormalizedPayload(
        request=execution_info,
        parsed_query=parsed_query,
        final_answer=final_answer,
        explanation=explanation,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        matches=matches,
        compounds=compounds,
        tool_trace=tool_trace,
        referenced_cids=_collect_referenced_cids(matches, compounds),
    )

    raw_payload: dict[str, Any] | None = None
    if request.include_raw and isinstance(result, dict):
        raw_payload = {
            "message_count": len(result.get("messages", [])),
            "tool_call_count": len(tool_trace),
            "structured_response": result.get("structured_response"),
        }

    return AgentResponseEnvelope(
        trace_id=trace_id,
        status="success",
        normalized=normalized,
        raw=raw_payload,
        warnings=_build_warnings(normalized),
    )
