export type Overview = {
  summary: {
    study_design_projects: number;
    review_projects: number;
    evidence_workflows: number;
    writing_drafts: number;
    pending_approvals: number;
  };
  study_design_projects: ProjectSummary[];
  review_projects: ProjectSummary[];
  writing_drafts: WritingDraftSummary[];
  pending_approvals: Approval[];
};

export type ProjectSummary = {
  agent_type: "study_design" | "literature_review";
  id: number;
  title: string;
  status: string;
  updated_at: string;
  created_at: string;
  research_question: string;
  study_type?: string;
  prisma?: Record<string, number> | null;
  approval?: Approval | null;
  evidence_run_count?: number;
  writing_draft_count?: number;
};

export type Approval = {
  kind?: string;
  id?: number;
  status: string;
  requested_at: string;
  scope_digest: string;
  approved_by?: string | null;
};

export type WritingDraftSummary = {
  id: number;
  title: string;
  status: string;
  document_type: string;
  source_type: string;
  source_id: number;
  version_number: number;
  updated_at: string;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`读取失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/workbench/overview"),
  study: (id: number) => request<Record<string, unknown>>(`/workbench/study-design-projects/${id}`),
  review: (id: number) => request<Record<string, unknown>>(`/workbench/review-projects/${id}`),
  writing: (id: number) => request<Record<string, unknown>>(`/workbench/research-writing-drafts/${id}`),
};
