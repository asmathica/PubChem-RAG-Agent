from contextlib import asynccontextmanager
import logging
import socket
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.agent import router as agent_router
from app.api.routes.health import router as health_router
from app.api.routes.interpret import router as interpret_router
from app.api.routes.query import router as query_router
from app.config import get_settings
from app.container import AppContainer, build_container
from app.errors.models import AppError, ErrorCode
from app.errors.normalizer import build_agent_error_response, build_interpret_error_response, build_query_error_response, unknown_error


def _silence_otel_when_langfuse_offline(settings) -> None:
    """If LANGFUSE_BASE_URL points at a port that isn't accepting
    connections, suppress the per-second OTLP exporter warnings so the
    real backend logs stay readable. Once the user runs
    `docker compose -f infra/langfuse-compose.yml up -d` the spans
    will start flowing again — the loggers are not permanently muted,
    just dropped to ERROR.
    """
    url = settings.langfuse_base_url
    if not url.startswith("http://localhost") and not url.startswith("http://127.0.0.1"):
        return  # remote endpoint — leave default warning level
    try:
        host = url.split("://", 1)[1].split("/", 1)[0]
        host, _, port = host.partition(":")
        port = int(port or 80)
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError:
        logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.ERROR)
        logging.getLogger("opentelemetry.exporter.otlp").setLevel(logging.ERROR)


def create_app(container_override: AppContainer | None = None) -> FastAPI:
    """Создаёт и конфигурирует экземпляр приложения FastAPI.

    Функция инкапсулирует логику инициализации веб-сервиса: от настройки CORS 
    и промежуточного ПО (middleware) до регистрации маршрутов и глобальных обработчиков 
    исключений. Особое внимание уделяется управлению жизненным циклом (lifespan) 
    для корректного запуска и остановки контейнера зависимостей.

    Args:
        container_override (AppContainer | None, optional): Возможность передать 
            преднастроенный контейнер зависимостей. Полезно для интеграционного 
            тестирования (например, для подмены реальных сервисов моками).

    Returns:
        FastAPI: Полностью настроенный экземпляр приложения, готовый к запуску 
            через ASGI-сервер (например, uvicorn).

    """
    settings = get_settings()
    _silence_otel_when_langfuse_offline(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = container_override or build_container(settings)
        app.state.container = container
    
        try:
            yield
        finally:

            close = getattr(container, "close", None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                  await result

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        request.state.trace_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request.state.trace_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        print(f"VALIDATION DEBUG: {exc.errors()}")

        app_error = AppError(
            ErrorCode.VALIDATION_ERROR,
            "Запрос не прошёл валидацию.",
            http_status=422,
            details={"errors": exc.errors()},
        )
        if request.url.path.endswith("/api/agent"):
            return build_agent_error_response(trace_id=request.state.trace_id, error=app_error)
        if request.url.path.endswith("/api/interpret"):
            return build_interpret_error_response(trace_id=request.state.trace_id, error=app_error)
        return build_query_error_response(trace_id=request.state.trace_id, error=app_error)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        app_error = exc if isinstance(exc, AppError) else unknown_error()
        if request.url.path.endswith("/api/agent"):
            return build_agent_error_response(trace_id=request.state.trace_id, error=app_error)
        if request.url.path.endswith("/api/interpret"):
            return build_interpret_error_response(trace_id=request.state.trace_id, error=app_error)
        if request.url.path.endswith("/api/query"):
            return build_query_error_response(trace_id=request.state.trace_id, error=app_error)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "trace_id": request.state.trace_id,
                "error": {
                    "code": "UNHANDLED",
                    "message": f"Непредвиденная ошибка приложения: {exc}",
                },
            },
        )

    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(interpret_router)
    app.include_router(agent_router)
    return app


app = create_app()
