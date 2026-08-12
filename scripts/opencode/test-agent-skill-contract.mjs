import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);
const [primary, search, screening, studyDesign, evidenceExtraction, researchWriting] = await Promise.all([
  readFile(new URL(".opencode/agents/literature-review.md", root), "utf8"),
  readFile(new URL(".opencode/agents/search.md", root), "utf8"),
  readFile(new URL(".opencode/agents/screening.md", root), "utf8"),
  readFile(new URL(".opencode/agents/study-design.md", root), "utf8"),
  readFile(new URL(".opencode/agents/evidence-extraction.md", root), "utf8"),
  readFile(new URL(".opencode/agents/research-writing.md", root), "utf8"),
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
  "generate_study_design_blueprint",
  "save_study_design_content",
  "calculate_study_sample_size",
  "save_rct_randomization_plan",
  "finalize_study_design",
  "get_study_design_approval_status",
]) {
  assert.match(studyDesign, new RegExp(tool));
}

assert.match(studyDesign, /phi-prompt-guard/);
assert.match(studyDesign, /OpenCode must show one native Allow\/Deny confirmation/i);
assert.doesNotMatch(studyDesign, /confirm_study_design/);

for (const skill of [
  "clinical-study-info-extractor",
  "methodology-extractor",
  "retraction-watcher",
  "meta-screening-fulltext",
  "baseline-extraction-for-clinical-trials",
  "outcome-extraction-for-clinical-trials",
  "meta-analysis",
  "meta-forest-binary-plot",
]) {
  assert.match(evidenceExtraction, new RegExp(`must invoke[\\s\\S]*${skill}`, "i"));
}

for (const tool of [
  "start_evidence_extraction_workflow",
  "save_evidence_extractions",
  "check_project_retractions",
  "export_evidence_table",
  "save_full_text_documents",
  "save_full_text_evidence_details",
  "save_bias_assessments",
  "run_binary_meta_analysis",
  "request_systematic_evidence_review",
  "get_systematic_evidence_review_status",
  "export_systematic_evidence_bundle",
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
assert.match(researchWriting, /approve_research_writing/);
assert.match(researchWriting, /OpenCode will show an\s+Allow\/Deny confirmation/i);

console.log("Medical research agent skill contracts are enforced.");
