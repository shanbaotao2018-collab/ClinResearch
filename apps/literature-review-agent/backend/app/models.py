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


class ScreeningDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    decision: str
    reason: str
    actor: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PrismaCount(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, unique=True)
    identified_count: int = 0
    deduplicated_count: int = 0
    screened_count: int = 0
    included_count: int = 0
    excluded_count: int = 0
    full_text_assessed_count: int = 0


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    action: str
    actor: str
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignStatus(StrEnum):
    DRAFT = "draft"
    BLUEPRINT_READY = "blueprint_ready"
    CONTENT_DRAFTED = "content_drafted"
    SAMPLE_SIZE_READY = "sample_size_ready"
    APPROVAL_PENDING = "approval_pending"
    HUMAN_APPROVED = "human_approved"
    RANDOMIZATION_READY = "randomization_ready"
    HUMAN_CONFIRMED = "human_confirmed"
    EXPORTED = "exported"


class StudyDesignProject(SQLModel, table=True):
    """Project record for a clinical study-design workflow, separate from reviews."""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    research_question: str
    study_type: str
    study_design: str
    population: str
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcome: str
    department: Optional[str] = None
    resource_summary: Optional[str] = None
    protocol_standard: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None
    primary_outcome: Optional[str] = None
    secondary_outcomes: Optional[str] = None
    innovation_notes: Optional[str] = None
    feasibility_notes: Optional[str] = None
    proposal_outline: Optional[str] = None
    sample_size_method: Optional[str] = None
    sample_size_inputs_json: Optional[str] = None
    sample_size_result_json: Optional[str] = None
    randomization_seed: Optional[int] = None
    randomization_schedule_json: Optional[str] = None
    human_confirmed_by: Optional[str] = None
    human_confirmed_at: Optional[datetime] = None
    status: StudyDesignStatus = Field(default=StudyDesignStatus.DRAFT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignAuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_design_project_id: int = Field(index=True)
    action: str
    actor: str
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"


class StudyDesignApproval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_design_project_id: int = Field(index=True, unique=True)
    scope_digest: str
    status: StudyDesignApprovalStatus = Field(default=StudyDesignApprovalStatus.PENDING)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class StudyDesignRandomizationPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_design_project_id: int = Field(index=True, unique=True)
    total_subjects: int
    groups_json: str
    block_size: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignRandomizationSchedule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_design_project_id: int = Field(index=True, unique=True)
    storage_path: str
    checksum: str
    total_subjects: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignWorkflowRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    study_design_project_id: int = Field(index=True)
    actor: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignWorkflowEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_run_id: str = Field(index=True)
    study_design_project_id: int = Field(index=True)
    operation: str
    input_digest: str
    output_digest: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StudyDesignSkillExecutionReceipt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receipt_id: str = Field(index=True, unique=True)
    workflow_run_id: str = Field(index=True)
    study_design_project_id: int = Field(index=True)
    opencode_session_id: str = Field(index=True)
    skill_name: str
    executed_at: datetime
    signature: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentWorkflowRun(SQLModel, table=True):
    """Persisted run for the evidence-extraction and research-writing agents."""

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    workflow_type: str = Field(index=True)
    subject_type: str = Field(index=True)
    subject_id: int = Field(index=True)
    actor: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentWorkflowEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_run_id: str = Field(index=True)
    workflow_type: str = Field(index=True)
    subject_type: str = Field(index=True)
    subject_id: int = Field(index=True)
    operation: str
    input_digest: str
    output_digest: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentSkillExecutionReceipt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receipt_id: str = Field(index=True, unique=True)
    workflow_run_id: str = Field(index=True)
    workflow_type: str = Field(index=True)
    subject_type: str = Field(index=True)
    subject_id: int = Field(index=True)
    opencode_session_id: str = Field(index=True)
    skill_name: str
    executed_at: datetime
    signature: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidenceExtraction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    study_design: Optional[str] = None
    population: Optional[str] = None
    sample_size: Optional[str] = None
    intervention_or_exposure: Optional[str] = None
    comparator: Optional[str] = None
    outcomes: Optional[str] = None
    effect_estimates: Optional[str] = None
    methods_summary: Optional[str] = None
    evidence_basis: str
    missing_fields_json: str = "[]"
    needs_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CitationSafetyCheck(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    status: str
    check_source: str
    details: Optional[str] = None
    needs_human_review: bool = True
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FullTextDocument(SQLModel, table=True):
    """Traceable full-text source supplied by a researcher or public-source workflow."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    source_kind: str
    source_url: Optional[str] = None
    content_text: str
    content_sha256: str = Field(index=True)
    page_count: Optional[int] = None
    needs_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FullTextEvidenceDetail(SQLModel, table=True):
    """Structured baseline and outcome data explicitly tied to a full-text source."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    full_text_document_id: int = Field(index=True)
    baseline_json: str = "{}"
    outcomes_json: str = "[]"
    extraction_notes: Optional[str] = None
    needs_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BiasAssessment(SQLModel, table=True):
    """Human-reviewable RoB 2, NOS, or QUADAS-2 assessment based on full text."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    full_text_document_id: int = Field(index=True)
    instrument: str = Field(index=True)
    overall_judgement: str
    domains_json: str
    needs_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BinaryMetaAnalysisRun(SQLModel, table=True):
    """Persisted binary-outcome synthesis. Results are never final without review."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    workflow_run_id: str = Field(index=True)
    outcome_label: str
    effect_measure: str
    model: str
    result_json: str
    forest_plot_svg: str
    needs_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SystematicEvidenceReviewApproval(SQLModel, table=True):
    """External researcher approval for one immutable systematic-evidence scope."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    workflow_run_id: str = Field(index=True, unique=True)
    scope_digest: str
    status: str = Field(default="pending")
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class ResearchWritingDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_run_id: str = Field(index=True)
    source_type: str = Field(index=True)
    source_id: int = Field(index=True)
    document_type: str = Field(index=True)
    title: str
    target_audience: Optional[str] = None
    source_manifest_json: str
    outline: str
    methods_draft: Optional[str] = None
    discussion_framework: Optional[str] = None
    proposal_draft: Optional[str] = None
    limitations: str
    unresolved_items: str
    version_number: int
    status: str = Field(default="draft")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchWritingApproval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    research_writing_draft_id: int = Field(index=True, unique=True)
    scope_digest: str
    status: str = Field(default="pending")
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
