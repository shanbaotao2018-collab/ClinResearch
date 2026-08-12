# Client-Online Mode

`client_online` is for deployments where the ClinResearch server cannot reach
PubMed or Europe PMC but the researcher's desktop can. The server remains the
system of record for projects, screening, evidence, approvals, and exports.
Only public literature retrieval runs from the desktop-local MCP connector.

## Local Test Setup

Start the backend in client-online mode:

```bash
cd "/Users/shanbaotao/Documents/agent 2"
bash scripts/start-research-backend.sh --literature-access-mode client_online
```

The desktop OpenCode configuration needs both MCP servers:

- `literature_review`: remote central backend at `http://127.0.0.1:8010/mcp/`
- `literature_client`: local command `python -m app.client_retrieval_mcp`

For this development machine, the configured local command uses the backend
virtual environment. Production packaging should bundle this connector with
the customized desktop app instead of relying on a repository path.

Restart the desktop app, then verify both MCP servers:

```bash
opencode mcp list
```

Expected result: both `literature_review` and `literature_client` are
`connected`.

## Agent Behavior

When `get_literature_access_status` returns `mode: client_online`,
`literature-review` must:

1. Call `get_client_literature_access_status`.
2. Call `client_search_pubmed` and, when useful, `client_search_europepmc`.
3. Send the returned normalized records to the central backend with
   `import_citations_to_project`.
4. Continue normal server-side deduplication, screening, evidence extraction,
   approval, and export.

For evidence extraction in the same mode, `evidence-extraction` must use the
desktop connector for every remaining public-database operation:

1. Call `client_check_pubmed_retractions` with the included studies' numeric
   PMIDs, then save the exact returned results with
   `save_project_retraction_checks`.
2. When an included study has verified open-access Europe PMC full text, call
   `client_fetch_europepmc_open_access_full_text`, then save only its returned
   source text and HTTPS URL with `save_full_text_documents`.

The backend validates that results cover exactly the included citations and
remains the audit and export system of record. The agent must not replace this
path with direct Shell requests or arbitrary public APIs.

The server-side `search_pubmed` and `search_europepmc` tools are intentionally
blocked in this mode. This prevents accidental dependence on server egress.

## Current Scope

The desktop connector covers title/abstract retrieval, metadata lookup, PubMed
notice-type retraction checks, and verified Europe PMC open-access full-text
retrieval. It never stores project data; central backend tools validate and
persist all project mutations.

Never place patient identifiers in a database query or an MCP tool call.
