import httpx
import asyncio
global_sem = asyncio.Semaphore()

_PROPERTY_FIELDS = (
    "Title",
    "MolecularFormula",
    "MolecularWeight",
    "IUPACName",
    "CanonicalSMILES",
    "IsomericSMILES",
    "InChIKey",
    "ExactMass",
    "XLogP",
    "TPSA",
    "Complexity",
    "HBondDonorCount",
    "HBondAcceptorCount",
    "Charge",
)

def _coerce_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _fetch_props(cid: int, client: httpx.AsyncClient) -> dict:
    """Один REST-вызов к PubChem забирает все колонки, которые шоу в CompoundCard
    и в боковой панели «Свойства вещества». При сетевой ошибке возвращаем
    только cid + title-плейсхолдер, чтобы LangChain агент мог продолжить."""
    prop_url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/"
        + ",".join(_PROPERTY_FIELDS)
        + "/JSON"
    )
    try:
        async with global_sem:
            response = await client.get(prop_url, timeout=5.0)
            await asyncio.sleep(0.1)

        if response.status_code == 200:
            data = response.json()
            props = data["PropertyTable"]["Properties"][0]
            return {
                "cid": cid,

                "title": props.get("Title"),
                "molecular_formula": props.get("MolecularFormula"),
                "molecular_weight": _coerce_float(props.get("MolecularWeight")),
                "iupac_name": props.get("IUPACName"),
                "canonical_smiles": props.get("CanonicalSMILES"),
                "isomeric_smiles": props.get("IsomericSMILES"),
                "inchi_key": props.get("InChIKey"),
                "exact_mass": _coerce_float(props.get("ExactMass")),
                "xlogp": _coerce_float(props.get("XLogP")),
              # "tpsa": _coerce_float(props.get("TPSA")),
               # "complexity": _coerce_float(props.get("Complexity")),
                #"hbond_donor_count": _coerce_int(props.get("HBondDonorCount")),
                #"hbond_acceptor_count": _coerce_int(props.get("HBondAcceptorCount")),
                "charge": _coerce_int(props.get("Charge")),
            }
    except Exception:
        pass

    return {
        "cid": cid,
        "XLogP": 0,
        "title": f"CID {cid}",
        "molecular_formula": None,
        "molecular_weight": None,
    }


async def perform_search(client: httpx.AsyncClient, url: str, query_val: str, limit: int) -> dict:
    """Общая логика поиска CID и сбора свойств для всех инструментов."""
    try:
        async with global_sem:
            response = await client.get(url, timeout=10.0)
            await asyncio.sleep(0.1)
        if response.status_code not in [200,202]:
            return {
                "ok": False, 
                "message": f"Запрос '{query_val}' не дал результатов в базе PubChem.", 
                "matches": []
            }

        data = response.json()

        list_key = data.get("Waiting", {}).get("ListKey")
        
        if list_key:
            status_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/listkey/{list_key}/cids/JSON"
            max_attempts = 4
            
            for attempt in range(max_attempts):
                await asyncio.sleep(0.1)  
                
                async with global_sem:
                    status_res = await client.get(status_url, timeout=10.0)
                
                if status_res.status_code in [200,202]:
                    data = status_res.json()
                    break

                elif attempt == max_attempts - 1:
                    return {"ok": False, "message": "Превышено время ожидания ответа от PubChem.", "matches": []}

        cid_list = data.get('IdentifierList', {}).get('CID', [])[:limit]
        
        if not cid_list:
            return {"ok": False, "message": "Список идентификаторов пуст.", "matches": []}
        
        # Запускаем сбор свойств. return_exceptions=True гарантирует, что gather не выкинет Exception
        tasks = [_fetch_props(cid, client) for cid in cid_list]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Очищаем результаты от возможных объектов исключений
        matches = [res for res in results_raw if isinstance(res, dict)]
        
        return {
            "ok": True if matches else False,
            "query": query_val,
            "matches": matches,
            "count": len(matches)
        }

    except Exception as e:
        # Ловим только критические ошибки (например, полный разрыв соединения)
        return {
            "ok": False, 
            "message": f"Сетевая ошибка при обращении к PubChem: {str(e)}", 
            "matches": []
        }