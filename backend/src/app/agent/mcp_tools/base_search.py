import urllib.parse
import httpx
from app.agent.mcp_tools.search_cid import perform_search
from app.schemas.schemas import (SearchByNameInput,SearchBySMILESInput,SearchByFormulaInput,SearchByMassRangeArgs
                                 ,SearchByInChIKeyArgs)


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
    

