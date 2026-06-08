import urllib.parse

import httpx

from app.agent.mcp_tools.search_cid import _fetch_props, perform_search
from app.schemas.schemas import (
    SearchByFormulaInput,
    SearchByInChIKeyArgs,
    SearchByNameInput,
    SearchBySMILESInput,
)


async def search_compound_by_name(name: str, limit: int = 5) -> dict:
    # Сохраняем пробелы внутри multi-word имён ("acetic acid" → URL-encode "acetic%20acid").
    # PubChem REST по name индексу возвращает корректные CIDs только если
    # пробелы не вырезаны — иначе "aceticacid" → 404.
    args = SearchByNameInput(name=name.strip(), limit=limit)
    async with httpx.AsyncClient(timeout=15) as client:
        encoded_name = urllib.parse.quote(args.name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded_name}/cids/JSON"
        return await perform_search(client, url, args.name, args.limit)

    
async def search_compound_by_smiles(smiles: str, limit: int = 5) -> dict:
    clean_smiles = smiles.replace(" ", "").strip()
    args = SearchBySMILESInput(smiles=clean_smiles, limit=limit)
    async with httpx.AsyncClient(timeout=15) as client:
        encoded_smiles = urllib.parse.quote(args.smiles)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{encoded_smiles}/cids/JSON"
        return await perform_search(client, url, args.smiles, args.limit)

async def search_compound_by_formula(formula: str, limit: int = 5) -> dict:
    clean_formula = formula.replace(" ", "").strip()
    args = SearchByFormulaInput(formula=clean_formula, limit=limit)
    async with httpx.AsyncClient(timeout=15) as client:
        encoded_formula = urllib.parse.quote(args.formula)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/fastformula/{encoded_formula}/cids/JSON"
        return await perform_search(client, url, args.formula, args.limit)
    
async def search_compound_by_inchikey(inchikey: str, limit: int = 5) -> dict:
    clean_inchikey = inchikey.replace(" ", "").strip()
    args = SearchByInChIKeyArgs(inchikey=clean_inchikey, limit=limit)
    async with httpx.AsyncClient(timeout=15) as client:
        encoded_inchikey = urllib.parse.quote(args.inchikey)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/{encoded_inchikey}/cids/JSON"
        return await perform_search(client, url, args.inchikey, args.limit)


async def search_compound_by_cid(cid: int, limit: int = 5) -> dict:
    """Прямая выборка вещества по известному PubChem CID (без поиска кандидатов).

    Нужно для типизированного режима `cid` в /api/query и для случаев, когда
    агенту уже известен CID. Возвращает тот же формат, что и search-инструменты
    ({ok, matches, count}); если CID не найден — ok=False.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        props = await _fetch_props(int(cid), client)
    if props.get("molecular_formula") is None:
        return {"ok": False, "message": f"CID {cid} не найден в PubChem.", "matches": []}
    return {"ok": True, "query": str(cid), "matches": [props], "count": 1}
    

