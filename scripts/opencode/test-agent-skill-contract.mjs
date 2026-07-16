import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);
const [primary, search, screening, studyDesign, evidenceExtraction, researchWriting] = await Promise.all([
  readFile(new URL(".opencode/agents/literature-review.md", root), "utf8"),
  readFile(new URL(".opencode/agents/search-agent.md", root), "utf8"),
  readFile(new URL(".opencode/agents/screening-agent.md", root), "utf8"),
  readFile(new URL(".opencode/agents/study-design-agent.md", root), "utf8"),
  readFile(new URL(".opencode/agents/evidence-extraction-agent.md", root), "utf8"),
  readFile(new URL(".opencode/agents/research-writing-agent.md", root), "utf8"),
]);

for (const skill of ["pubmed-search-specialist", "reference-search"]) {
  assert.match(search, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

for (const skill of ["systematic-review-screener", "literature-filtering"]) {
  assert.match(screening, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

assert.match(primary, /Skills Applied/i);
assert.match(primary, /do not accept a delegated result/i);

for (const skill of [
  "clinic-research-design",
  "inclusion-criteria-gen",
  "research-proposal-generator",
]) {
  assert.match(studyDesign, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

for (const tool of [
  "create_study_design_project",
  "calculate_study_sample_size",
  "save_rct_randomization_plan",
  "request_study_design_approval",
  "get_study_design_approval_status",
  "export_study_design_bundle",
]) {
  assert.match(studyDesign, new RegExp(tool));
}

assert.match(studyDesign, /phi-prompt-guard/);
assert.doesNotMatch(studyDesign, /confirm_study_design/);

for (const skill of [
  "clinical-study-info-extractor",
  "methodology-extractor",
  "retraction-watcher",
]) {
  assert.match(evidenceExtraction, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

for (const tool of [
  "start_evidence_extraction_workflow",
  "save_evidence_extractions",
  "check_project_retractions",
  "export_evidence_table",
]) {
  assert.match(evidenceExtraction, new RegExp(tool));
}

assert.match(evidenceExtraction, /not_reported/);

for (const skill of [
  "biomed-outline-generator",
  "method-writing",
  "discussion-section-architect",
  "research-proposal-generator",
]) {
  assert.match(researchWriting, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

for (const tool of [
  "start_research_writing_workflow",
  "get_research_writing_source",
  "save_research_writing_draft",
  "request_research_writing_approval",
  "get_research_writing_approval_status",
  "export_research_writing_bundle",
]) {
  assert.match(researchWriting, new RegExp(tool));
}

assert.match(researchWriting, /source_manifest/);
assert.doesNotMatch(researchWriting, /approve_research_writing/);

console.log("Medical research agent skill contracts are enforced.");
