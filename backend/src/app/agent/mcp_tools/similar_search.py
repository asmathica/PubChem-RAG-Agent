import urllib.parse

import httpx
from rdkit import Chem

from app.agent.mcp_tools.search_cid import perform_search
from app.schemas.schemas import SearchBySMILESInput


async def search_by_similar_mol_pubchem(smiles: str, threshold: float = 0.75, limit: int = 5) -> dict:
    """Поиск молекул, похожих на заданный SMILES (2D-сходство Tanimoto).

    RDKit нормализует входной SMILES (отбрасываем стереохимию). threshold (0..1)
    переводится в проценты для PubChem. Используется эндпоинт `fastsimilarity_2d`
    с обязательным суффиксом `/cids/JSON` и параметрами в query-строке — без них
    PUG REST возвращает 400 PUGREST.BadRequest. perform_search дотягивает свойства.
    """
    if not smiles:
        return {"ok": False, "message": "Ошибка: SMILES не предоставлен"}

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {
            "ok": False,
            "message": f"Ошибка: Некорректный или химически невалидный SMILES: {smiles}",
        }

    clean_smiles = Chem.MolToSmiles(mol, isomericSmiles=False)
    args = SearchBySMILESInput(smiles=clean_smiles, limit=limit)
    perc_threshold = int(threshold * 100)
    encoded_smiles = urllib.parse.quote(args.smiles)

    async with httpx.AsyncClient(timeout=15) as client:
        url = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/fastsimilarity_2d/"
            f"smiles/{encoded_smiles}/cids/JSON?Threshold={perc_threshold}&MaxRecords={args.limit}"
        )
        return await perform_search(client, url, args.smiles, args.limit)
