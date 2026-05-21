import uuid, json
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import Settings
from app.errors.models import AppError, ErrorCode
from app.schemas.common import PresentationHints, WarningMessage, CompoundMatchCard, CompoundOverview
from app.schemas.query import  QueryNormalizedPayload, QueryResponseEnvelope, ResolvedQuery, InputMode
from app.schemas.query import QueryRequest
from app.services.agent_service import MCP_LOOKUP_MAP 
import logging
SUPPORTED_INPUT_MODES = {"cid", "name", "smiles", "inchikey", "formula"}
SUPPORTED_OPERATIONS = {"property",
    "record",
    "synonyms",
    "description",
    "xrefs",
    "assaysummary",
    "image",
    "pug_view_overview",
    "safety",
    "fastformula",
    "fastidentity",
    "fastsimilarity_2d",
    "fastsubstructure"}

logger = logging.getLogger(__name__)
class QueryService:
    def __init__(self, settings: Settings, mcp_client: MultiServerMCPClient) -> None:
        self.settings = settings
        self.mcp_client = mcp_client

    async def execute(self, req: QueryRequest) -> QueryResponseEnvelope:
        """
        Выполняет запрос через систему MCP инструментов.
        """
        logger.info(f"--- [QueryService] Начало обработки запроса:  ---")
        self._validate_capabilities(req)
        limit = req.limit if req.limit else self.settings.candidate_limit

        tool_name = self._map_input_to_tool(req.input_mode)

        if not tool_name:
            raise AppError(ErrorCode.INVALID_INPUT, f"Режим {req.input_mode} не поддерживается")
        
        tool_args = {
            req.input_mode: req.identifier,
            "limit": limit
        }

#вызов тулов
        try:
         async with self.mcp_client.session("pubchem") as session:
            logger.info(f"Сессия с pubchem открыта. Вызываем инструмент: {tool_name}")
            mcp_result = await session.call_tool(
                    name=tool_name,
                    arguments=tool_args
                )
            logger.info("mcp_result был вызван корерктно")
            raw_text = ""
            if mcp_result.content and hasattr(mcp_result.content[0], 'text'):
                raw_text = mcp_result.content[0].text if mcp_result.content else ""
                print(f"\n DEBUG RAW TEXT: {raw_text} \n")
                
            else:
                raw_text = str(mcp_result)

        except Exception as e:
            raise AppError(
                ErrorCode.INTERNAL_ERROR, 
                f"Ошибка получения ответа от MCP: {str(e)}",
                http_status=500
            )
#парсинг ответа от mcp
      #  try:

       # except Exception as e:
        #    raise AppError(
         #       ErrorCode.INTERNAL_ERROR, 
          #      f"Сервер вернул невалидный JSON",
           #     http_status=502
            #)


        data = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
        raw_matches = data.get("matches", [])
        normalized_matches = []

        for m in raw_matches:
          try:
                normalized_matches.append(CompoundMatchCard.model_validate(m))

          except Exception:
                continue

        primary_overview = None
        synonyms = []

        if not normalized_matches:#если ничего не найдено по результатам поиска в бд
            _matches = [CompoundMatchCard.model_validate([{ "cid" : 0},
                                                          {"XLogP": 0},
                                                         { "title" : "Вещество не найдено"},
                                                         { "molecular_formula" : None},
                                                         { "molecular_weight" : None},
                                                         { "image_data_url":  None}
                                                         ])
                        ]
            current_status = "success"
            additional_sections = {
        "search_info": {
            "mode": req.input_mode,
            "count": 0,
            "message": "По вашему запросу ничего не найдено в базе PubChem"
        }
    }
        #если найдено
        else:
         _matches = normalized_matches
         current_status = "success"
         primary_data = data.get("matches", [])[0]
    
         if raw_matches:
            primary_overview = CompoundOverview.model_validate(raw_matches[0])

         synonyms = data.get("synonyms", [])
         additional_sections = {}
         if "extended_properties" in data:
            additional_sections["properties"] = data["extended_properties"]
        
         additional_sections["search_info"] = {
            "mode": req.input_mode,
            "count": len(normalized_matches)
         }

        # финальный ответ
        return QueryResponseEnvelope(
            trace_id=str(uuid.uuid4()),
            source="pubchem-mcp-service", 
            status = current_status,
            raw = data if req.include_raw else None,
            normalized=QueryNormalizedPayload(
                query=ResolvedQuery(
                    domain="compound",
                    input_mode=req.input_mode,
                    identifier=req.identifier,
                    operation=req.operation,
                ),
                matches=normalized_matches,
                primary_result=primary_overview,
                synonyms=synonyms,
                sections=additional_sections
            ),
            presentation_hints=PresentationHints(
                active_tab="synonyms" if req.operation == "synonyms" else "overview",
                available_tabs=["overview", "synonyms", "json"],
            ),
            warnings = self._build_warnings(req), 
            error=None
        )

    def _validate_capabilities(self, req:  QueryRequest) -> None:
    #вернуть проверку домена
        if req.input_mode not in SUPPORTED_INPUT_MODES:
            raise AppError(
                ErrorCode.UNSUPPORTED_QUERY,
                f"Режим ввода '{req.input_mode}' пока не поддерживается.",
                http_status=400,
            )
        if req.operation not in SUPPORTED_OPERATIONS:
            raise AppError(
                ErrorCode.UNSUPPORTED_QUERY,
                f"Операция '{req.operation}' пока не поддерживается.",
                http_status=400,
            )

    def _build_warnings(self, req:  QueryRequest) -> list[WarningMessage]:
        """Формирует список диагностических предупреждений для пользователя на основе параметров запроса.
    Функция анализирует входящий запрос и добавляет уведомления о специфике обработки данных. 
    Это помогает пользователю понять, почему результат выглядит определённым образом или 
    какие ограничения были применены при поиске.

    Args:
        req (QueryRequest): Объект запроса, содержащий тип операции и режим ввода.

    Returns:
        list[WarningMessage]: Список объектов предупреждений с кодами и описаниями. 
            Если специфических условий не обнаружено, возвращается пустой список.
    """
        warnings: list[WarningMessage] = []
        if req.operation == "record":
            warnings.append(
                WarningMessage(
                    code="RECORD_NORMALIZED",
                    message="Операция record сейчас сводится к тому же обзору, что и property.",
                )
            )
        if req.input_mode in {"name", "smiles"}:
            warnings.append(
                WarningMessage(
                    code = "PRIMARY_IS_FIRST_MATCH",
                    message = "Основным результатом выбран первый найденный кандидат PubChem.",
                )
            )
        return warnings
    

    def _map_input_to_tool(self, mode: InputMode) -> str:
        """Определяет целевой инструмент (tool) MCP-сервера на основе режима ввода пользователя.
    Функция сопоставляет абстрактный режим ввода (название, формула, SMILES) с конкретным 
    именем функции, которую должен вызвать агент для получения данных из PubChem.

    Args:
        mode (InputMode): Режим ввода данных (например, "name", "smiles", "formula").

    Returns:
        str: Название соответствующего инструмента (функции) для MCP-клиента. 
            По умолчанию возвращает "search_by_name_pubchem", если режим не распознан.
    """
        mapping = {
            "name": "search_by_name_pubchem",
            "smiles": "search_by_smiles_pubchem",
           # "cid": "get_by_cid",
            "formula": "search_by_formula_pubchem",
            "inchikey": "search_by_inchikey_pubchem",
            "smiles_similar": "search_similar_mol_pubchem"
        }
        return mapping.get(mode, "search_by_name_pubchem")
