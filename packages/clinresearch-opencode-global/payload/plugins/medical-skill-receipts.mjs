import { createHmac, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

const MEDICAL_SKILLS = new Set([
  "phi-prompt-guard",
  "clinic-research-design",
  "inclusion-criteria-gen",
  "research-proposal-generator",
  "biomed-outline-generator",
  "method-writing",
  "sample-size-basic",
  "randomization-gen",
  "clinical-study-info-extractor",
  "methodology-extractor",
  "retraction-watcher",
  "fulltext-fetcher",
  "pdf-extract",
  "baseline-extraction-for-clinical-trials",
  "outcome-extraction-for-clinical-trials",
  "meta-screening-fulltext",
  "meta-analysis",
  "meta-forest-binary-plot",
  "rct-bias-assessment-rob",
  "cohort-study-quality-assessment-nos",
  "diagnostic-study-quality-assessment-quadas",
  "biomed-outline-generator",
  "method-writing",
  "discussion-section-architect",
]);

const STUDY_DESIGN_WORKFLOW_TOOLS = new Set([
  "literature_review_generate_study_design_blueprint",
  "literature_review_save_study_design_content",
  "literature_review_calculate_study_sample_size",
  "literature_review_save_rct_randomization_plan",
  "literature_review_request_study_design_approval",
  "literature_review_get_study_design_approval_status",
  "literature_review_finalize_study_design",
  "literature_review_generate_rct_randomization_schedule",
  "literature_review_export_study_design_bundle",
]);

const EVIDENCE_WORKFLOW_TOOLS = new Set([
  "literature_review_save_evidence_extractions",
  "literature_review_check_project_retractions",
  "literature_review_save_project_retraction_checks",
  "literature_review_export_evidence_table",
  "literature_review_save_full_text_documents",
  "literature_review_fetch_and_save_open_access_full_text",
  "literature_review_save_full_text_evidence_details",
  "literature_review_save_bias_assessments",
  "literature_review_run_binary_meta_analysis",
  "literature_review_request_systematic_evidence_review",
  "literature_review_confirm_systematic_evidence_phase_start",
  "literature_review_get_systematic_evidence_review_status",
  "literature_review_export_systematic_evidence_bundle",
]);

function signature(secret, receipt) {
  return createHmac("sha256", secret)
    .update(`${receipt.receipt_id}|${receipt.opencode_session_id}|${receipt.skill_name}|${receipt.executed_at_ms}`)
    .digest("hex");
}

function parseToolOutput(output) {
  if (typeof output !== "string") return output;
  try {
    return JSON.parse(output);
  } catch {
    return undefined;
  }
}

async function readReceipts(path) {
  try {
    const payload = JSON.parse(await readFile(path, "utf8"));
    return Array.isArray(payload.receipts) ? payload.receipts : [];
  } catch {
    return [];
  }
}

async function writeReceiptJournal(path, payload) {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify(payload), { encoding: "utf8", mode: 0o600 });
  await rename(temporary, path);
}

async function resolveBackendUrl() {
  if (process.env.LRA_BACKEND_URL) return process.env.LRA_BACKEND_URL;
  const configDir = process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config");
  try {
    const config = JSON.parse(await readFile(join(configDir, "opencode", "opencode.json"), "utf8"));
    const url = config?.mcp?.literature_review?.url;
    return typeof url === "string" ? url : undefined;
  } catch {
    return undefined;
  }
}

function resolveOpenCodeConfigDir() {
  return join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "opencode");
}

