# Evidence And Writing Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two persisted, Skill-gated OpenCode medical research agents for evidence extraction and research writing, each with exports and verified execution receipts.

**Architecture:** Reuse the literature project and citation records, then add small workflow, receipt, artifact, and audit models around them. The OpenCode Agents use Skills for domain method and MCP tools for project-state mutations. The receipt plugin signs required Skills and the backend rejects critical operations without valid signatures.

**Tech Stack:** Python 3.14, FastAPI, SQLModel, MCP Python SDK, OpenCode, Node.js plugin hooks, pytest.

## Global Constraints

- Never place PHI in model prompts or backend records.
- Do not fabricate citations, abstract fields, effect estimates, outcomes, or research results.
- Exported writing remains a researcher-reviewed draft until human confirmation.
- Preserve the existing literature review and study-design workflows.
- Do not expose secret keys or randomization allocations.

---

### Task 1: Persist generic literature workflow runs and Skill receipts

**Files:**
- Modify: `apps/literature-review-agent/backend/app/models.py`
- Modify: `apps/literature-review-agent/backend/app/services/project_workflow.py`
- Modify: `apps/literature-review-agent/backend/app/mcp_server.py`
- Modify: `.opencode/plugins/medical-skill-receipts.mjs`
- Test: `apps/literature-review-agent/backend/tests/test_evidence_extraction.py`

**Interfaces:**
- Produces `ReviewWorkflowRun`, `ReviewWorkflowEvent`, and `ReviewSkillExecutionReceipt` records.
- Produces `start_review_workflow_run(session, project_id, workflow_type, actor)` and `require_review_skill_receipts(session, run_id, project_id, operation)`.
- The plugin binds its session journal to both review and study-design workflow runs.

- [ ] Write a test that starts an `evidence_extraction` run and expects required receipt validation to reject an empty receipt set.
- [ ] Run `pytest tests/test_evidence_extraction.py -q` and confirm failure because the run and receipt APIs do not exist.
- [ ] Add workflow/receipt models and shared service functions with HMAC validation using `LRA_SKILL_RECEIPT_KEY`.
- [ ] Extend the receipt plugin skill allowlist and bind review workflow receipts after `literature_review_start_*_workflow` tool calls.
- [ ] Run the focused test and confirm it passes.

### Task 2: Implement evidence extraction records and MCP workflow

**Files:**
- Modify: `apps/literature-review-agent/backend/app/models.py`
- Modify: `apps/literature-review-agent/backend/app/schemas.py`
- Create: `apps/literature-review-agent/backend/app/services/evidence_extraction.py`
- Modify: `apps/literature-review-agent/backend/app/mcp_server.py`
- Modify: `apps/literature-review-agent/backend/app/services/exporters.py`
- Test: `apps/literature-review-agent/backend/tests/test_evidence_extraction.py`

**Interfaces:**
- Produces MCP tools `start_evidence_extraction_workflow`, `save_evidence_extractions`, `save_retraction_checks`, and `export_evidence_table`.
- `save_evidence_extractions(project_id, workflow_run_id, extractions)` requires the two extraction Skills.
- `export_evidence_table(project_id, workflow_run_id)` requires retraction-watcher receipts and one extraction plus safety check for each included citation.

- [ ] Write a test with two included citations, valid signed receipts, two extraction rows, two safety rows, and an export assertion.
- [ ] Write a test that attempts to save an effect estimate sourced only from metadata and expects validation failure.
- [ ] Run the focused tests and confirm failure because the service is absent.
- [ ] Implement Pydantic payload validation, persistence, audit events, completion checks, JSON and Markdown evidence-table export.
- [ ] Register MCP tools and run the focused tests until passing.

### Task 3: Create evidence-extraction OpenCode Agent and documentation

**Files:**
- Create: `.opencode/agents/evidence-extraction-agent.md`
- Modify: `AGENTS.md`
- Create: `docs/opencode-evidence-extraction-agent.md`
- Test: `scripts/opencode/test-agent-skill-contract.mjs`

