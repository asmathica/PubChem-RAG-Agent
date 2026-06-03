import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.adapter.pubchem_adapter import PubChemAdapter
from app.agent.tracing import build_langfuse_client_from_settings
from app.config import Settings, get_settings
from app.services.agent_service import AgentService
from app.services.cache import TTLCache
from app.services.interpret_service import InterpretService
from app.services.query_service import QueryService
from app.services.rate_limit import SlidingWindowRateLimiter
from app.transport.pubchem import PubChemTransport

logger = logging.getLogger(__name__)


@dataclass
class AppContainer:
    settings: Settings
    cache: TTLCache
    rate_limiter: SlidingWindowRateLimiter
    transport: PubChemTransport
    adapter: PubChemAdapter
    query_service: QueryService
    interpret_service: InterpretService
    agent_service: AgentService
    mcp_client: MultiServerMCPClient

    async def close(self) -> None:
        client = build_langfuse_client_from_settings(self.settings)
        if client is not None:
            try:
                client.flush()
            except Exception:
                pass

        try:
            await self.transport.close()
            logger.info("PubChem transport closed.")
        except Exception as e:
            logger.error("Error closing transport: %s", e)


def build_container(settings: Settings | None = None) -> AppContainer:
    """Инициализирует и собирает все зависимости приложения в единый контейнер.

    Функция создает экземпляры базовых сервисов (кеширование, лимитирование запросов, 
    транспортный слой), настраивает MCP-клиент для работы с сервером PubChem и 
    формирует высокоуровневые сервисы (поиск, интерпретация, агентные службы).

    Args:
        settings (Settings | None, optional): Объект настроек приложения. Если не передан, 
            используется результат вызова `get_settings()`.

    Returns:
        AppContainer: Объект-контейнер, содержащий инициализированные экземпляры всех 
            сервисов, необходимых для работы жизненного цикла приложения.
    """
    # .env лежит в корне репо (на 4 уровня выше container.py).
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)
    resolved_settings = settings or get_settings()

    cache = TTLCache()
    rate_limiter = SlidingWindowRateLimiter(limit=resolved_settings.query_rate_limit_per_second)
    transport = PubChemTransport(resolved_settings, rate_limiter)

    # MCP-сервер запускается как subprocess через stdio. PYTHONPATH = src/,
    # чтобы subprocess видел модули `app.*`. Из CWD=backend/ берём src/; в
    # тестах с другим CWD — fallback на директорию этого файла.
    src_path = os.path.abspath("src") if os.path.exists("src") else os.path.dirname(os.path.abspath(__file__))
    server_config = {
        "pubchem": {
            "command": "python",
            "args": ["-m", "app.agent.mcp_server"],
            "transport": "stdio",
            "env": {
                "PYTHONPATH": src_path,
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            },
        }
    }

    mcp_client = MultiServerMCPClient(server_config)
    logger.info("MCP pubchem server configured: PYTHONPATH=%s", src_path)

    return AppContainer(
        settings=resolved_settings,
        cache=cache,
        rate_limiter=rate_limiter,
        transport=transport,
        adapter=PubChemAdapter(resolved_settings, transport, cache),
        query_service=QueryService(resolved_settings, mcp_client),
        interpret_service=InterpretService(),
        agent_service=AgentService(resolved_settings, mcp_client=mcp_client),
        mcp_client=mcp_client,
    )

