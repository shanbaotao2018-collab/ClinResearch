# Medical Research Agent Workspace

This repository contains experimental and MVP work for medical-domain agents, including:

- `apps/literature-review-agent/` for the FastAPI literature review backend
- `deploy/dify/literature-review-agent/` for the existing Dify-hosted MVP
- `vendor/medical-research-skills/` for the upstream AIPOCH skill library used in the OpenCode integration
- `.opencode/agents/` for project-local OpenCode agent definitions
- `.agents/skills/` for the curated project-local skill subset that OpenCode can discover directly

## Scope

This workspace is for medical research assistance, not clinical diagnosis or treatment advice.

Allowed:

- literature review planning
- search strategy drafting
- screening support
- evidence summarization
- research design support
- academic writing support

Not allowed:

- direct diagnosis or treatment advice
- final clinical decision-making for patient care
- fabricated citations, PMIDs, DOIs, trial names, or effect sizes
- presenting uncertain claims as confirmed facts

When evidence is missing, uncertain, or only abstract-level, state that explicitly.

## OpenCode Setup

Before using the OpenCode medical research agents in this repo:

1. Review the curated integration guide at `docs/opencode-medical-research-skills-integration.md`
2. Run `bash scripts/opencode/sync-medical-research-skills.sh` to populate `.agents/skills/`
3. Start OpenCode from the repository root so it can load:
   - this `AGENTS.md`
   - `.opencode/agents/*.md`
   - `.agents/skills/*/SKILL.md`

## Agent Workflow Rules

For literature review tasks, default to this sequence and do not skip available steps:

1. Clarify the research question
2. Structure the question into PICO or equivalent
3. Create a local review project record
4. Generate a project search strategy
5. Recommend databases and search approach
6. Retrieve candidate citations
7. Import citations into the local project
8. Deduplicate the project citation set
9. Review candidate citations
10. Submit screening decisions to the local project
11. Export the project bundle
12. Summarize evidence patterns and controversies
13. Draft a review outline

Do not skip clarification when the research question is ambiguous.

Do not treat screening suggestions as final inclusion/exclusion decisions unless the user explicitly confirms.

The local review project should be the system of record once it exists.

For clinical study-design tasks, default to this sequence:

1. Clarify the research objective, study type, resources, and PICO
2. Create a local study-design project record
3. Generate the reporting-standard blueprint
4. Draft eligibility criteria, outcomes, feasibility, and proposal outline
5. Save the draft content to the local project
6. Calculate basic two-group sample size with explicit assumptions
7. For an explicit RCT, save a randomization plan without generating allocations
8. Request external approval and wait for the protected approval endpoint to record it
9. After approval, generate the concealed schedule and export a redacted study-design bundle

The study-design project is the system of record once it exists. Do not claim that a protocol, sample-size calculation, or randomization schedule is final before external approval. Never place identifiable patient data in model prompts or MCP calls; provide only de-identified or aggregate research data.

For evidence-extraction tasks, use `evidence-extraction` only after review screening is complete. Extract only from the citation metadata, abstract, or a user-provided full-text excerpt and record the evidence basis for every row. Do not treat missing fields as negative findings. A PubMed notice lookup is a check-time status, not a permanent citation-safety guarantee. Require researcher review before any evidence row is used as a final conclusion.

For research-writing tasks, use `research-writing` only with a saved study-design project or a review project whose included citations all have evidence-extraction records. Persist a source manifest and unresolved items with every draft. Require external approval before export; never present a generated draft as an approved protocol, grant application, manuscript, or clinical conclusion.

## Output Rules

For literature review tasks, final outputs should be structured with these sections when applicable:

- Workflow Status
- Research Question
- PICO
- Search Strategy Draft
- Recommended Databases
- Retrieval Summary
- Screening Suggestions
- PRISMA Snapshot
- Evidence Summary
- Key Controversies
- Review Outline
- Next Steps

Prefer structured bullets or tables over long prose.

Always distinguish:

- verified vs inferred
- extracted vs suggested
- evidence vs interpretation

For the canonical output layout, follow:

- `docs/templates/literature-review-output-template.md`

## Human Confirmation Points

Require user confirmation before:

- finalizing a search strategy for operational use
- locking inclusion/exclusion criteria
- treating screening suggestions as final decisions
- generating a polished submission-style review summary
- finalizing a study-design bundle, sample-size assumptions, or an RCT randomization schedule

Use the `question` tool when the decision materially changes downstream outputs.

## Tooling Notes

- Prefer MCP literature search tools for retrieval once configured.
- Prefer project workflow MCP tools over free-form narration when advancing project state.
- Prefer project-local curated skills instead of loading the entire upstream skill library ad hoc.
- For study design, use the `study-design` Agent and its MCP tools; treat the sample-size MVP as limited to equal-allocation, two-group means or proportions.
- Avoid unnecessary file edits during research-only tasks unless the user explicitly asks for generated deliverables.