export default async ({ directory }) => {
  const configDir = resolveOpenCodeConfigDir();
  const receiptKey = process.env.LRA_SKILL_RECEIPT_KEY
    ?? await readFile(join(configDir, "clinresearch-skill-receipt-key"), "utf8")
      .then((value) => value.trim())
      .catch(() => undefined)
    ?? await readFile(join(directory, "runtime", ".skill-receipt-key"), "utf8")
      .then((value) => value.trim())
      .catch(() => undefined);
  const writeQueueBySession = new Map();
  const activeAgentWorkflows = new Map();
  // Global installations must not depend on the user-selected workspace.
  const receiptDirectory = join(configDir, "clinresearch-skill-receipts");
  const backendUrl = await resolveBackendUrl();

  function enqueue(sessionID, operation) {
    const previous = writeQueueBySession.get(sessionID) ?? Promise.resolve();
    const next = previous.catch(() => undefined).then(operation);
    writeQueueBySession.set(sessionID, next);
    return next;
  }

  async function bindReceiptsToWorkflow(sessionID, projectId, workflowRunId) {
    if (!workflowRunId || !projectId) return;
    await (writeQueueBySession.get(sessionID) ?? Promise.resolve());
    await mkdir(receiptDirectory, { recursive: true, mode: 0o700 });
    const sessionPath = join(receiptDirectory, `session-${sessionID}.json`);
    const receipts = await readReceipts(sessionPath);
    if (receipts.length === 0) return;
    await writeReceiptJournal(join(receiptDirectory, `${workflowRunId}.json`), {
      version: 1,
      workflow_run_id: workflowRunId,
      study_design_project_id: projectId,
      opencode_session_id: sessionID,
      receipts,
    });
  }

  async function bindReceiptsToAgentWorkflow(sessionID, workflow) {
    if (!workflow?.run_id || !workflow?.workflow_type || !workflow?.subject_type || !workflow?.subject_id) return;
    await (writeQueueBySession.get(sessionID) ?? Promise.resolve());
    await mkdir(receiptDirectory, { recursive: true, mode: 0o700 });
    const sessionPath = join(receiptDirectory, `session-${sessionID}.json`);
    const receipts = await readReceipts(sessionPath);
    if (receipts.length === 0) return;
    await writeReceiptJournal(join(receiptDirectory, `${workflow.run_id}.json`), {
      version: 1,
      workflow_run_id: workflow.run_id,
      workflow_type: workflow.workflow_type,
      subject_type: workflow.subject_type,
      subject_id: workflow.subject_id,
      opencode_session_id: sessionID,
      receipts,
    });
    if (!backendUrl) return;
    const endpoint = new URL("/agent-workflows/skill-receipts", backendUrl).toString();
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        version: 1,
        workflow_run_id: workflow.run_id,
        workflow_type: workflow.workflow_type,
        subject_type: workflow.subject_type,
        subject_id: workflow.subject_id,
        opencode_session_id: sessionID,
        receipts,
      }),
    });
    if (!response.ok) {
      throw new Error(`ClinResearch backend rejected Skill receipts (${response.status})`);
    }
  }

  return {
    "tool.execute.after": async (input, output) => {
      if (!receiptKey) return;

      if (input.tool === "skill" && MEDICAL_SKILLS.has(input.args?.name)) {
        await enqueue(input.sessionID, async () => {
          await mkdir(receiptDirectory, { recursive: true, mode: 0o700 });
          const receipt = {
            receipt_id: randomUUID(),
            opencode_session_id: input.sessionID,
            skill_name: input.args.name,
            executed_at_ms: Date.now(),
          };
          receipt.signature = signature(receiptKey, receipt);
          const sessionPath = join(receiptDirectory, `session-${input.sessionID}.json`);
          const pending = await readReceipts(sessionPath);
          pending.push(receipt);
          await writeReceiptJournal(sessionPath, {
            version: 1,
            opencode_session_id: input.sessionID,
            receipts: pending,
          });
        });
        const workflow = activeAgentWorkflows.get(input.sessionID);
        if (workflow) await bindReceiptsToAgentWorkflow(input.sessionID, workflow);
        return;
      }

      const result = parseToolOutput(output.output);
      if (input.tool === "literature_review_create_study_design_project") {
        const workflowRunId = result?.workflow?.run_id;
        const projectId = result?.project?.id;
        await bindReceiptsToWorkflow(input.sessionID, projectId, workflowRunId);
        return;
      }

      if ([
        "literature_review_start_evidence_extraction_workflow",
        "literature_review_start_research_writing_workflow",
      ].includes(input.tool)) {
        if (result?.workflow) {
          activeAgentWorkflows.set(input.sessionID, result.workflow);
          await bindReceiptsToAgentWorkflow(input.sessionID, result.workflow);
        }
      }
    },
    "tool.execute.before": async (input, output) => {
      if (input.tool === "literature_review_create_study_design_project") {
        output.args.opencode_session_id = input.sessionID;
        return;
      }
      if ([
        "literature_review_start_evidence_extraction_workflow",
        "literature_review_start_research_writing_workflow",
      ].includes(input.tool)) {
        output.args.opencode_session_id = input.sessionID;
        return;
      }
      const args = output.args ?? input.args;
      if (STUDY_DESIGN_WORKFLOW_TOOLS.has(input.tool)) {
        await bindReceiptsToWorkflow(
          input.sessionID,
          args?.project_id,
          args?.workflow_run_id,
        );
        return;
      }
      if (EVIDENCE_WORKFLOW_TOOLS.has(input.tool)) {
        const workflow = {
          run_id: args?.workflow_run_id,
          workflow_type: "evidence_extraction",
          subject_type: "review",
          subject_id: args?.project_id,
        };
        activeAgentWorkflows.set(input.sessionID, workflow);
        await bindReceiptsToAgentWorkflow(input.sessionID, workflow);
      }
      if ([
        "literature_review_save_research_writing_draft",
        "literature_review_request_research_writing_approval",
        "literature_review_export_research_writing_bundle",
      ].includes(input.tool)) {
        const workflow = {
          run_id: args?.workflow_run_id,
          workflow_type: "research_writing",
          subject_type: args?.source_type,
          subject_id: args?.source_id,
        };
        activeAgentWorkflows.set(input.sessionID, workflow);
        await bindReceiptsToAgentWorkflow(input.sessionID, workflow);
      }
    },
  };
};
