# Evidence Extraction And Research Writing Agents Design

## Goal

Complete the remaining two medical-research-skills-backed business agents:

1. Literature screening and evidence extraction.
2. Research writing and proposal drafting.

Both agents must use the same design standard as the existing literature-review and study-design agents: a code-orchestrated workflow, explicit Skills, MCP business tools, project-local persistence, human review points, and verifiable Skill execution receipts.

## Architecture

The existing FastAPI and SQLite backend remains the single source of truth. The existing literature `Project` and `Citation` records are reused instead of creating parallel project systems.

Each new workflow has its own run record, event log, signed Skill receipt records, and structured output records. OpenCode Agent definitions orchestrate Skills and MCP tools. The model drafts structured content, while backend tools validate state transitions and prevent unsupported exports.

```text
OpenCode primary Agent
  -> skill tool: loads the required research method Skill
  -> MCP tool: starts a persisted workflow run
  -> MCP tool: saves validated structured artifacts
  -> MCP tool: exports a project artifact

OpenCode receipt plugin
  -> signs each required Skill call
  -> binds session receipts to the workflow run

Backend
  -> verifies required receipts before critical operations
  -> writes workflow events and project artifacts
```

This is the OpenAI Agents SDK cookbook pattern of a code-orchestrated `Workflow + Agent + Tools`, with guardrails and human-in-the-loop checkpoints. The Skills are not independent agents: they provide the professional method the primary Agent must apply before invoking business tools.

## Agent 1: Literature Screening And Evidence Extraction

### Inputs

- An existing literature review project.
- Citations screened as `include`, or a user-confirmed subset.
- Citation metadata, abstracts, and optionally user-supplied full-text excerpts.

### Required Skills

- `clinical-study-info-extractor`
- `methodology-extractor`
- `retraction-watcher` before evidence-table export

### Workflow

1. Confirm the project is screened and identify eligible citations.
2. Start an evidence-extraction workflow run.
3. Invoke the two extraction Skills.
4. Save one evidence extraction per eligible citation.
5. Explicitly label the evidence basis as `abstract`, `metadata`, or `full_text_excerpt`.
6. Invoke the retraction-watcher Skill and save one safety-check result per citation.
7. Export the evidence table only after all eligible citations have an extraction and a safety check.

### Structured Output

An extraction stores the study design, population, sample size, intervention or exposure, comparator, outcomes, effect estimates, methods summary, source basis, missing fields, and an explicit `needs_human_review` flag.

The backend never treats an absent abstract field as a negative finding. Unknown values must be persisted as `not_reported` or be represented in the missing-fields list. A safety check is a recorded check result, not a guarantee that a source is safe forever.

## Agent 2: Research Writing And Proposal Drafting

### Inputs

- An existing approved study-design project, or an exported evidence table from a literature project.
- A declared document type: `protocol`, `proposal`, `methods`, or `discussion`.
- Optional target audience and writing constraints.

### Required Skills

- `biomed-outline-generator`
- `method-writing`
- `discussion-section-architect`
- `research-proposal-generator` when document type is `proposal`

### Workflow

1. Confirm the source project and select a supported document type.
2. Start a writing workflow run.
3. Invoke required Skills.
4. Save a versioned writing draft with a source manifest.
5. Require human confirmation before marking a draft ready for external use.
6. Export the approved draft with its source manifest, limitations, and verified Skill receipts.

### Structured Output

Each draft stores an outline, methods draft, discussion framework, proposal content when applicable, limitations, unresolved items, and the exact project sources used. The Agent must not invent patient outcomes, effect estimates, citations, budgets, or preliminary findings; missing evidence is a visible placeholder and a human-review item.

## Shared Integrity Requirements

- The receipt plugin signs all required evidence and writing Skills using the existing `LRA_SKILL_RECEIPT_KEY` mechanism.
- The backend verifies receipt signatures before saving critical content and exporting final artifacts.
- The Agent cannot create human approvals itself.
- Workflow event logs store input and output digests, not raw sensitive content.
- The existing PHI prohibition applies to all prompts and MCP calls.

## Verification

For each Agent, provide two medically realistic workflow tests, including a successful export and explicit inspection of signed Skill receipts. The automated test suite must also cover a missing-receipt rejection and a no-fabrication constraint for unsupported source fields.

## Non-Goals

- Full-text PDF parsing, automatic NOS/Cochrane scoring, or formal meta-analysis.
- A guarantee that a paper is never retracted after a recorded check.
- Final clinical, statistical, ethical, or publication decisions.
