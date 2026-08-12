#!/usr/bin/env node
// Minimal dependency-free stdio MCP server bundled with the desktop app.
// It retrieves public metadata only; project data stays in the central backend.
import readline from "node:readline"
import { randomUUID } from "node:crypto"
import { mkdir, rename, writeFile } from "node:fs/promises"
import path from "node:path"

const TOOL_DEFINITIONS = [
  {
    name: "client_get_literature_access_status",
    description: "Describe desktop-local PubMed and Europe PMC retrieval capability.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "client_search_pubmed",
    description: "Search PubMed from the desktop-local network and return normalized citation metadata.",
    inputSchema: { type: "object", properties: { query: { type: "string" }, limit: { type: "integer", minimum: 1, maximum: 20 } }, required: ["query"] },
  },
  {
    name: "client_search_europepmc",
    description: "Search Europe PMC from the desktop-local network and return normalized citation metadata.",
    inputSchema: { type: "object", properties: { query: { type: "string" }, limit: { type: "integer", minimum: 1, maximum: 20 } }, required: ["query"] },
  },
  {
    name: "client_retrieve_pubmed_formal_review",
    description: "Page every PubMed result into the ClinResearch project backend for a formal review. Returns audit counts, not a model-selected shortlist.",
    inputSchema: { type: "object", properties: { project_id: { type: "integer", minimum: 1 }, query: { type: "string" }, max_records: { type: "integer", minimum: 1, maximum: 2000, default: 2000 } }, required: ["project_id", "query"] },
  },
  {
    name: "client_retrieve_europepmc_formal_review",
    description: "Page every Europe PMC result into the ClinResearch project backend for a formal review. Returns audit counts, not a model-selected shortlist.",
    inputSchema: { type: "object", properties: { project_id: { type: "integer", minimum: 1 }, query: { type: "string" }, max_records: { type: "integer", minimum: 1, maximum: 2000, default: 2000 } }, required: ["project_id", "query"] },
  },
  {
    name: "client_check_pubmed_retractions",
    description: "Check PubMed retraction, correction, and expression-of-concern notice types from the desktop-local network.",
    inputSchema: { type: "object", properties: { pmids: { type: "array", items: { type: "string", pattern: "^[0-9]+$" }, minItems: 1, maxItems: 50 } }, required: ["pmids"] },
  },
  {
    name: "client_start_europepmc_open_access_preflight_job",
    description: "Start a background Europe PMC open-access full-text preflight job. Returns immediately with a task ID; use the status tool to monitor progress.",
    inputSchema: { type: "object", properties: { project_id: { type: "integer", minimum: 1 }, workspace_dir: { type: "string", description: "Optional absolute OpenCode workspace path. Full texts are cached beneath this directory." }, citations: { type: "array", minItems: 1, maxItems: 100, items: { type: "object", properties: { citation_id: { type: "integer", minimum: 1 }, pmid: { type: "string", pattern: "^[0-9]+$" }, doi: { type: "string" } }, required: ["citation_id", "pmid"] } } }, required: ["project_id", "citations"] },
  },
  {
    name: "client_get_europepmc_open_access_preflight_job",
    description: "Read progress for a background Europe PMC open-access full-text preflight job. Returns counts and recent statuses only, never XML.",
    inputSchema: { type: "object", properties: { task_id: { type: "string" } }, required: ["task_id"] },
  },
]

