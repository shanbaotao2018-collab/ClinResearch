import { useEffect, useState } from "react";
import { api, type Overview, type ProjectSummary } from "./api";

type Selection = { type: "study" | "review" | "writing"; id: number } | null;

const statusLabel: Record<string, string> = {
  draft: "草稿",
  blueprint_ready: "蓝图已生成",
  content_drafted: "内容已起草",
  sample_size_ready: "样本量已完成",
  approval_pending: "等待确认",
  approved: "已批准",
  human_approved: "人工已批准",
  randomization_ready: "随机化已生成",
  exported: "已导出",
  search_strategy_ready: "检索式已生成",
  screening_completed: "筛选完成",
  pending: "等待确认",
};

function readableStatus(status?: string) {
  return statusLabel[status ?? ""] ?? status ?? "未知";
}

function displayTime(value?: string) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function text(value: unknown) {
  if (value === null || value === undefined || value === "") return "未填写";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function Status({ value }: { value?: string }) {
  return <span className={`status status-${value ?? "unknown"}`}>{readableStatus(value)}</span>;
}

async function downloadArtifact(path: string, fallbackName: string) {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `导出失败：${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fallbackName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <article className={`metric ${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
  </article>;
}

function ProjectRow({ item, type, selected, onSelect }: {
  item: ProjectSummary;
  type: "study" | "review";
  selected: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const active = selected?.type === type && selected.id === item.id;
  return (
    <button className={`project-row ${active ? "active" : ""}`} onClick={() => onSelect({ type, id: item.id })}>
      <span className="project-row-kicker">{type === "study" ? "研究设计" : "文献与证据"} · #{item.id}</span>
      <strong>{item.title}</strong>
      <div className="project-row-footer"><Status value={item.status} /><span>{displayTime(item.updated_at)}</span></div>
    </button>
  );
}

function Detail({ selection }: { selection: Selection }) {
  const [data, setData] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selection) return;
    let live = true;
    setLoading(true);
    setError(null);
    setData(null);
    const reader = selection.type === "study" ? api.study : selection.type === "review" ? api.review : api.writing;
    reader(selection.id)
      .then((result) => { if (live) setData(result); })
      .catch((reason: Error) => { if (live) setError(reason.message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [selection]);

  if (!selection) {
    return <section className="empty-detail"><p className="eyebrow">项目查看器</p><h2>选择左侧项目，查看完整科研过程</h2><p>每个项目都可回溯到结构化输入、Skills、工具调用、审批与审计记录。</p></section>;
  }
  if (loading) return <section className="empty-detail"><p className="eyebrow">正在读取</p><h2>加载项目事实记录...</h2></section>;
  if (error || !data) return <section className="empty-detail error"><p className="eyebrow">读取异常</p><h2>{error ?? "没有找到项目"}</h2></section>;

  if (selection.type === "study") return <StudyDetail data={data} />;
  if (selection.type === "review") return <ReviewDetail data={data} />;
  return <WritingDetail data={data} />;
}

function StudyDetail({ data }: { data: Record<string, any> }) {
  const project = data.project;
  const sample = data.sample_size ?? {};
  const randomization = data.randomization ?? {};
  return <section className="detail">
    <header className="detail-header"><div><p className="eyebrow">研究设计 Agent · #{project.id}</p><h2>{project.title}</h2><p>{project.research_question}</p></div><Status value={project.status} /></header>
    <div className="notice">随机分配序列受保护保存。工作台仅显示随机化计划与生成状态。</div>
    <ExportCenter title="方案工作包" description="导出内容不包含实际随机分配序列。" paths={{ markdown: `/workbench/study-design-projects/${project.id}/export?format=markdown`, json: `/workbench/study-design-projects/${project.id}/export?format=json` }} />
    <div className="fact-grid">
      <Fact title="PICO 人群" value={project.population} /><Fact title="干预 / 对照" value={`${text(project.intervention)} / ${text(project.comparator)}`} />
      <Fact title="主要结局" value={project.primary_outcome || project.outcome} /><Fact title="研究设计" value={`${project.study_type} · ${project.study_design}`} />
      <Fact title="纳入标准" value={project.inclusion_criteria} /><Fact title="排除标准" value={project.exclusion_criteria} />
      <Fact title="样本量" value={sample.result} code /><Fact title="随机化计划" value={randomization.plan} code />
    </div>
    <EvidenceStrip title="审批状态" items={[data.approval]} />
    <Timeline title="工作流审计" items={data.audit_logs} />
    <SkillList items={data.skill_receipts} />
  </section>;
}

function ReviewDetail({ data }: { data: Record<string, any> }) {
  const project = data.project;
  const prisma = data.prisma ?? {};
  const evidence = data.evidence ?? {};
  const latestEvidenceRun = evidence.workflow_runs?.[0];
  const latestEvidenceApproval = evidence.approvals?.find((item: any) => item.workflow_run_id === latestEvidenceRun?.run_id);
  return <section className="detail">
    <header className="detail-header"><div><p className="eyebrow">文献检索与综述 Agent · #{project.id}</p><h2>{project.title}</h2><p>{project.research_question}</p></div><Status value={project.status} /></header>
    <ExportCenter title="文献综述项目包" description="包含检索式、题录、PRISMA 与审计记录。" paths={{ markdown: `/workbench/review-projects/${project.id}/export?format=markdown`, json: `/workbench/review-projects/${project.id}/export?format=json` }} />
    {latestEvidenceRun ? <ExportCenter title="系统评价证据包" description={latestEvidenceApproval?.status === "approved" ? "已批准，可导出全文证据、质量评价与 Meta 分析。" : "等待人工批准后才能导出。"} status={latestEvidenceApproval?.status ?? "pending"} paths={{ markdown: `/workbench/review-projects/${project.id}/evidence-workflows/${latestEvidenceRun.run_id}/export?format=markdown`, json: `/workbench/review-projects/${project.id}/evidence-workflows/${latestEvidenceRun.run_id}/export?format=json` }} disabled={latestEvidenceApproval?.status !== "approved"} /> : null}
    <div className="prisma-grid">
      <Metric label="识别文献" value={prisma.identified_count ?? 0} tone="sea" /><Metric label="去重后" value={prisma.deduplicated_count ?? 0} tone="sand" />
      <Metric label="已筛选" value={prisma.screened_count ?? 0} tone="mint" /><Metric label="已纳入" value={prisma.included_count ?? 0} tone="coral" />
    </div>
    <Section title="检索策略" items={data.search_strategies} fields={["source", "version_number", "query_text", "rationale"]} />
    <Section title={`题录记录 (${data.citations?.length ?? 0})`} items={data.citations} fields={["title", "authors", "publication_year", "doi", "source"]} />
    <Section title={`证据抽取 (${evidence.extractions?.length ?? 0})`} items={evidence.extractions} fields={["citation_id", "study_design", "population", "outcomes", "evidence_basis", "needs_human_review"]} />
    <Section title={`偏倚风险评估 (${evidence.bias_assessments?.length ?? 0})`} items={evidence.bias_assessments} fields={["citation_id", "instrument", "overall_judgement", "needs_human_review"]} />
    <Section title={`Meta 分析 (${evidence.meta_analyses?.length ?? 0})`} items={evidence.meta_analyses} fields={["outcome_label", "effect_measure", "model", "result", "needs_human_review"]} />
    <EvidenceStrip title="系统评价审批" items={evidence.approvals} />
    <Section title={`科研写作草稿 (${data.writing_drafts?.length ?? 0})`} items={data.writing_drafts} fields={["id", "title", "document_type", "status", "version_number"]} />
    <Timeline title="项目审计" items={data.audit_logs} />
    <SkillList items={data.skill_receipts} />
  </section>;
}

function WritingDetail({ data }: { data: Record<string, any> }) {
  return <section className="detail">
    <header className="detail-header"><div><p className="eyebrow">科研写作 Agent · 草稿 #{data.id}</p><h2>{data.title}</h2><p>来源类型：{data.source_type} #{data.source_id} · 版本 {data.version_number}</p></div><Status value={data.status} /></header>
    <ExportCenter title="科研写作草稿包" description={data.approval?.status === "approved" ? "已批准，可导出带来源清单的版本化草稿。" : "等待人工批准后才能导出。"} status={data.approval?.status ?? "pending"} paths={{ markdown: `/workbench/research-writing-drafts/${data.id}/export?format=markdown`, json: `/workbench/research-writing-drafts/${data.id}/export?format=json` }} disabled={data.approval?.status !== "approved"} />
    <EvidenceStrip title="审批状态" items={[data.approval]} />
    <Section title="来源清单" items={data.source_manifest} fields={["source_type", "source_id", "description"]} />
    <Fact title="写作大纲" value={data.outline} />
    <Fact title="方法草稿" value={data.methods_draft} />
    <Fact title="讨论框架" value={data.discussion_framework} />
    <Fact title="局限性" value={data.limitations} />
    <Fact title="未解决项" value={data.unresolved_items} />
    <Timeline title="工作流审计" items={data.workflow_events} />
    <SkillList items={data.skill_receipts} />
  </section>;
}

function Fact({ title, value, code = false }: { title: string; value: unknown; code?: boolean }) {
  return <article className={`fact ${code ? "code" : ""}`}><span>{title}</span><div>{text(value)}</div></article>;
}

function ExportCenter({ title, description, paths, status, disabled = false }: { title: string; description: string; paths: { markdown: string; json: string }; status?: string; disabled?: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const download = (format: "markdown" | "json") => {
    setError(null);
    downloadArtifact(paths[format], `${title}.${format === "markdown" ? "md" : "json"}`).catch((reason: Error) => setError(reason.message));
  };
  return <section className="export-center"><div><p className="eyebrow">导出中心</p><h3>{title}</h3><p>{description}</p>{error ? <p className="export-error">{error}</p> : null}</div><div className="export-actions">{status ? <Status value={status} /> : null}<button disabled={disabled} onClick={() => download("markdown")}>下载 Markdown</button><button className="secondary" disabled={disabled} onClick={() => download("json")}>下载 JSON</button></div></section>;
}

function EvidenceStrip({ title, items }: { title: string; items?: any[] }) {
  const records = (items ?? []).filter(Boolean);
  return <section className="strip"><h3>{title}</h3>{records.length === 0 ? <p>暂无记录</p> : records.map((item, index) => <div className="approval" key={index}><Status value={item.status} /><span>申请：{displayTime(item.requested_at)}</span><span>审批人：{item.approved_by || "待处理"}</span><code>{item.scope_digest?.slice(0, 16) ?? "-"}...</code></div>)}</section>;
}

function Section({ title, items, fields }: { title: string; items?: any[]; fields: string[] }) {
  const records = items ?? [];
  return <section className="section"><h3>{title}</h3>{records.length === 0 ? <p className="muted">暂无已保存记录</p> : <div className="records">{records.map((item, index) => <article className="record" key={item.id ?? index}>{fields.map((field) => <div key={field}><span>{field}</span><p>{text(item[field])}</p></div>)}</article>)}</div>}</section>;
}

function Timeline({ title, items }: { title: string; items?: any[] }) {
  const records = items ?? [];
  return <section className="section"><h3>{title}</h3>{records.length === 0 ? <p className="muted">暂无审计记录</p> : <ol className="timeline">{records.slice(0, 12).map((item, index) => <li key={item.id ?? index}><strong>{item.action || item.operation}</strong><p>{item.summary || "已记录一次工作流操作"}</p><span>{item.actor || "agent"} · {displayTime(item.created_at)}</span></li>)}</ol>}</section>;
}

function SkillList({ items }: { items?: any[] }) {
  const skills = [...new Set((items ?? []).map((item) => item.skill_name).filter(Boolean))];
  return <section className="skills"><h3>已验证的 Skill 执行回执</h3>{skills.length ? skills.map((name) => <span key={name}>{name}</span>) : <p className="muted">当前项目没有保存的 Skill 回执</p>}</section>;
}

export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then((result) => { setOverview(result); const first = result.study_design_projects[0] ?? result.review_projects[0]; if (first) setSelection({ type: first.agent_type === "study_design" ? "study" : "review", id: first.id }); }).catch((reason: Error) => setError(reason.message));
  }, []);

  if (error) return <main className="app loading"><p className="eyebrow">连接失败</p><h1>{error}</h1><p>请确认 FastAPI 后端运行在 <code>127.0.0.1:8010</code>。</p></main>;
  if (!overview) return <main className="app loading"><p className="eyebrow">临床科研智能体工作台</p><h1>正在加载已保存的科研项目...</h1></main>;

  const summary = overview.summary;
  return <main className="app">
    <header className="masthead"><div><p className="eyebrow">Clinical Research Agents</p><h1>临床科研智能体工作台</h1><p>四类科研智能体的项目事实、过程留痕与人工确认，统一在这里查看。</p></div><div className="masthead-note"><span>只读 P0</span><strong>项目事实来自本地 SQLite</strong></div></header>
    <section className="metric-grid"><Metric label="研究设计项目" value={summary.study_design_projects} tone="sea" /><Metric label="文献综述项目" value={summary.review_projects} tone="mint" /><Metric label="证据工作流" value={summary.evidence_workflows} tone="sand" /><Metric label="科研写作草稿" value={summary.writing_drafts} tone="coral" /></section>
    <section className="workspace">
      <aside className="sidebar"><div className="sidebar-head"><div><p className="eyebrow">项目导航</p><h2>已保存项目</h2></div><span className="pending-count">{summary.pending_approvals} 待确认</span></div>
        <h3>临床研究设计</h3>{overview.study_design_projects.length ? overview.study_design_projects.map((item) => <ProjectRow key={item.id} item={item} type="study" selected={selection} onSelect={setSelection} />) : <p className="muted">暂无项目</p>}
        <h3>文献、证据与写作</h3>{overview.review_projects.length ? overview.review_projects.map((item) => <ProjectRow key={item.id} item={item} type="review" selected={selection} onSelect={setSelection} />) : <p className="muted">暂无项目</p>}
        <h3>科研写作草稿</h3>{overview.writing_drafts?.length ? overview.writing_drafts.map((item) => <button className={`project-row ${selection?.type === "writing" && selection.id === item.id ? "active" : ""}`} key={item.id} onClick={() => setSelection({ type: "writing", id: item.id })}><span className="project-row-kicker">{item.document_type} · 草稿 #{item.id} · v{item.version_number}</span><strong>{item.title}</strong><div className="project-row-footer"><Status value={item.status} /><span>{displayTime(item.updated_at)}</span></div></button>) : <p className="muted">暂无草稿</p>}
        <div className="pending"><p className="eyebrow">人工确认</p><h3>待办审批</h3>{overview.pending_approvals.length ? overview.pending_approvals.slice(0, 5).map((item, index) => <div className="pending-row" key={index}><Status value={item.status} /><span>{item.kind} #{item.id}</span></div>) : <p className="muted">没有待确认事项</p>}</div>
      </aside>
      <Detail selection={selection} />
    </section>
  </main>;
}
