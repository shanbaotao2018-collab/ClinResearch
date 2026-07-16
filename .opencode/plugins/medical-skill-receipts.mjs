import { createHmac, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
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
  "biomed-outline-generator",
  "method-writing",
  "discussion-section-architect",
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

export default async ({ directory }) => {
  const receiptKey = process.env.LRA_SKILL_RECEIPT_KEY;
  const writeQueueBySession = new Map();
  const receiptDirectory = join(directory, "runtime", "skill-receipts");

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
        await bindReceiptsToAgentWorkflow(input.sessionID, result?.workflow);
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
      if (!input.tool.startsWith("literature_review_")) return;
      const args = output.args ?? input.args;
      await bindReceiptsToWorkflow(
        input.sessionID,
        args?.project_id,
        args?.workflow_run_id,
      );
      if ([
        "literature_review_save_evidence_extractions",
        "literature_review_check_project_retractions",
        "literature_review_export_evidence_table",
      ].includes(input.tool)) {
        await bindReceiptsToAgentWorkflow(input.sessionID, {
          run_id: args?.workflow_run_id,
          workflow_type: "evidence_extraction",
          subject_type: "review",
          subject_id: args?.project_id,
        });
      }
      if ([
        "literature_review_save_research_writing_draft",
        "literature_review_request_research_writing_approval",
        "literature_review_export_research_writing_bundle",
      ].includes(input.tool)) {
        await bindReceiptsToAgentWorkflow(input.sessionID, {
          run_id: args?.workflow_run_id,
          workflow_type: "research_writing",
          subject_type: args?.source_type,
          subject_id: args?.source_id,
        });
      }
    },
  };
};