const BACKEND_URL = (process.env.LRA_BACKEND_URL || "http://127.0.0.1:8010").replace(/\/$/, "")
const FORMAL_RETRIEVAL_MAX_RECORDS = 2000
const FORMAL_RETRIEVAL_PAGE_SIZE = 100
const PUBMED_ONLY_DEMO_MODE = ["1", "true", "yes"].includes(String(process.env.LRA_PUBMED_ONLY_DEMO || "").toLowerCase())
const PREFLIGHT_JOB_BATCH_SIZE = 2
const PREFLIGHT_JOBS = new Map()
const clean = (value) => value ? value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : null
const tag = (xml, name) => clean(xml.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)</${name}>`, "i"))?.[1])
const bounded = (value) => Math.max(1, Math.min(Number.isInteger(value) ? value : 5, 20))
const boundedFormal = (value) => {
  const normalized = Number.isInteger(value) ? value : FORMAL_RETRIEVAL_MAX_RECORDS
  if (normalized < 1 || normalized > FORMAL_RETRIEVAL_MAX_RECORDS) {
    throw new Error(`max_records must be between 1 and ${FORMAL_RETRIEVAL_MAX_RECORDS}`)
  }
  return normalized
}

function availableToolDefinitions() {
  if (!PUBMED_ONLY_DEMO_MODE) return TOOL_DEFINITIONS
  // Europe PMC remains available only as an OA full-text resolver after
  // screening; it is deliberately excluded from demo retrieval and PRISMA.
  return TOOL_DEFINITIONS.filter((tool) => ![
    "client_search_europepmc",
    "client_retrieve_europepmc_formal_review",
  ].includes(tool.name))
}

async function fetchWithRetry(url, options = {}, attempts = 2, timeoutMs = 18000) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(url, { ...options, signal: controller.signal })
      if (response.status < 500 || attempt === attempts) return response
      lastError = new Error(`HTTP ${response.status}`)
    } catch (error) {
      lastError = error
      if (attempt === attempts) throw error
    } finally {
      clearTimeout(timeout)
    }
    await new Promise((resolve) => setTimeout(resolve, 400 * attempt))
  }
  throw lastError ?? new Error("Request failed")
}

async function pubmedPage(query, pageSize, offset = 0, requestPolicy = {}) {
  const search = new URL("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
  search.search = new URLSearchParams({ db: "pubmed", retmode: "json", retmax: String(Math.max(1, Math.min(pageSize, FORMAL_RETRIEVAL_PAGE_SIZE))), retstart: String(Math.max(0, offset)), term: query }).toString()
  const attempts = requestPolicy.attempts ?? 2
  const timeoutMs = requestPolicy.timeoutMs ?? 18000
  const searchPayload = (await (await fetchWithRetry(search, { headers: { "User-Agent": "ClinResearchDesktop/0.4" } }, attempts, timeoutMs)).json())?.esearchresult ?? {}
  const ids = searchPayload.idlist ?? []
  const totalCount = Number(searchPayload.count) || 0
  if (!ids.length) return { records: [], total_count: totalCount, has_more: false }
  const fetchUrl = new URL("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi")
  fetchUrl.search = new URLSearchParams({ db: "pubmed", retmode: "xml", id: ids.join(",") }).toString()
  const xml = await (await fetchWithRetry(fetchUrl, { headers: { "User-Agent": "ClinResearchDesktop/0.4" } }, attempts, timeoutMs)).text()
  const articles = [...xml.matchAll(/<PubmedArticle>([\s\S]*?)<\/PubmedArticle>/g)].map((match) => match[1])
  const byId = new Map(articles.map((article) => {
    const pmid = tag(article, "PMID")
    const doi = clean(article.match(/<ArticleId IdType="doi">([\s\S]*?)<\/ArticleId>/i)?.[1])
    const abstract = [...article.matchAll(/<AbstractText(?:\s[^>]*)?>([\s\S]*?)<\/AbstractText>/gi)].map((item) => clean(item[1])).filter(Boolean).join("\n\n") || null
    return [pmid, { source: "pubmed", external_id: pmid, title: tag(article, "ArticleTitle") || "Untitled PubMed record", abstract, authors: null, publication_year: Number(tag(article, "Year")) || null, doi }]
  }))
  return { records: ids.map((id) => byId.get(id)).filter(Boolean), total_count: totalCount, has_more: offset + ids.length < totalCount }
}

async function pubmed(query, limit) {
  // A quick exploration must fail fast. Formal retrieval keeps the more
  // resilient retry policy below because it is an auditable long-running job.
  return (await pubmedPage(query, bounded(limit), 0, { attempts: 1, timeoutMs: 8000 })).records
}

async function europePmcPage(query, pageSize, cursorMark = "*") {
  const url = new URL("https://www.ebi.ac.uk/europepmc/webservices/rest/search")
  url.search = new URLSearchParams({ query, format: "json", pageSize: String(Math.max(1, Math.min(pageSize, FORMAL_RETRIEVAL_PAGE_SIZE))), resultType: "core", cursorMark: cursorMark || "*" }).toString()
  const payload = await (await fetchWithRetry(url, { headers: { "User-Agent": "ClinResearchDesktop/0.2" } })).json()
  const records = (payload?.resultList?.result ?? []).map((item) => ({
    source: "europe_pmc", external_id: item.pmid || item.id || null, title: clean(item.title) || "Untitled Europe PMC record",
    abstract: clean(item.abstractText), authors: clean(item.authorString), publication_year: Number(item.pubYear) || null,
    doi: clean(item.doi), pmcid: clean(item.pmcid),
  }))
  const nextCursorMark = payload?.nextCursorMark ?? null
  return { records, total_count: Number(payload?.hitCount) || 0, next_cursor_mark: nextCursorMark, has_more: Boolean(records.length && nextCursorMark && nextCursorMark !== cursorMark) }
}

async function europePmc(query, limit) {
  return (await europePmcPage(query, bounded(limit), "*")).records
}

async function importFormalBatch(projectId, source, citations) {
  if (!citations.length) return 0
  const response = await fetchWithRetry(`${BACKEND_URL}/projects/${projectId}/citations/import-manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, citations }),
  })
  if (!response.ok) throw new Error(`ClinResearch backend rejected formal retrieval batch (HTTP ${response.status})`)
  return Number((await response.json()).imported_count) || 0
}

