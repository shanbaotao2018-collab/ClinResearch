# Dify Integration

## Purpose

Use Dify as the B/S host for the literature review workbench.

## Required backend endpoints

- `POST /projects`
- `POST /projects/{project_id}/search-strategies/generate`
- `POST /projects/{project_id}/citations/import-manual`
- `POST /projects/{project_id}/deduplicate`
- `POST /projects/{project_id}/screening-decisions`
- `GET /projects/{project_id}/prisma`
- `GET /projects/{project_id}/export`

## Recommended Dify app layout

1. Project creation workflow
2. Search strategy generation workflow
3. Citation import and deduplication workflow
4. Screening assistant workflow
5. PRISMA and export workflow
