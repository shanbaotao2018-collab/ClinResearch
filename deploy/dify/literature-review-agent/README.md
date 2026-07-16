# Dify Integration

## Purpose

Use Dify as the B/S host for the literature review workbench.

## Local deployment files

- `config/dify.local.env`: local Dify runtime overrides
- `workflows/init-and-search.yml`: project init, search generation, citation import, dedup, export
- `workflows/screening-and-prisma.yml`: screening decision + PRISMA refresh
- `scripts/start-local.sh`: copy local env into `vendor/dify/docker/.env` and start Dify
- `scripts/bootstrap-dify.sh`: initialize Dify, create admin, import both workflow apps

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

## Local ports and credentials

- Dify console: `http://localhost:18080`
- Literature backend: `http://127.0.0.1:8010`
- Dify container -> backend: `http://host.docker.internal:8010`
- Init password: `dify-init-123456`
- Admin email: `admin@example.com`
- Admin password: `Local123456`

## Bring-up sequence

1. Start backend:
   - `cd apps/literature-review-agent/backend`
   - `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010`
2. Start Dify:
   - `deploy/dify/literature-review-agent/scripts/start-local.sh`
3. Bootstrap and import workflow apps:
   - `deploy/dify/literature-review-agent/scripts/bootstrap-dify.sh`