async function recordFormalRetrievalRun(summary) {
  const { project_id: projectId, ...payload } = summary
  const response = await fetchWithRetry(`${BACKEND_URL}/projects/${projectId}/formal-retrieval-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(`ClinResearch backend could not record formal retrieval completeness (HTTP ${response.status})`)
}

async function retrieveFormalReview(projectId, query, source, maxRecords) {
  if (!Number.isInteger(projectId) || projectId < 1) throw new Error("project_id must be a positive integer")
  const limit = boundedFormal(maxRecords)
  let totalCount = null
  let retrievedCount = 0
  let importedCount = 0
  let pageCount = 0

  if (source === "pubmed") {
    let offset = 0
    const firstPage = await pubmedPage(query, Math.min(FORMAL_RETRIEVAL_PAGE_SIZE, limit), offset)
    totalCount = firstPage.total_count
    if (totalCount > limit) {
      const summary = { project_id: projectId, source, retrieval_channel: "client_online_formal_direct_handoff", query, database_total_count: totalCount, retrieved_count: 0, imported_count: 0, page_count: 0, complete: false, truncated: true, max_records: limit, requires_refinement: true }
      await recordFormalRetrievalRun(summary)
      return summary
    }
    let page = firstPage
    while (retrievedCount < limit) {
      if (!page.records.length) break
      importedCount += await importFormalBatch(projectId, source, page.records)
      retrievedCount += page.records.length
      pageCount += 1
      if (!page.has_more) break
      offset += page.records.length
      page = await pubmedPage(query, Math.min(FORMAL_RETRIEVAL_PAGE_SIZE, limit - retrievedCount), offset)
    }
  } else if (source === "europe_pmc") {
    let cursorMark = "*"
    const firstPage = await europePmcPage(query, Math.min(FORMAL_RETRIEVAL_PAGE_SIZE, limit), cursorMark)
    totalCount = firstPage.total_count
    if (totalCount > limit) {
      const summary = { project_id: projectId, source, retrieval_channel: "client_online_formal_direct_handoff", query, database_total_count: totalCount, retrieved_count: 0, imported_count: 0, page_count: 0, complete: false, truncated: true, max_records: limit, requires_refinement: true }
      await recordFormalRetrievalRun(summary)
      return summary
    }
    let page = firstPage
    while (retrievedCount < limit) {
      if (!page.records.length) break
      importedCount += await importFormalBatch(projectId, source, page.records)
      retrievedCount += page.records.length
      pageCount += 1
      if (!page.has_more || !page.next_cursor_mark) break
      cursorMark = page.next_cursor_mark
      page = await europePmcPage(query, Math.min(FORMAL_RETRIEVAL_PAGE_SIZE, limit - retrievedCount), cursorMark)
    }
  } else {
    throw new Error("source must be pubmed or europe_pmc")
  }

  const summary = {
    project_id: projectId,
    source,
    retrieval_channel: "client_online_formal_direct_handoff",
    query,
    database_total_count: totalCount ?? 0,
    retrieved_count: retrievedCount,
    imported_count: importedCount,
    page_count: pageCount,
    complete: totalCount !== null && retrievedCount >= totalCount,
    truncated: totalCount !== null && retrievedCount < totalCount,
    max_records: limit,
  }
  await recordFormalRetrievalRun(summary)
  return summary
}

async function pubmedRetractionCheck(pmid) {
  const search = new URL("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
  const term = `${pmid}[PMID] AND ("Retracted Publication"[Publication Type] OR "Retraction of Publication"[Publication Type] OR "Expression of Concern"[Publication Type] OR "Published Erratum"[Publication Type])`
  search.search = new URLSearchParams({ db: "pubmed", retmode: "json", retmax: "1", term }).toString()
  const ids = (await (await fetchWithRetry(search, { headers: { "User-Agent": "ClinResearchDesktop/0.2" } })).json())?.esearchresult?.idlist ?? []
  const flagged = ids.includes(pmid)
  return {
    pmid,
    status: flagged ? "flagged_needs_human_review" : "not_flagged_at_check_time",
    check_source: "pubmed_publication_type_client",
    details: flagged
      ? "Desktop-local PubMed returned a retraction, correction, or concern publication-type flag; verify the linked notice before use."
      : "Desktop-local PubMed returned no matching notice publication-type flag at check time; this is not a permanent safety guarantee.",
  }
}

async function europePmcOpenAccessFullText(citation) {
  const pmid = String(citation?.pmid ?? "").trim()
  const citationId = citation?.citation_id
  if (!Number.isInteger(citationId) || citationId < 1 || !/^\d+$/.test(pmid)) throw new Error("each citation needs a positive citation_id and numeric PMID")
  const search = new URL("https://www.ebi.ac.uk/europepmc/webservices/rest/search")
  search.search = new URLSearchParams({ query: `EXT_ID:${pmid}`, format: "json", pageSize: "1", resultType: "core" }).toString()
  const record = (await (await fetchWithRetry(search, { headers: { "User-Agent": "ClinResearchDesktop/0.3" } })).json())?.resultList?.result?.[0]
  const pmcid = clean(record?.pmcid)
  if (!record || !pmcid || clean(record?.pmid) !== pmid) {
    return { citation_id: citationId, pmid, status: "access_unavailable", found: false, details: "No Europe PMC open-access XML record matched this PMID." }
  }
  if (citation?.doi && record?.doi && String(citation.doi).toLowerCase() !== String(record.doi).toLowerCase()) throw new Error(`Europe PMC DOI does not match citation ${citationId}`)
  const fullTextUrl = new URL(`https://www.ebi.ac.uk/europepmc/webservices/rest/${pmcid}/fullTextXML`)
  const response = await fetchWithRetry(fullTextUrl, { headers: { "User-Agent": "ClinResearchDesktop/0.3" } })
  const contentText = await response.text()
  if (!response.ok || new TextEncoder().encode(contentText).length < 10000 || !contentText.slice(0, 2000).toLowerCase().includes("<article")) {
    return { citation_id: citationId, pmid, pmcid, status: "verification_failed", found: false, source_url: fullTextUrl.toString(), details: `Europe PMC fullTextXML was not a valid article (HTTP ${response.status}).` }
  }
  return { citation_id: citationId, pmid, pmcid, status: "full_text_ready", found: true, source_kind: "open_access_html", source_url: fullTextUrl.toString(), content_text: contentText }
}

function localExportRoot(workspaceDir) {
  if (workspaceDir !== undefined && workspaceDir !== null) {
    if (typeof workspaceDir !== "string" || !path.isAbsolute(workspaceDir)) {
      throw new Error("workspace_dir must be an absolute path when provided")
    }
    return workspaceDir
  }
  return process.cwd()
}

async function cacheVerifiedFullTexts(workspaceDir, projectId, documents) {
  const cacheDir = path.join(
    localExportRoot(workspaceDir),
    "临床科研智能体工作台导出",
    "全文缓存",
    `项目${projectId}`,
  )
  const cached = new Map()
  for (const document of documents) {
    if (document.status !== "full_text_ready" || !document.content_text) continue
    const filename = `citation-${document.citation_id}-PMID${document.pmid}-${document.pmcid}.xml`
    const destination = path.join(cacheDir, filename)
    try {
      await mkdir(cacheDir, { recursive: true })
      const temporary = `${destination}.tmp-${process.pid}`
      await writeFile(temporary, document.content_text, { encoding: "utf8", mode: 0o600 })
      await rename(temporary, destination)
      cached.set(document.citation_id, { local_cache_path: destination, local_cache_status: "saved" })
    } catch (error) {
      cached.set(document.citation_id, {
        local_cache_path: null,
        local_cache_status: "write_failed",
        local_cache_error: error instanceof Error ? error.message : String(error),
      })
    }
  }
  return cached
}

async function preflightOpenAccessFullTextToProject(projectId, citations, workspaceDir) {
  if (!Number.isInteger(projectId) || projectId < 1) throw new Error("project_id must be a positive integer")
  if (!Array.isArray(citations) || !citations.length || citations.length > 5) throw new Error("citations must contain 1 to 5 entries")
  const documents = await Promise.all(citations.map(async (citation) => {
    try {
      return await europePmcOpenAccessFullText(citation)
    } catch (error) {
      return { citation_id: citation?.citation_id, pmid: String(citation?.pmid ?? ""), status: "verification_failed", found: false, details: error instanceof Error ? error.message : String(error) }
    }
  }))
  const localCache = await cacheVerifiedFullTexts(workspaceDir, projectId, documents)
  const recordsForBackend = documents.map((document) => ({
    ...document,
    local_cache_path: localCache.get(document.citation_id)?.local_cache_path || null,
  }))
  const response = await fetchWithRetry(`${BACKEND_URL}/projects/${projectId}/full-text-preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ results: recordsForBackend }),
  })
  if (!response.ok) throw new Error(`ClinResearch backend rejected full-text preflight (HTTP ${response.status})`)
  const saved = await response.json()
  return {
    project_id: projectId,
    retrieval_channel: "client_online_direct_handoff",
    checked_count: saved.checked_count,
    full_text_ready_count: saved.full_text_ready_count,
    records: (saved.records || []).map((item) => ({
      citation_id: item.citation_id,
      status: item.status,
      pmcid: item.pmcid || null,
      full_text_document_id: item.full_text_document_id || null,
      details: item.details || null,
      ...(localCache.get(item.citation_id) || { local_cache_path: null, local_cache_status: "not_applicable" }),
    })),
  }
}

function validatePreflightJob(projectId, citations) {
  if (!Number.isInteger(projectId) || projectId < 1) throw new Error("project_id must be a positive integer")
  if (!Array.isArray(citations) || !citations.length || citations.length > 100) throw new Error("citations must contain 1 to 100 entries")
  const normalized = []
  const seen = new Set()
  for (const citation of citations) {
    const citationId = citation?.citation_id
    const pmid = String(citation?.pmid ?? "").trim()
    if (!Number.isInteger(citationId) || citationId < 1 || !/^\d+$/.test(pmid)) throw new Error("each citation needs a positive citation_id and numeric PMID")
    if (seen.has(citationId)) continue
    seen.add(citationId)
    normalized.push({ citation_id: citationId, pmid, doi: citation?.doi || undefined })
  }
  return normalized
}

function updatePreflightJobCounts(job, records) {
  for (const record of records) {
    job.completed += 1
    if (record.status === "full_text_ready") job.full_text_ready += 1
    else if (record.status === "access_unavailable") job.access_unavailable += 1
    else job.verification_failed += 1
  }
  job.recent_records = [...records, ...job.recent_records].slice(0, 10).map((record) => ({
    citation_id: record.citation_id,
    status: record.status,
    full_text_document_id: record.full_text_document_id || null,
    details: record.details || null,
  }))
}

async function runPreflightJob(job) {
  try {
    for (let offset = 0; offset < job.citations.length; offset += PREFLIGHT_JOB_BATCH_SIZE) {
      const batch = job.citations.slice(offset, offset + PREFLIGHT_JOB_BATCH_SIZE)
      job.current_citation_ids = batch.map((item) => item.citation_id)
      const result = await preflightOpenAccessFullTextToProject(job.project_id, batch, job.workspace_dir)
      updatePreflightJobCounts(job, result.records || [])
    }
    job.status = "completed"
  } catch (error) {
    job.status = "failed"
    job.error = error instanceof Error ? error.message : String(error)
  } finally {
    job.current_citation_ids = []
    job.finished_at = new Date().toISOString()
  }
}

function preflightJobStatus(job) {
  return {
    task_id: job.task_id,
    project_id: job.project_id,
    status: job.status,
    total_count: job.citations.length,
    completed_count: job.completed,
    remaining_count: job.citations.length - job.completed,
    full_text_ready_count: job.full_text_ready,
    access_unavailable_count: job.access_unavailable,
    verification_failed_count: job.verification_failed,
    current_citation_ids: job.current_citation_ids,
    recent_records: job.recent_records,
    started_at: job.started_at,
    finished_at: job.finished_at || null,
    error: job.error || null,
  }
}

function startPreflightJob(projectId, citations, workspaceDir) {
  const normalized = validatePreflightJob(projectId, citations)
  const active = [...PREFLIGHT_JOBS.values()].find((job) => job.project_id === projectId && job.status === "running")
  if (active) return { ...preflightJobStatus(active), reused_existing_task: true }
  const job = {
    task_id: `preflight-${randomUUID()}`,
    project_id: projectId,
    workspace_dir: workspaceDir,
    citations: normalized,
    status: "running",
    completed: 0,
    full_text_ready: 0,
    access_unavailable: 0,
    verification_failed: 0,
    current_citation_ids: [],
    recent_records: [],
    started_at: new Date().toISOString(),
  }
  PREFLIGHT_JOBS.set(job.task_id, job)
  void runPreflightJob(job)
  return preflightJobStatus(job)
}

function result(payload) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], structuredContent: payload }
}

async function callTool(name, args) {
  if (name === "client_get_literature_access_status") return result({
    mode: "client_online",
    execution_location: "desktop_local",
    supported_sources: PUBMED_ONLY_DEMO_MODE ? ["pubmed"] : ["pubmed", "europe_pmc"],
    full_text_preflight_source: "europe_pmc_open_access",
    retrieval_policy: PUBMED_ONLY_DEMO_MODE ? "pubmed_only_demo" : "multi_database",
    project_storage: "none",
  })
  if (name === "client_check_pubmed_retractions") {
    const pmids = [...new Set((args?.pmids ?? []).map((item) => String(item).trim()).filter(Boolean))]
    if (!pmids.length || pmids.length > 50 || pmids.some((item) => !/^\d+$/.test(item))) throw new Error("pmids must contain 1 to 50 numeric PubMed IDs")
    const checks = []
    for (const pmid of pmids) checks.push(await pubmedRetractionCheck(pmid))
    return result({ retrieval_channel: "client_online", checked_count: checks.length, checks })
  }
  if (name === "client_preflight_europepmc_open_access_full_text_to_project") {
    throw new Error("The synchronous full-text preflight tool is retired. Start a new OpenCode session and use the background preflight task tools instead.")
  }
  if (name === "client_start_europepmc_open_access_preflight_job") {
    return result(startPreflightJob(args?.project_id, args?.citations, args?.workspace_dir))
  }
  if (name === "client_get_europepmc_open_access_preflight_job") {
    const job = PREFLIGHT_JOBS.get(String(args?.task_id ?? ""))
    if (!job) throw new Error("Unknown or expired full-text preflight task.")
    return result(preflightJobStatus(job))
  }
  if (PUBMED_ONLY_DEMO_MODE && ["client_search_europepmc", "client_retrieve_europepmc_formal_review"].includes(name)) {
    throw new Error("Europe PMC retrieval is disabled in PubMed-only demonstration mode. Use PubMed for retrieval; Europe PMC remains available only for open-access full-text preflight.")
  }
  const query = String(args?.query ?? "").trim()
  if (!query || query.length > 4000) throw new Error("query must contain 1 to 4,000 characters")
  if (name === "client_retrieve_pubmed_formal_review") {
    return result(await retrieveFormalReview(args?.project_id, query, "pubmed", args?.max_records))
  }
  if (name === "client_retrieve_europepmc_formal_review") {
    return result(await retrieveFormalReview(args?.project_id, query, "europe_pmc", args?.max_records))
  }
  const records = name === "client_search_pubmed" ? await pubmed(query, args?.limit) : name === "client_search_europepmc" ? await europePmc(query, args?.limit) : null
  if (records === null) throw new Error(`Unknown tool: ${name}`)
  return result({ source: name === "client_search_pubmed" ? "pubmed" : "europe_pmc", retrieval_channel: "client_online", query, returned_count: records.length, records })
}

function send(message) { process.stdout.write(`${JSON.stringify(message)}\n`) }
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
input.on("line", async (line) => {
  try {
    const request = JSON.parse(line)
    if (request.method === "notifications/initialized") return
    if (request.method === "initialize") return send({ jsonrpc: "2.0", id: request.id, result: { protocolVersion: request.params?.protocolVersion ?? "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "clinresearch-literature-client", version: "0.4.3" } } })
    if (request.method === "tools/list") return send({ jsonrpc: "2.0", id: request.id, result: { tools: availableToolDefinitions() } })
    if (request.method === "tools/call") return send({ jsonrpc: "2.0", id: request.id, result: await callTool(request.params?.name, request.params?.arguments) })
    if (request.id !== undefined) return send({ jsonrpc: "2.0", id: request.id, error: { code: -32601, message: "Method not found" } })
  } catch (error) {
    send({ jsonrpc: "2.0", id: null, error: { code: -32000, message: error instanceof Error ? error.message : String(error) } })
  }
})
