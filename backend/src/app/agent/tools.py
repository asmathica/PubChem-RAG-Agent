import asyncio
from typing import Any, Literal

from app.config import Settings

def get_mcp_connections_config(settings: Settings) -> dict[str, dict[str, Any]]:
    """
    Централизованный манифест подключений к MCP-серверам.
    Этот конфиг используется MultiServerMCPClient для запуска подпроцессов.
    """
    return {
        "pubchem": {
            "command": "python", 
            "args": ["app/mcp/mcp_server.py"],
            
            # Переменные окружения, которые нужны серверу (например, URL API или ключи)
            "env": {
                "PUBCHEM_API_BASE_URL": "https://pubchem.ncbi.nlm.nih.gov/rest/pug",
                # Можно прокинуть PYTHONPATH, чтобы сервер видел внутренние модули
                "PYTHONPATH": ".", 
            },
            
            "transport": "stdio",
        },
        
       
    }













