from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional

from sqlmodel import Field, SQLModel


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    SEARCH_STRATEGY_READY = "search_strategy_ready"
    SEARCH_EXECUTED = "search_executed"
    CITATIONS_DEDUPLICATED = "citations_deduplicated"
    SCREENING_IN_PROGRESS = "screening_in_progress"
    SCREENING_COMPLETED = "screening_completed"
    PRISMA_GENERATED = "prisma_generated"
    EXPORTED = "exported"


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    research_question: str
    pico_population: Optional[str] = None
    pico_intervention: Optional[str] = None
    pico_comparator: Optional[str] = None
    pico_outcome: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SearchStrategyVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    query_text: str
    source: str
    version_number: int
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Citation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    source: str
    external_id: Optional[str] = Field(default=None, index=True)
    title: str
    abstract: Optional[str] = None
    authors: Optional[str] = None
    publication_year: Optional[int] = None
    doi: Optional[str] = None
    is_deduplicated: bool = False
    dedup_group: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    action: str
    actor: str
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
