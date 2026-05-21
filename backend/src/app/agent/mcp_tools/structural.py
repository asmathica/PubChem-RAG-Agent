
from rdkit import Chem
import urllib.parse
import httpx
from app.agent.mcp_tools.search_cid import perform_search

async def search_substructure_pubchem(smiles: str, limit: int = 5) -> dict:
    """
    Поиск соединений, содержащих указанный фрагмент (подструктуру).
    """
    if not smiles:
        return {"ok": False, "message": "Ошибка: SMILES фрагмента не предоставлен"}
    
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"ok": False, "message": f"Ошибка: Невалидный SMILES фрагмента: {smiles}"}
    
    clean_smiles = Chem.MolToSmiles(mol, isomericSmiles = False)
    encoded_smiles = urllib.parse.quote(clean_smiles)

    async with httpx.AsyncClient(timeout=15) as client:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/substructure/smiles/{encoded_smiles}/JSON"
        return await perform_search(client, url, f"substructure of {clean_smiles}", limit)
    