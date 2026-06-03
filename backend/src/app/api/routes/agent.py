import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.errors.models import AppError
from app.schemas.agent import AgentRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent"])


@router.post("/api/agent")
async def run_agent(
    payload: AgentRequest,
    request: Request,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> JSONResponse:
    """POST /api/agent — natural-language запрос к LangChain агенту.

    AppError пробрасываем дальше — он будет нормализован в main.py
    через unhandled_exception_handler в правильный envelope.
    """
    if not hasattr(request.app.state, "container"):
        return JSONResponse(
            status_code=500,
            content={"error": "Container not initialized in app.state"},
        )

    container = request.app.state.container
    try:
        response = await container.agent_service.execute(
            payload,
            trace_id=request.state.trace_id,
            session_id=x_session_id,
        )
    except AppError as error:
        logger.warning("AppError in /api/agent: %s: %s", type(error).__name__, error)
        raise

    return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
