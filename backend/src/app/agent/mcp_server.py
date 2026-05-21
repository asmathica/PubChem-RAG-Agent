from app.agent.mcp_tools.base_search import (
    search_compound_by_name, 
    search_compound_by_smiles,
    search_compound_by_formula,
    search_compound_by_inchikey
)
from app.agent.mcp_tools.structural import search_substructure_pubchem
from app.agent.mcp_tools.similar_search import search_by_similar_mol_pubchem

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pubchem-tools")


mcp.tool()(search_compound_by_name)
mcp.tool()(search_compound_by_smiles)
mcp.tool()(search_compound_by_formula)
mcp.tool()(search_compound_by_formula)
mcp.tool()(search_compound_by_inchikey)

mcp.tool()(search_substructure_pubchem)
mcp.tool()(search_by_similar_mol_pubchem)

#tool 5
#@mcp.tool()
#async def search_compound_by_mass_range(
 #   min_mass: float,
  #  max_mass: float,
  #  mass_type: str = "molecular_weight",
  #  limit: int = 5
#) -> str:
  #  """
 #   Search PubChem compounds by a bounded mass range.
  #  mass_type can be: 'molecular_weight', 'exact_mass', or 'monoisotopic_mass'.
   # """
    # Маппинг типов масс для URL PubChem
   # mass_map = {
    #    "molecular_weight": "MolecularWeight",
     #   "exact_mass": "ExactMass",
     #   "monoisotopic_mass": "MonoisotopicMass"
   # }
  #  pubchem_mass_type = mass_map.get(mass_type, "MolecularWeight")
    
   # async with httpx.AsyncClient(timeout=15) as client:
    #    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{pubchem_mass_type}/{min_mass}:{max_mass}/cids/JSON"
     #   try:
        #    response = await client.get(url)
        #    if response.status_code != 200:
           #     return json.dumps({"ok": False, "message": "Mass range search failed", "matches": []})

          #  data = response.json()
           # cid_list = data.get('IdentifierList', {}).get('CID', [])[:limit]
            
          #  if not cid_list:
           #     return json.dumps({"ok": True, "matches": [], "count": 0})JSON?

          #  results = await asyncio.gather(*[_fetch_props(cid, client) for cid in cid_list])
          #  return json.dumps({
              #  "ok": True, 
             #   "query": {"min": min_mass, "max": max_mass, "type": mass_type}, 
             #   "matches": results, 
             #   "count": len(results)
           # }, ensure_ascii=False)
      #  except Exception as e:
           # return json.dumps({"ok": False, "message": str(e)})

#tool 6

#@mcp.tool()
#async def get_compound_summary(cid: int) -> str:
  #  """Fetch a compact PubChem summary and description for a single CID."""
  #  async with httpx.AsyncClient(timeout=10) as client:
   #     try:
            # 1. Получаем свойства
        #    props = await _fetch_props(cid, client)
            
            # 2. Получаем текстовое описание (дескрипшн)
          #  desc_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/description/JSON"
          #  desc_res = await client.get(desc_url)
          #  description = "No description available"
            
           # if desc_res.status_code == 200:
           #     desc_data = desc_res.json()
           #     # Извлекаем первый доступный текст описания
            #    annotations = desc_data.get("InformationList", {}).get("Information", [])
            #    for info in annotations:
                 #   if "Description" in info:
                   #     description = info["Description"]
                    #    break

           # return json.dumps({
            #    "ok": True,
           #     "cid": cid,
          #      "compound": props,
           #     "description": description
          #  }, ensure_ascii=False)
    #   except AppError as e:
        # Ловим наши "красивые" ошибки (например, 404)
      #  return json.dumps(_error_payload(e), ensure_ascii=False)
        
 #   except Exception as e:
  #      # Ловим всё остальное (сломался код, упала сеть)
   #     return json.dumps(_unexpected_error_payload(e), ensure_ascii=False)

#tool 7
#t@mcp.tool()
#async def search_by_synonym_pubchem(synonym: str, limit: int = 5) -> str:
  # """Search PubChem compounds by synonym or alternative name."""
  #  # В PubChem поиск по имени и по синониму часто идет через один и тот же эндпоинт name
    # Но мы можем явно пометить это для агента как поиск синонимов
   # return await search_by_name_pubchem(name=synonym, limit=limit)

if __name__ == "__main__":#запуск цикла событий
    mcp.run(transport="stdio")