from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    title: str
    research_question: str
    pico_population: Optional[str] = None
    pico_intervention: Optional[str] = None
    pico_comparator: Optional[str] = None
    pico_outcome: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str


class SearchStrategyCreate(BaseModel):
    source: str
    query_text: str
    rationale: str


class SearchStrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str
    query_text: str
    version_number: int
    rationale: str | None = None


class PrismaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    identified_count: int
    deduplicated_count: int
    screened_count: int
    included_count: int
    excluded_count: int
    full_text_assessed_count: int


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str
    external_id: str | None = None
    title: str
    abstract: str | None = None
    authors: str | None = None
    publication_year: int | None = None
    doi: str | None = None
    is_deduplicated: bool
    dedup_group: str | None = None


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    action: str
    actor: str
    summary: str
