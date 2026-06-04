from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import CompoundMatchCard, CompoundOverview, ErrorPayload, PresentationHints, WarningMessage


Domain = Literal["compound"]
InputMode = Literal["cid", "name", "smiles", "inchikey", "formula", "Unnamed"]
Operation = Literal[
    "property",
    "record",
    "synonyms",
    "description",
    "xrefs",
    "assaysummary",
    "image",
    "pug_view_overview",
    "safety",
    "fastformula",
    "fastidentity",
    "fastsimilarity_2d",
    "fastsubstructure",
]

class QueryRequest(BaseModel):
    """Объект запроса к сервису поиска."""
    input_mode: InputMode
    identifier: str
    operation: Operation = "property"
    limit: int = Field(default=10, ge=1, le=50)
    include_raw: bool = False

class PaginationSpec(BaseModel):
    start: int = 0
    limit: int = Field(default = 10, ge = 1, le = 50)


class OutputSpec(BaseModel):
    format: Literal["json"] = "json"
    include_images: bool = True
    include_synonyms: bool = True

class ResolvedQuery(BaseModel):
    domain: Domain = "compound"
    input_mode: InputMode
    identifier: str
    operation: Operation

class QueryNormalizedPayload(BaseModel):
    query: ResolvedQuery
    matches: list[CompoundMatchCard] = Field(default_factory=list)
    primary_result: CompoundOverview | None = None
    synonyms: list[str] = Field(default_factory=list)
    sections: dict[str, Any] = Field(default_factory=dict)

class QueryResponseEnvelope(BaseModel):
    trace_id: str
    source: Literal["pubchem-pug-rest", "pubchem-pug-view", "interpreter", "mixed", "pubchem-mcp-service"] = "pubchem-pug-rest"
    status: Literal["success", "error"] = "success"
    raw: dict[str, Any] | None = None
    normalized: QueryNormalizedPayload | None = None
    presentation_hints: PresentationHints = Field(default_factory=PresentationHints)
    warnings: list[WarningMessage] = Field(default_factory=list)
    error: ErrorPayload | None = None
