from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
#from langchain_openai import ChatOpenAI

#from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.runnables import RunnableConfig
from dotenv import load_dotenv
import os
import sys
import asyncio
from pathlib import Path
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
        
    tools = await client.get_tools()
    #llm = ChatOpenAI(
     #       model="gpt-4o-mini",  
      #      temperature=0
       #     #model_kwargs={"parallel_tool_calls": False}
        #).with_config(RunnableConfig(max_concurrency=1))
    #
    llm = ChatOllama(
    model="gemma3:4b", 
    temperature=0,
    # Ollama по умолчанию работает на http://localhost:11434
    base_url="http://localhost:11434" 
)
    
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)
    prompt=SYSTEM_PROMPT
    agent = create_agent(model=llm_with_tools, 
                             tools=tools, 
                             system_prompt=prompt)
    print(f"Доступные инструменты: {[t.name for t in tools]}")

        #вызов агента
       # response = await agent.ainvoke({
        #    "messages": [HumanMessage(content="Найди аспирин")]
        #})
        #print(response)

if __name__ == "__main__":
    asyncio.run(main())