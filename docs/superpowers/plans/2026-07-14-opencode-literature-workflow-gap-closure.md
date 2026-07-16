# OpenCode Literature Workflow Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the shortest remaining gaps between the current OpenCode literature-review prototype and a fixed-structure, repeatable literature review workspace MVP.

**Architecture:** Reuse the existing FastAPI + SQLite backend as the single source of project truth, then expose the missing workflow actions as MCP tools so the OpenCode agents can create projects, generate search strategies, import citations, deduplicate records, and submit screening decisions without bypassing the backend state model. Keep the new workflow logic in a small shared service layer so both HTTP routes and MCP tools use the same business behavior.

**Tech Stack:** Python 3.14, FastAPI, SQLModel, MCP Python SDK (`FastMCP`), pytest, OpenCode local MCP

---

### Task 1: Add a shared workflow service layer

**Files:**
- Create: `apps/literature-review-agent/backend/app/services/project_workflow.py`
- Modify: `apps/literature-review-agent/backend/app/schemas.py`
- Modify: `apps/literature-review-agent/backend/app/main.py`
- Test: `apps/literature-review-agent/backend/tests/test_mcp_workflow.py`

- [ ] Add reusable workflow functions for project creation, search strategy generation, citation import, deduplication, and screening submission.
- [ ] Move the screening decision schema into `schemas.py` so HTTP routes and MCP tools share one payload shape.
- [ ] Update `main.py` to call the shared service layer instead of duplicating business logic in each route.

### Task 2: Expose the missing five MCP workflow tools

**Files:**
- Modify: `apps/literature-review-agent/backend/app/mcp_server.py`
- Modify: `apps/literature-review-agent/backend/app/services/citations.py`
- Test: `apps/literature-review-agent/backend/tests/test_mcp_workflow.py`

- [ ] Add `create_review_project`.
- [ ] Add `generate_project_search_strategy`.
- [ ] Add `import_citations_to_project`.
- [ ] Add `deduplicate_project_citations`.
- [ ] Add `submit_screening_decisions`.

### Task 3: Verify end-to-end local workflow behavior

**Files:**
- Modify: `docs/opencode-medical-research-skills-integration.md`
- Test: `apps/literature-review-agent/backend/tests/test_mcp_workflow.py`

- [ ] Add tests that execute the new MCP-callable workflow functions against the local SQLite database.
- [ ] Run the backend pytest suite.
- [ ] Confirm `opencode mcp list` still shows the local `literature_review` server connected.
- [ ] Update the integration doc with the new tool list and the remaining gap after this round.

### Task 4: Record the post-implementation status

**Files:**
- Modify: `docs/opencode-medical-research-skills-integration.md`

- [ ] Summarize what is now complete for the literature-review workspace MVP.
- [ ] Summarize what is still missing after the five workflow tools are added.