**Interfaces:**
- Agent accepts a screened literature project and produces a structured evidence table.
- Agent uses the four MCP tools from Task 2 and the three required Skills.

- [ ] Extend the contract test with the new Agent’s required Skill and MCP-tool names.
- [ ] Run the Node contract test and confirm it fails because the definition does not exist.
- [ ] Add the Agent definition with workflow order, evidence-basis constraints, human-review rules, and final output fields.
- [ ] Add a beginner-facing usage guide and update workspace workflow rules.
- [ ] Run the contract test and confirm it passes.

### Task 4: Implement writing draft records and MCP workflow

**Files:**
- Modify: `apps/literature-review-agent/backend/app/models.py`
- Modify: `apps/literature-review-agent/backend/app/schemas.py`
- Create: `apps/literature-review-agent/backend/app/services/research_writing.py`
- Modify: `apps/literature-review-agent/backend/app/mcp_server.py`
- Test: `apps/literature-review-agent/backend/tests/test_research_writing.py`

**Interfaces:**
- Produces MCP tools `start_research_writing_workflow`, `save_research_writing_draft`, `request_research_writing_approval`, `get_research_writing_approval_status`, and `export_research_writing_bundle`.
- Supports `protocol`, `proposal`, `methods`, and `discussion` document types.
- Requires valid Skill receipts before saving and external approval before export.

- [ ] Write a test that saves a protocol draft with the three base Skill receipts and confirms export is blocked before approval.
- [ ] Write a test that attempts to save a proposal without `research-proposal-generator` and expects rejection.
- [ ] Run `pytest tests/test_research_writing.py -q` and confirm failure because the service is absent.
- [ ] Implement writing source-manifest validation, versioned draft persistence, approval requests, protected approval status, and redaction-safe export.
- [ ] Register the MCP tools and run the focused tests until passing.

### Task 5: Create research-writing OpenCode Agent and documentation

**Files:**
- Create: `.opencode/agents/research-writing-agent.md`
- Modify: `AGENTS.md`
- Create: `docs/opencode-research-writing-agent.md`
- Test: `scripts/opencode/test-agent-skill-contract.mjs`

**Interfaces:**
- Agent uses a study-design project or evidence-export source manifest.
- Agent saves drafts through MCP and does not claim external approval.

- [ ] Extend the contract test with the writing Agent’s required Skills and MCP tools.
- [ ] Run the contract test and confirm failure because the Agent is absent.
- [ ] Add the Agent definition with document-specific Skill gates, source-only writing rules, explicit placeholders, and approval stop points.
- [ ] Add a beginner-facing usage guide and update workspace workflow rules.
- [ ] Run the contract test and confirm it passes.

### Task 6: Run and document two real workflows per Agent

**Files:**
- Create: `docs/two-evidence-extraction-agent-runs-2026-07-16.md`
- Create: `docs/two-research-writing-agent-runs-2026-07-16.md`
- Modify: `docs/medical-research-agent-goals.md`

**Interfaces:**
- Each document records project/run IDs, source limits, generated artifacts, export status, and the exact verified Skills.

- [ ] Run two evidence-extraction workflows on real PubMed-sourced citation records.
- [ ] Inspect database receipt rows and exported evidence tables; document exact skills, limitations, and status.
- [ ] Run two writing workflows using approved study-design projects or saved evidence tables.
- [ ] Inspect database receipt rows and exported draft bundles; document exact skills, limitations, and approval status.
- [ ] Run `pytest -q` and the Node Agent contract test; record results in both documents.

## Self-Review

- Spec coverage: Tasks 1-3 implement the first Agent and Tasks 4-5 implement the second; Task 6 proves two runs and receipt verification for each.
- Placeholder scan: no implementation task depends on an unspecified interface or an unspecified test command.
- Type consistency: both Agents use `project_id` and `workflow_run_id`; receipts are scoped to the same project and run before state-mutating tools execute.
