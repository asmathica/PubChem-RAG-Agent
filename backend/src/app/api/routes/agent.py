from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.errors.models import AppError
from app.errors.normalizer import build_agent_error_response, unknown_error
from app.schemas.agent import AgentRequest


router = APIRouter(tags=["agent"])

@router.post("/api/agent")
async def run_agent(
    payload: AgentRequest,
    request: Request,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> JSONResponse:
    if not hasattr(request.app.state, "container"):
         return JSONResponse(status_code=500, content={"error": "Container not initialized in app.state"})

    container = request.app.state.container
    trace_id = getattr(request.state, "trace_id", "manual-test-id")
    try:
        response = await container.agent_service.execute(
            payload,
            trace_id=request.state.trace_id,
            session_id=x_session_id,
        )
    except AppError as error:
        print(f"DEBUG ERROR: {type(error).__name__}: {str(error)}")
        raise error
       # return build_agent_error_response(trace_id=request.state.trace_id, error=error)
    #except Exception:
     #   return build_agent_error_response(trace_id=request.state.trace_id, error=unknown_error())

    return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
