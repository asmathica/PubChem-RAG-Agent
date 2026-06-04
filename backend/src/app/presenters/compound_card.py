from typing import Any

from app.schemas.agent import AgentResponseEnvelope
from app.schemas.common import CompoundMatchCard, CompoundOverview


def build_compound_card_props(
    compound: CompoundOverview,
    *,
    explanation: list[str] | None = None,
    synonyms: list[str] | None = None,
) -> dict[str, Any]:
    """Готовит props для inline-карточки в Chainlit (CustomElement CompoundCardV2).
    TPSA/complexity/hbond-поля исключены: MCP-tools пока их не возвращают."""
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
        return _match_to_overview(normalized.matches[0])
    return None


def _match_to_overview(match: CompoundMatchCard) -> CompoundOverview:
    """Поднимает match до CompoundOverview, копируя только общие поля
    (всё что PubChem уже вернул) — без второго запроса к API."""
    shared = {k: v for k, v in match.model_dump().items() if k in CompoundOverview.model_fields}
    return CompoundOverview(**shared)


def select_compounds_for_cards(response: AgentResponseEnvelope, limit: int = 4) -> list[CompoundOverview]:
    """Все вещества для карточек: полные compounds если есть, иначе matches.
    Дедуп по CID, не более `limit` штук. Одно вещество → одна карточка,
    несколько → несколько."""
    normalized = response.normalized
    if normalized is None:
        return []

    source = normalized.compounds or [_match_to_overview(m) for m in normalized.matches]
    seen: set[int] = set()
    unique: list[CompoundOverview] = []
    for compound in source:
        if compound.cid not in seen:
            seen.add(compound.cid)
            unique.append(compound)
    return unique[:limit]


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


def build_details_markdown(response: AgentResponseEnvelope) -> str:
    """Markdown для правой side-панели Chainlit.

    MCP-search tools сейчас возвращают только cid/title/formula/mol_weight,
    поэтому rich-fields (IUPAC, SMILES, XLogP…) почти всегда пустые. Чтобы
    панель не выглядела как одинокий заголовок «Подробности» — всегда печатаем
    то что есть + ссылку на PubChem + ход поиска.
    """
    normalized = response.normalized
    if normalized is None:
        return "Подробные сведения недоступны."

    primary = select_primary_compound(response)
    if primary is None:
        return build_tool_trace_markdown(response)

    lines: list[str] = [f"### {primary.title or f'CID {primary.cid}'}"]
    lines.append(f"- **PubChem CID:** {primary.cid}")
    if primary.molecular_formula:
        lines.append(f"- **Молекулярная формула:** `{primary.molecular_formula}`")
    if primary.molecular_weight is not None:
        lines.append(f"- **Молекулярная масса:** {primary.molecular_weight:.2f} г/моль")
    if primary.iupac_name:
        lines.append(f"- **IUPAC:** {primary.iupac_name}")
    if primary.canonical_smiles:
        lines.append(f"- **Canonical SMILES:** `{primary.canonical_smiles}`")
    if primary.exact_mass is not None:
        lines.append(f"- **Exact mass:** {primary.exact_mass:.4f}")
    if primary.xlogp is not None:
        lines.append(f"- **XLogP:** {primary.xlogp}")

    lines.append("")
    lines.append(f"[Открыть на PubChem ↗]({build_pubchem_compound_url(primary.cid)})")

    if primary.description:
        lines.append("")
        lines.append("#### Описание")
        lines.append(primary.description)

    if normalized.tool_trace:
        lines.append("")
        lines.append(build_tool_trace_markdown(response))

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
