import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from langchain_core.runnables import RunnableConfig
# Убедись, что этот импорт create_agent соответствует твоей библиотеке
# (например, из langchain.agents или твоего кастомного модуля)
from langchain.agents import create_agent 
from app.agent.prompts import SYSTEM_PROMPT

current_file = Path(__file__).resolve()
src_path = None
for parent in current_file.parents:
    if parent.name == 'src':
        src_path = str(parent)
        break

env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
print(f"DEBUG: Ключ найден? {'Да' if os.getenv('OPENAI_API_KEY') else 'Нет'}")

async def main():
    # Инициализация клиента
    client = MultiServerMCPClient({                      
        "pubchem": {
            "command": "python",
            "args": ["-m", "app.agent.mcp_server"],
            "transport": "stdio",
            "env": {
                **os.environ, 
                "PYTHONPATH": src_path, 
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY")
            }
        }
    })
    
    print(f"--- Запуск MCP Сервера ---")
    print(f"Корень (PYTHONPATH): {src_path}")
    print(f"Команда: {sys.executable} -m app.agent.mcp_server")
        
    # ИСПРАВЛЕНИЕ: Вся работа с инструментами и агентом должна быть внутри контекста!
    async with client:
        print("🔌 Подключение к MCP-серверу установлено...")
        
        tools = await client.get_tools()
        print(f"Доступные инструменты: {[t.name for t in tools]}")
        
        # Настройка локальной модели Ollama
        llm = ChatOllama(
            model="qwen2.5:7b",
            temperature=0,
            base_url="http://localhost:11434" 
        )
        
        llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)
        prompt = SYSTEM_PROMPT
        
        agent = create_agent(
            model=llm_with_tools, 
            tools=tools, 
            system_prompt=prompt
        )
        
        

if __name__ == "__main__":
    asyncio.run(main())