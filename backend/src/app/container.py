from dataclasses import dataclass

from langchain_mcp_adapters.client import MultiServerMCPClient
from app.adapter.pubchem_adapter import PubChemAdapter

from app.agent.tracing import build_langfuse_client_from_settings
from app.config import Settings, get_settings
from app.services.agent_stream_service import AgentStreamService
from app.services.agent_service import AgentService
from app.services.cache import TTLCache
from app.services.interpret_service import InterpretService
from app.services.query_service import QueryService
from app.services.rate_limit import SlidingWindowRateLimiter
from app.transport.pubchem import PubChemTransport
import logging
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
    agent_stream_service: AgentStreamService
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
            logging.info("PubChem transport closed.")
        except Exception as e:
            logging.error(f"Error closing transport: {e}")


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
    resolved_settings = settings or get_settings()
    
    cache = TTLCache()
    rate_limiter = SlidingWindowRateLimiter(limit=resolved_settings.query_rate_limit_per_second)
    transport = PubChemTransport(resolved_settings, rate_limiter)
#создание клиента по Singleton
    server_config = {
        "pubchem": {
            "command": "python",
            "args": ["-m", "app.agent.mcp_server"],
            "transport": "stdio",
     }
    }

    mcp_client = MultiServerMCPClient(server_config)

    return AppContainer(
        settings=resolved_settings,
        cache=cache,
        rate_limiter=rate_limiter,
        transport=transport,
        adapter=PubChemAdapter(resolved_settings, transport, cache),
        query_service=QueryService(resolved_settings, mcp_client),
        interpret_service=InterpretService(),
        agent_service=AgentService(
            resolved_settings, 
            mcp_client=mcp_client 
        ),
        agent_stream_service=AgentStreamService(
            resolved_settings, 
            mcp_client=mcp_client
        ),
        mcp_client=mcp_client 
    )

