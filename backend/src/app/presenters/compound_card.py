from typing import Any

from app.schemas.agent import AgentResponseEnvelope
from app.schemas.common import CompoundMatchCard, CompoundOverview


def build_compound_card_props(
    compound: CompoundOverview,
    *,
    explanation: list[str] | None = None,
    synonyms: list[str] | None = None,
) -> dict[str, Any]:
    name = compound.title or compound.iupac_name or f"CID {compound.cid}"
    return {
        "cid": compound.cid,
        "name": name,
        "iupac_name": compound.iupac_name,
        "molecular_formula": compound.molecular_formula,
        "molecular_weight": compound.molecular_weight,
        "exact_mass": compound.exact_mass,
        "canonical_smiles": compound.canonical_smiles,
        "xlogp": compound.xlogp,
        "tpsa": compound.tpsa,
        "complexity": compound.complexity,
        "hbond_donor_count": compound.hbond_donor_count,
        "hbond_acceptor_count": compound.hbond_acceptor_count,
        "description": compound.description,
        "synonyms": list((synonyms or compound.synonyms_preview)[:8]),
        "why_it_matches": " ".join(explanation or []),
        "image_url": build_structure_image_url(compound.cid),
        "pubchem_url": build_pubchem_compound_url(compound.cid),
        "ghs_hazards": [],
    }


def build_structure_image_url(cid: int) -> str:
    return f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG?image_size=300x200"


def build_pubchem_compound_url(cid: int) -> str:
    return f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"


def select_primary_compound(response: AgentResponseEnvelope) -> CompoundOverview | None:
    normalized = response.normalized
    if normalized is None:
        return None

    if normalized.compounds:
        referenced = set(normalized.referenced_cids)
        for compound in normalized.compounds:
            if compound.cid in referenced:
                return compound
        return normalized.compounds[0]

    if normalized.matches:
        match = normalized.matches[0]
        # Pass every enriched field that PubChem returned so the side
        # panel and CompoundCard can show IUPAC / SMILES / XLogP / TPSA /
        # complexity / H-bond counts without a second tool call.
        return CompoundOverview(
            cid=match.cid,
            title=match.title,
            molecular_formula=match.molecular_formula,
            molecular_weight=match.molecular_weight,
            iupac_name=match.iupac_name,
            canonical_smiles=match.canonical_smiles,
            inchi_key=match.inchi_key,
            exact_mass=match.exact_mass,
            xlogp=match.xlogp,
            tpsa=match.tpsa,
            complexity=match.complexity,
            hbond_donor_count=match.hbond_donor_count,
            hbond_acceptor_count=match.hbond_acceptor_count,
        )
    return None


def extract_primary_synonyms(response: AgentResponseEnvelope, cid: int) -> list[str]:
    normalized = response.normalized
    if normalized is None:
        return []
    for event in normalized.tool_trace:
        result = event.result or {}
        if result.get("cid") == cid and event.tool_name == "get_compound_summary":
            synonyms = result.get("synonyms") or []
            return [value for value in synonyms if isinstance(value, str)]
    return []


def build_candidates_markdown(matches: list[CompoundMatchCard]) -> str:
    if not matches:
        return "Других кандидатов не найдено."

    lines = ["### Другие кандидаты"]
    for index, match in enumerate(matches, start=1):
        parts = [f"{index}. **{match.title or f'CID {match.cid}'}**", f"`CID {match.cid}`"]
        if match.molecular_formula:
            parts.append(match.molecular_formula)
        if match.molecular_weight is not None:
            parts.append(f"{match.molecular_weight:.2f} g/mol")
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def build_tool_trace_markdown(response: AgentResponseEnvelope) -> str:
    normalized = response.normalized
    if normalized is None or not normalized.tool_trace:
        return "Инструменты не вызывались."

    lines = ["### Ход поиска"]
    for item in normalized.tool_trace:
        result = item.result or {}
        if result.get("needs_clarification"):
            lines.append(f"{item.step}. `{item.tool_name}` — запросил уточнение.")
            continue
        match_count = result.get("count")
        if match_count is not None:
            lines.append(f"{item.step}. `{item.tool_name}` — найдено кандидатов: {match_count}.")
            continue
        if result.get("cid"):
            lines.append(f"{item.step}. `{item.tool_name}` — обработан CID {result['cid']}.")
            continue
        lines.append(f"{item.step}. `{item.tool_name}` — шаг завершён.")
    return "\n".join(lines)
