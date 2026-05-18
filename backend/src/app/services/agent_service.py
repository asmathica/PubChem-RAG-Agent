from collections import OrderedDict
from collections.abc import Callable
import asyncio
from typing import Any
import uuid, json
from langchain_core.messages import AIMessage

from app.agent.meta import build_capability_response, is_capability_question
from app.agent.model_factory import resolve_provider_model_name
from app.agent.runtime import PreparedAgentRuntime, prepare_agent_runtime
from app.agent.tracing import record_manual_agent_trace
from app.config import Settings
from app.schemas.agent import (
    AgentExecutionInfo,
    AgentNormalizedPayload,
    AgentRequest,
    AgentResponseEnvelope,
    AgentToolTraceEntry,
    ParsedAgentQuery,
    AgentFinalStructuredResponse,
)
from app.errors.models import AppError, ErrorCode
from app.schemas.common import CompoundMatchCard, CompoundOverview, PresentationHints, WarningMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.schemas.query import QueryRequest
import logging
logger = logging.getLogger(__name__)
MCP_LOOKUP_MAP = {
<<<<<<< HEAD
    "search_by_name_pubchem": "name",
    "search_by_smiles_pubchem": "smiles",
    "get_by_cid": "cid",
    "search_by_formula_pubchem": "formula",
    "search_compound_by_inchikey": "inchikey",
    "search_similar_mol_pubchem": "smiles_similar"
=======
    "search_compound_by_name": "name",
    "search_compound_by_smiles": "smiles",
    "search_compound_by_formula": "formula",
    "search_compound_by_inchikey": "inchikey",
>>>>>>> main
}

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

    async def execute(self, request: AgentRequest, *, trace_id: str | None = None) -> AgentResponseEnvelope:
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
                input_payload={"text": request.text, "provider": provider_name},
                output_payload=response.model_dump(mode="json"),
            )
            return response
        
        async with self.runtime_factory(
            settings=self.settings,
            trace_id=resolved_trace_id,
            mcp_client=self.mcp_client,
            provider=request.provider,
        ) as runtime:
            logger.info(f"--- [AgentService] Runtime создан: provider {request.provider}, настройки: {self.settings}")

            try:
                result = await asyncio.wait_for(
                runtime.agent.ainvoke(
                    {"messages": [{"role": "user", "content": request.text}]},
                    config=runtime.invoke_config,
                    
                ),
                timeout=max(
                    self.settings.agent_run_timeout_seconds,
                    self.settings.llm_request_timeout_seconds,
                    130.0,
                ),
            )
                tool_trace = [
                AgentToolTraceEntry(
                step = event.step,
                tool_name = event.tool_name,
                arguments = event.arguments,
                result = event.result,
                error_message = event.error_message,
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

            except asyncio.TimeoutError:
                logger.error("Агент превысил лимит времени (Timeout)")
                raise AppError(
                    ErrorCode.UPSTREAM_TIMEOUT,
                    "Агент слишком долго думал — попробуйте более конкретный запрос или повторите.",
                    http_status=504,
                    retriable=True,
                )
         
            except Exception as exc:
                logger.error(f"Ошибка во время выполнения агента: {exc}", exc_info=True)
                raise
        



def _fallback_answer(result: dict[str, Any]) -> str:
    """
    "Извлекает текстовый ответ из истории сообщений агента.
    Аргументы:
        result (dict[str, Any]): Словарь с результатами работы агента, содержащий ключ 'messages'.
    Возвращает:
        str: Последнее текстовое сообщение от ИИ или стандартная фраза об отсутствии ответа."
    """
    messages = result.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return "Агент завершил работу, но не сформировал отдельный текстовый ответ."


def _contains_cyrillic(text: str) -> bool:
    """
    "Проверяет наличие символов кириллицы в строке.
    Аргументы:
        text (str): Строка для проверки.
    Возвращает:
        bool: True, если найден хотя бы один кириллический символ, иначе False."
    """
    lowered = text.casefold()#нижний регистр
    return any("а" <= char <= "я" or char == "ё" for char in lowered)


def _fallback_compound_answer(
    request_text: str,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> str:
    """
    "Формирует текстовое описание найденного вещества на основе данных из PubChem.
    
    Выбирает наиболее релевантное соединение и составляет ответ на языке запроса 
    (русском или английском), включая название, CID, формулу и молекулярную массу.

    Аргументы:
        request_text (str): Текст исходного запроса пользователя.
        matches (list[CompoundMatchCard]): Список карточек совпадений.
        compounds (list[CompoundOverview]): Список детальных обзоров соединений.
        
    Возвращает:
        str: Текстовое резюме с информацией о веществе или сообщение о неуспешном поиске."
    """
    primary_compound = compounds[0] if compounds else None
    primary_match = matches[0] if matches else None
    is_russian = _contains_cyrillic(request_text)

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


def _infer_parsed_query(request_text: str, tool_trace: list[AgentToolTraceEntry]) -> ParsedAgentQuery:
    """
    "Восстанавливает структуру поискового запроса на основе истории вызовов инструментов агента.
    
    Анализирует цепочку вызовов (tool_trace), определяет использованный инструмент 
    и извлекает параметры поиска, такие как идентификатор вещества и лимит результатов.

    Аргументы:
        request_text (str): Текст исходного запроса пользователя.
        tool_trace (list[AgentToolTraceEntry]): История вызовов инструментов агентом.
        
    Возвращает:
        ParsedAgentQuery: Объект с метаданными запроса, языком и параметрами поиска."
    """
    language = "ru" if _contains_cyrillic(request_text) else "en"

    #генератор
    target_event = next(
        (e for e in tool_trace if e.tool_name in MCP_LOOKUP_MAP),
        None,
    )

    query_obj = None

    if target_event:
        input_mode = MCP_LOOKUP_MAP[target_event.tool_name]
        # MCP-tools принимают аргумент с именем, совпадающим с input_mode
        # ("name", "smiles", "formula", "inchikey"), а не "identifier".
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
        intent = "Scientific chemical lookup via MCP tools",
        language = language,
        query = query_obj
    )


def _infer_clarification(
    final_answer: str,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> tuple[bool, str | None]:
    
    """Уточнение запроса """

    lowered = final_answer.casefold()
    clarification_markers = (
        "уточ",
        "укажите",
        "какой именно",
        "please clarify",
        "could you clarify",
        "can you clarify",
        "please specify",
        "which one do you mean",
    )
    needs_clarification = not matches and not compounds and (
        final_answer.strip().endswith("?") or any(marker in lowered for marker in clarification_markers)
    )
    return needs_clarification, final_answer if needs_clarification else None


def _collect_referenced_cids(
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
) -> list[int]:
    
    seen: OrderedDict[int, None] = OrderedDict()

    for compound in compounds:
        seen.setdefault(compound.cid, None)

    for match in matches:
        seen.setdefault(match.cid, None)
    return list(seen.keys())


def _infer_explanation(
    request_text: str,
    *,
    parsed_query: ParsedAgentQuery,
    matches: list[CompoundMatchCard],
    compounds: list[CompoundOverview],
    tool_trace: list[AgentToolTraceEntry],
    needs_clarification: bool,
) -> list[str]:
    
    """Восстановление пути размышлений агента"""

    if needs_clarification or not parsed_query.query:
        return []

    is_russian = _contains_cyrillic(request_text)

    mode = parsed_query.query.input_mode
    identifier = parsed_query.query.identifier

    primary = compounds[0] if compounds else None
    explanation: list[str] = []

    if mode == "name":

        msg = f"Запрос интерпретирован как поиск по названию: {identifier}." if is_russian \
              else f"The request was interpreted as a name search: {identifier}."
        
        explanation.append(msg)

    elif mode == "smiles":
        msg = f"Использована химическая структура (SMILES): {identifier}." if is_russian \
              else f"The chemical structure (SMILES) was used: {identifier}."
        
        explanation.append(msg)

    elif mode == "formula":
        msg = f"Поиск выполнен по молекулярной формуле: {identifier}." if is_russian \
              else f"The search was performed by molecular formula: {identifier}."
        
        explanation.append(msg)

    elif mode == "cid":
        msg = f"Запрос выполнен по прямому идентификатору PubChem CID: {identifier}." if is_russian \
              else f"The query was executed by direct PubChem CID: {identifier}."
        
        explanation.append(msg)

###проверка результата
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


    deduped = list(OrderedDict((item, None) for item in explanation).keys())
    return deduped[:4]


def _collect_compounds(tool_trace: list[AgentToolTraceEntry]) -> tuple[list[CompoundMatchCard], list[CompoundOverview]]:
    """
    Функция обходит лог действий агента (tool_trace), парсит JSON-ответы от сервера PubChem,
    валидирует их с помощью Pydantic-моделей и формирует два списка: краткие карточки 
    совпадений и подробные обзоры соединений. Используется OrderedDict для сохранения 
    порядка появления и дедупликации по CID.

    Args:
        tool_trace (list[AgentToolTraceEntry]): Список записей о вызовах инструментов,
            где каждая запись содержит сырой результат выполнения функции (JSON или dict).

    Returns:
        tuple[list[CompoundMatchCard], list[CompoundOverview]]: Кортеж, содержащий:
            1. Список уникальных карточек совпадений (CompoundMatchCard) для UI/поиска.
            2. Список уникальных подробных описаний соединений (CompoundOverview).
    """
    match_map: "OrderedDict[int, CompoundMatchCard]" = OrderedDict()
    compound_map: "OrderedDict[int, CompoundOverview]" = OrderedDict()

    for event in tool_trace:
        # требуемый формат raw_result: json
        raw_result = event.result
        if isinstance(raw_result, str):
            try:
                result_data = json.loads(raw_result)

            except Exception:
                continue

        elif isinstance(raw_result, dict):
            result_data = raw_result

        else:
            continue

        if not result_data.get("ok", False):
            continue


        for match in result_data.get("matches", []) or []:
            try:
                validated = CompoundMatchCard.model_validate(match)
                # setdefault гарантирует дедупликацию: оставляем первое найденное
                match_map.setdefault(validated.cid, validated)

            except Exception:
                continue

        compound = result_data.get("compound")
        if compound:
            try:
                validated = CompoundOverview.model_validate(compound)
                if validated:
                    compound_map.setdefault(validated.cid, validated)
                    
            except Exception:
                pass

        cid_val = result_data.get("cid")
        if cid_val:
            try:
                cid_int = int(cid_val)
                if cid_int not in match_map:
                    match_map[cid_int] = CompoundMatchCard(
                        cid=cid_int,
                        title=result_data.get("resolved_title") or f"CID {cid_int}",
                        molecular_formula=result_data.get("molecular_formula"),
                        molecular_weight=result_data.get("molecular_weight")
                    )
            except Exception:
                continue

    return list(match_map.values()), list(compound_map.values())


def _build_warnings(normalized: AgentNormalizedPayload) -> list[WarningMessage]:
    """Генерирует диагностические предупреждения о состоянии обработки запроса.

    Функция анализирует флаги в нормализованных данных агента, чтобы выявить потенциальные
    проблемы: отсутствие вызова инструментов (MCP) или необходимость диалога с пользователем.

    Args:
        normalized (AgentNormalizedPayload): Объект с извлеченными признаками ответа 
            агента (наличие трейсов инструментов, флаги уточнения).

    Returns:
        list[WarningMessage]: Список объектов предупреждений. Пустой список = 
            что запрос обработан в штатном режиме без замечаний.
    """
    warnings: list[WarningMessage] = []
    if normalized.needs_clarification:
        warnings.append(
            WarningMessage(
                code="NEEDS_CLARIFICATION",
                message="Запрос требует уточнения перед надёжным поиском в PubChem.",
            )
        )
    if not normalized.tool_trace:
        warnings.append(
            WarningMessage(
                code="NO_TOOL_USAGE",
                message="Агент не вызвал PubChem tools. Ответ мог остановиться на этапе уточнения.",
            )
        )
    return warnings


def build_agent_response_envelope(
    trace_id: str,
    request: AgentRequest,
    runtime: PreparedAgentRuntime,
    result: dict[str, Any],
    tool_trace: list[AgentToolTraceEntry],
) -> AgentResponseEnvelope:
    """Final response assembly.

    `create_agent(...).ainvoke(...)` returns a LangGraph state dict (messages,
    structured_response, etc.) — NOT a Pydantic model. We reconstruct the
    envelope using the helper functions defined above:
    - final_answer from the last AIMessage; fallback to compound summary
      when the LLM produced an empty / generic response.
    - matches/compounds extracted from tool_trace JSON payloads.
    - parsed_query / explanation / clarification reconstructed from the
      tool_trace + the original user text.
    """

    execution_info = AgentExecutionInfo(
        provider=runtime.provider,
        model=runtime.model_name,
        text=request.text,
    )

    matches, compounds = _collect_compounds(tool_trace)

    final_answer = _fallback_answer(result)
    if not final_answer or final_answer.startswith("Агент завершил работу"):
        if matches or compounds:
            final_answer = _fallback_compound_answer(request.text, matches, compounds)

    parsed_query = _infer_parsed_query(request.text, tool_trace)
    needs_clarification, clarification_question = _infer_clarification(
        final_answer, matches, compounds
    )
    explanation = _infer_explanation(
        request.text,
        parsed_query=parsed_query,
        matches=matches,
        compounds=compounds,
        tool_trace=tool_trace,
        needs_clarification=needs_clarification,
    )
    referenced_cids = _collect_referenced_cids(matches, compounds)

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
        referenced_cids=referenced_cids,
    )

    warnings = _build_warnings(normalized)

    raw_payload: dict[str, Any] | None = None
    if request.include_raw and isinstance(result, dict):
        messages = result.get("messages", [])
        raw_payload = {
            "message_count": len(messages),
            "tool_call_count": len(tool_trace),
            "structured_response": result.get("structured_response"),
        }

    return AgentResponseEnvelope(
        trace_id=trace_id,
        status="success",
        normalized=normalized,
        raw=raw_payload,
        warnings=warnings,
    )