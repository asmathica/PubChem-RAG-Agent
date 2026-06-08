"""
MCP-сервер PubChem (stdio).

Запускается как отдельный subprocess (`python -m app.agent.mcp_server`) и
общается с агентом по протоколу MCP через stdio — конфигурация subprocess'а
лежит в `container.py`. Здесь только регистрация функций-инструментов в
FastMCP; сама логика обращения к PubChem — в `app.agent.mcp_tools.*`.

Активных инструмента шесть:
- 4 поиска по идентификатору: name / smiles / formula / inchikey (base_search);
- 2 структурных: подструктура (structural) и поиск похожих молекул (similar_search).
"""
from mcp.server.fastmcp import FastMCP

from app.agent.mcp_tools.base_search import (
    search_compound_by_cid,
    search_compound_by_formula,
    search_compound_by_inchikey,
    search_compound_by_name,
    search_compound_by_smiles,
)
from app.agent.mcp_tools.similar_search import search_by_similar_mol_pubchem
from app.agent.mcp_tools.structural import search_substructure_pubchem

mcp = FastMCP("pubchem-tools")

mcp.tool()(search_compound_by_name)
mcp.tool()(search_compound_by_smiles)
mcp.tool()(search_compound_by_formula)
mcp.tool()(search_compound_by_inchikey)
mcp.tool()(search_compound_by_cid)
mcp.tool()(search_substructure_pubchem)
mcp.tool()(search_by_similar_mol_pubchem)


if __name__ == "__main__":
    # Точка входа subprocess'а: поднимаем MCP event loop поверх stdio.
    mcp.run(transport="stdio")
