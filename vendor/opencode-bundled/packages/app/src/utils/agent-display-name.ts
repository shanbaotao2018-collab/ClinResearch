const CLINRESEARCH_AGENT_NAMES: Record<string, string> = {
  "study-design": "研究设计（Study Design）",
  "literature-review": "文献检索与综述（Literature Review）",
  "evidence-extraction": "多源证据抽取分析（Evidence Extraction）",
  "research-writing": "科研写作（Research Writing）",
  search: "检索策略（Search）",
  screening: "文献初筛（Screening）",
}

// Keep stable English IDs for routing while presenting clinician-friendly labels.
export function agentDisplayName(name: string): string {
  return CLINRESEARCH_AGENT_NAMES[name] ?? name
}
