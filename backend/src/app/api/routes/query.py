from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.errors.models import AppError
from app.errors.normalizer import build_query_error_response, unknown_error
from app.schemas.query import QueryRequest


router = APIRouter(tags=["query"])


@router.post("/api/query")
async def query_compounds(spec: QueryRequest, request: Request) -> JSONResponse:
    # QueryRequest (input_mode/identifier/operation) — именно его ждёт
    # QueryService.execute. Раньше тут стоял AgentRequest (text) → контракт
    # роута расходился с сервисом, и /api/query падал.
    container = request.app.state.container

    trace_id = getattr(request.state, "trace_id", "unknown")
    try:
        response = await container.query_service.execute(spec)
    except AppError as error:
        return build_query_error_response(trace_id=trace_id , error=error)
    except Exception:
        return build_query_error_response(trace_id=trace_id , error=unknown_error())

    return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
