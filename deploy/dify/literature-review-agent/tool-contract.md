# Tool Contract

## Tool: create_project

- Method: `POST`
- Path: `/projects`
- Input: `title`, `research_question`, optional PICO fields
- Output: `id`, `status`, project fields

## Tool: generate_search_strategy

- Method: `POST`
- Path: `/projects/{project_id}/search-strategies/generate`
- Output: `query_text`, `source`, `version_number`, `rationale`

## Tool: import_manual_citations

- Method: `POST`
- Path: `/projects/{project_id}/citations/import-manual`
- Output: `imported_count`

## Tool: deduplicate

- Method: `POST`
- Path: `/projects/{project_id}/deduplicate`
- Output: `removed_count`

## Tool: submit_screening_decision

- Method: `POST`
- Path: `/projects/{project_id}/screening-decisions`
- Input: `citation_id`, `decision`, `reason`, `actor`

## Tool: export_bundle

- Method: `GET`
- Path: `/projects/{project_id}/export`
