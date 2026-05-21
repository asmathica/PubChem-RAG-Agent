import httpx
from rdkit import Chem
from app.agent.mcp_tools.search_cid import perform_search

from app.schemas.schemas import SearchBySMILESInput



async def search_by_similar_mol_pubchem(smiles: str, threshold: float = 0.75, limit: int = 5) -> dict:

    if not smiles:
        return {"ok": False, "message": "Ошибка: SMILES не предоставлен"}
    
    mol = Chem.MolFromSmiles(smiles)

    if mol is None:
        return {
            "ok": False, 
            "message": f"Ошибка: Некорректный или химически невалидный SMILES: {smiles}"
        }

    clean_smiles = Chem.MolToSmiles(mol, isomericSmiles = False)
    
    args = SearchBySMILESInput(smiles = clean_smiles, limit=limit)
    perc_threshold = int(threshold * 100)

    async with httpx.AsyncClient(timeout=15) as client:
     url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/similarity/smiles/{clean_smiles}/Threshold={perc_threshold}"
     return await perform_search(client, url, args.smiles, args.limit)
