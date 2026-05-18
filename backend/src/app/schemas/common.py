from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WarningMessage(BaseModel):
    code: str
    message: str


class PresentationHints(BaseModel):
    active_tab: str = "overview"
    available_tabs: list[str] = Field(default_factory=lambda: ["overview", "synonyms", "json"])


class CompoundMatchCard(BaseModel):
    cid: int
    title: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    image_data_url: str | None = None
    # Enrichment fields fetched via PubChem `/compound/cid/.../property/...`
    # at MCP server time. All optional — older payloads stay backward-compatible.
    iupac_name: str | None = None
    canonical_smiles: str | None = None
    isomeric_smiles: str | None = None
    inchi_key: str | None = None
    exact_mass: float | None = None
    xlogp: float | None = None
    tpsa: float | None = None
    complexity: float | None = None
    hbond_donor_count: int | None = None
    hbond_acceptor_count: int | None = None
    charge: int | None = None


class CompoundOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cid: int
    title: str | None = None
    iupac_name: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    exact_mass: float | None = None
    canonical_smiles: str | None = None
    inchi_key: str | None = None
    xlogp: float | None = None
    tpsa: float | None = None
    complexity: float | None = None
    hbond_donor_count: int | None = None
    hbond_acceptor_count: int | None = None
    description: str | None = None
    image_data_url: str | None = None
    synonyms_preview: list[str] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    code: str
    message: str
    retriable: bool = False
    details: dict[str, Any] | None = None
