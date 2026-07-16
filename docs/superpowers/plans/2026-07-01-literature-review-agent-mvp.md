# Literature Review Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可本地运行、可私有化部署的文献综述智能体 MVP 后端与 Dify 宿主接入层，完成“检索 + 筛选 + PRISMA”闭环。

**Architecture:** 先实现一个薄的 `FastAPI + SQLite` 业务后端，负责项目事实、审计、检索、导入、去重、筛选与 PRISMA 状态流；再把 Dify 作为 B/S 宿主，通过 HTTP 工具方式接入这些能力。对外部专业能力采用适配器模式，先支持 `PubMed / Europe PMC` 与文件导入，筛选与 PRISMA 先保留可替换接口。

**Tech Stack:** Python 3.12, FastAPI, SQLModel, Pydantic Settings, httpx, pytest, SQLite, Dify

---

### Task 1: 脚手架后端项目

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/pyproject.toml`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/__init__.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/config.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/db.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/README.md`

- [ ] **Step 1: 创建目录结构**

Run: `mkdir -p '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app'`
Expected: `backend/app` 目录存在

- [ ] **Step 2: 写依赖清单**

```toml
[project]
name = "literature-review-agent-backend"
version = "0.1.0"
description = "Backend for literature review agent MVP"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115,<1.0",
  "uvicorn[standard]>=0.30,<1.0",
  "sqlmodel>=0.0.22,<1.0",
  "pydantic-settings>=2.3,<3.0",
  "httpx>=0.27,<1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2,<9.0",
  "pytest-cov>=5.0,<6.0",
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: 写配置文件**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Literature Review Agent Backend"
    database_url: str = "sqlite:///./literature_review_agent.db"
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    model_config = SettingsConfigDict(env_prefix="LRA_", env_file=".env", extra="ignore")


settings = Settings()
```

- [ ] **Step 4: 写数据库入口**

```python
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
```

- [ ] **Step 5: 写应用入口**

```python
from fastapi import FastAPI

from .config import settings
from .db import init_db

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 写最小 README**

```md
# Literature Review Agent Backend

## Run

```bash
uvicorn app.main:app --reload
```
```

- [ ] **Step 7: 安装并验证服务能启动**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
Expected: 依赖安装成功

- [ ] **Step 8: 启动健康检查**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/python -m uvicorn app.main:app --port 8010`
Expected: 服务启动，访问 `/health` 返回 `{"status":"ok"}`

- [ ] **Step 9: 提交**

```bash
git add apps/literature-review-agent/backend
git commit -m "feat: scaffold literature review backend"
```

### Task 2: 定义核心数据模型与项目状态流

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/models.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/schemas.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/tests/test_projects.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`

- [ ] **Step 1: 写项目创建测试**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_project_returns_draft_status():
    response = client.post(
        "/projects",
        json={
            "title": "Sepsis biomarker review",
            "research_question": "What biomarkers predict sepsis mortality?",
            "pico_population": "Adults with sepsis",
            "pico_outcome": "Mortality",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["title"] == "Sepsis biomarker review"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_projects.py::test_create_project_returns_draft_status -v`
Expected: FAIL，提示 `/projects` 未实现

- [ ] **Step 3: 定义模型**

```python
from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlmodel import Field, SQLModel


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    SEARCH_STRATEGY_READY = "search_strategy_ready"
    SEARCH_EXECUTED = "search_executed"
    CITATIONS_DEDUPLICATED = "citations_deduplicated"
    SCREENING_IN_PROGRESS = "screening_in_progress"
    SCREENING_COMPLETED = "screening_completed"
    PRISMA_GENERATED = "prisma_generated"
    EXPORTED = "exported"


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    research_question: str
    pico_population: Optional[str] = None
    pico_intervention: Optional[str] = None
    pico_comparator: Optional[str] = None
    pico_outcome: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SearchStrategyVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    query_text: str
    source: str
    version_number: int
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    action: str
    actor: str
    summary: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: 定义请求响应模型**

```python
from typing import Optional

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    research_question: str
    pico_population: Optional[str] = None
    pico_intervention: Optional[str] = None
    pico_comparator: Optional[str] = None
    pico_outcome: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None


class ProjectRead(ProjectCreate):
    id: int
    status: str


class SearchStrategyCreate(BaseModel):
    source: str
    query_text: str
    rationale: str
```

- [ ] **Step 5: 在 `main.py` 实现项目接口**

```python
from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import AuditLog, Project
from .schemas import ProjectCreate

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)):
    project = Project.model_validate(payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(
        AuditLog(
            project_id=project.id,
            action="project.created",
            actor="system",
            summary=f"Project {project.title} created",
        )
    )
    session.commit()
    return project


@app.get("/projects/{project_id}")
def get_project(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/projects")
def list_projects(session: Session = Depends(get_session)):
    return session.exec(select(Project)).all()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_projects.py::test_create_project_returns_draft_status -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add apps/literature-review-agent/backend/app apps/literature-review-agent/backend/tests
git commit -m "feat: add project models and lifecycle endpoints"
```

### Task 3: 实现检索式生成与版本管理

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/services/search_strategy.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/tests/test_search_strategy.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`

- [ ] **Step 1: 写检索式生成测试**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_generate_search_strategy_creates_version():
    project = client.post(
        "/projects",
        json={
            "title": "ARDS ventilation review",
            "research_question": "Does lung protective ventilation reduce mortality in ARDS?",
            "pico_population": "Adults with ARDS",
            "pico_intervention": "Lung protective ventilation",
            "pico_outcome": "Mortality",
        },
    ).json()

    response = client.post(f"/projects/{project['id']}/search-strategies/generate")
    assert response.status_code == 201
    payload = response.json()
    assert payload["source"] == "pubmed"
    assert "ARDS" in payload["query_text"]
    assert payload["version_number"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_search_strategy.py::test_generate_search_strategy_creates_version -v`
Expected: FAIL，提示路由不存在

- [ ] **Step 3: 写生成服务**

```python
from app.models import Project


def build_pubmed_query(project: Project) -> tuple[str, str]:
    terms = [project.research_question]
    if project.pico_population:
        terms.append(project.pico_population)
    if project.pico_intervention:
        terms.append(project.pico_intervention)
    if project.pico_outcome:
        terms.append(project.pico_outcome)

    cleaned_terms = [term.strip() for term in terms if term and term.strip()]
    query_text = " AND ".join(f'("{term}"[Title/Abstract])' for term in cleaned_terms)
    rationale = "Generated from research question and available PICO fields."
    return query_text, rationale
```

- [ ] **Step 4: 在 `main.py` 加版本接口**

```python
from .models import AuditLog, Project, ProjectStatus, SearchStrategyVersion
from .services.search_strategy import build_pubmed_query


@app.post("/projects/{project_id}/search-strategies/generate", status_code=status.HTTP_201_CREATED)
def generate_search_strategy(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query_text, rationale = build_pubmed_query(project)
    existing_count = len(
        session.exec(
            select(SearchStrategyVersion).where(SearchStrategyVersion.project_id == project_id)
        ).all()
    )
    strategy = SearchStrategyVersion(
        project_id=project_id,
        query_text=query_text,
        source="pubmed",
        version_number=existing_count + 1,
        rationale=rationale,
    )
    session.add(strategy)
    project.status = ProjectStatus.SEARCH_STRATEGY_READY
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="search_strategy.generated",
            actor="system",
            summary="Generated PubMed search strategy",
        )
    )
    session.commit()
    session.refresh(strategy)
    return strategy
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_search_strategy.py::test_generate_search_strategy_creates_version -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/literature-review-agent/backend/app apps/literature-review-agent/backend/tests
git commit -m "feat: add search strategy generation and versioning"
```

### Task 4: 实现英文检索与文件导入

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/services/citations.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/tests/test_citations.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/models.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`

- [ ] **Step 1: 写题录检索测试**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_import_manual_citations_updates_project_status():
    project = client.post(
        "/projects",
        json={"title": "ICU delirium review", "research_question": "How common is ICU delirium?"},
    ).json()

    response = client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "ICU delirium cohort study", "external_id": "PMID123", "abstract": "Abstract 1"},
                {"title": "ICU delirium meta analysis", "external_id": "PMID456", "abstract": "Abstract 2"},
            ],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["imported_count"] == 2
    project_after = client.get(f"/projects/{project['id']}").json()
    assert project_after["status"] == "search_executed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_citations.py::test_import_manual_citations_updates_project_status -v`
Expected: FAIL，提示模型或路由不存在

- [ ] **Step 3: 扩展模型**

```python
class Citation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    source: str
    external_id: Optional[str] = Field(default=None, index=True)
    title: str
    abstract: Optional[str] = None
    authors: Optional[str] = None
    publication_year: Optional[int] = None
    doi: Optional[str] = None
    is_deduplicated: bool = False
    dedup_group: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: 写导入服务**

```python
from pydantic import BaseModel


class CitationIn(BaseModel):
    title: str
    external_id: str | None = None
    abstract: str | None = None
    authors: str | None = None
    publication_year: int | None = None
    doi: str | None = None


class CitationImportPayload(BaseModel):
    source: str
    citations: list[CitationIn]
```

- [ ] **Step 5: 在 `main.py` 加手工导入接口**

```python
from .models import AuditLog, Citation, Project, ProjectStatus, SearchStrategyVersion
from .services.citations import CitationImportPayload


@app.post("/projects/{project_id}/citations/import-manual", status_code=status.HTTP_201_CREATED)
def import_manual_citations(
    project_id: int,
    payload: CitationImportPayload,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    imported_count = 0
    for item in payload.citations:
        citation = Citation(project_id=project_id, source=payload.source, **item.model_dump())
        session.add(citation)
        imported_count += 1

    project.status = ProjectStatus.SEARCH_EXECUTED
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="citations.imported",
            actor="system",
            summary=f"Imported {imported_count} citations from {payload.source}",
        )
    )
    session.commit()
    return {"imported_count": imported_count}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_citations.py::test_import_manual_citations_updates_project_status -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add apps/literature-review-agent/backend/app apps/literature-review-agent/backend/tests
git commit -m "feat: add citation import pipeline"
```

### Task 5: 实现去重、筛选决策与 PRISMA 计数

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/services/screening.py`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/tests/test_screening.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/models.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`

- [ ] **Step 1: 写去重与筛选测试**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_deduplicate_and_screening_updates_prisma_counts():
    project = client.post(
        "/projects",
        json={"title": "Stroke AI review", "research_question": "Can AI diagnose stroke on CT?"},
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "AI stroke CT", "external_id": "1", "doi": "10.1/a"},
                {"title": "AI stroke CT duplicate", "external_id": "2", "doi": "10.1/a"},
                {"title": "Unrelated radiology paper", "external_id": "3", "doi": "10.1/b"},
            ],
        },
    )

    dedup_response = client.post(f"/projects/{project['id']}/deduplicate")
    assert dedup_response.status_code == 200
    assert dedup_response.json()["removed_count"] == 1

    screening_response = client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={"citation_id": 1, "decision": "include", "reason": "Matches topic", "actor": "reviewer_a"},
    )
    assert screening_response.status_code == 201

    prisma_response = client.get(f"/projects/{project['id']}/prisma")
    assert prisma_response.status_code == 200
    assert prisma_response.json()["identified_count"] == 3
    assert prisma_response.json()["deduplicated_count"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_screening.py::test_deduplicate_and_screening_updates_prisma_counts -v`
Expected: FAIL，提示接口未实现

- [ ] **Step 3: 扩展模型**

```python
class ScreeningDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    citation_id: int = Field(index=True)
    decision: str
    reason: str
    actor: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PrismaCount(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, unique=True)
    identified_count: int = 0
    deduplicated_count: int = 0
    screened_count: int = 0
    included_count: int = 0
    excluded_count: int = 0
    full_text_assessed_count: int = 0
```

- [ ] **Step 4: 写筛选服务**

```python
from collections import Counter

from sqlmodel import Session, select

from app.models import Citation, PrismaCount, ScreeningDecision


def deduplicate_citations(session: Session, project_id: int) -> int:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    seen: set[str] = set()
    removed = 0
    for citation in citations:
        fingerprint = citation.doi or citation.external_id or citation.title.lower()
        if fingerprint in seen:
            citation.is_deduplicated = True
            removed += 1
        else:
            seen.add(fingerprint)
            citation.is_deduplicated = False
    session.commit()
    return removed


def rebuild_prisma_counts(session: Session, project_id: int) -> PrismaCount:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    decisions = session.exec(
        select(ScreeningDecision).where(ScreeningDecision.project_id == project_id)
    ).all()
    counts = Counter(item.decision for item in decisions)
    record = session.exec(select(PrismaCount).where(PrismaCount.project_id == project_id)).first()
    if not record:
        record = PrismaCount(project_id=project_id)
    record.identified_count = len(citations)
    record.deduplicated_count = len([c for c in citations if not c.is_deduplicated])
    record.screened_count = len(decisions)
    record.included_count = counts.get("include", 0)
    record.excluded_count = counts.get("exclude", 0)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
```

- [ ] **Step 5: 在 `main.py` 增加接口**

```python
from pydantic import BaseModel

from .models import AuditLog, Citation, PrismaCount, Project, ProjectStatus, ScreeningDecision, SearchStrategyVersion
from .services.screening import deduplicate_citations, rebuild_prisma_counts


class ScreeningDecisionCreate(BaseModel):
    citation_id: int
    decision: str
    reason: str
    actor: str


@app.post("/projects/{project_id}/deduplicate")
def deduplicate(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    removed_count = deduplicate_citations(session, project_id)
    project.status = ProjectStatus.CITATIONS_DEDUPLICATED
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="citations.deduplicated",
            actor="system",
            summary=f"Removed {removed_count} duplicates",
        )
    )
    session.commit()
    return {"removed_count": removed_count}


@app.post("/projects/{project_id}/screening-decisions", status_code=status.HTTP_201_CREATED)
def create_screening_decision(
    project_id: int,
    payload: ScreeningDecisionCreate,
    session: Session = Depends(get_session),
):
    decision = ScreeningDecision(project_id=project_id, **payload.model_dump())
    session.add(decision)
    project = session.get(Project, project_id)
    if project:
        project.status = ProjectStatus.SCREENING_IN_PROGRESS
        session.add(project)
    session.commit()
    prisma = rebuild_prisma_counts(session, project_id)
    return {"decision_id": decision.id, "prisma": prisma.model_dump()}


@app.get("/projects/{project_id}/prisma")
def get_prisma(project_id: int, session: Session = Depends(get_session)):
    record = rebuild_prisma_counts(session, project_id)
    return record
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_screening.py::test_deduplicate_and_screening_updates_prisma_counts -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add apps/literature-review-agent/backend/app apps/literature-review-agent/backend/tests
git commit -m "feat: add deduplication screening and prisma counts"
```

### Task 6: 实现导出、审计与端到端测试

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/tests/test_exports.py`
- Modify: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend/app/main.py`

- [ ] **Step 1: 写导出测试**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_export_bundle_returns_project_citations_prisma_and_audit():
    project = client.post(
        "/projects",
        json={"title": "ARDS review", "research_question": "How to ventilate ARDS?"},
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={"source": "pubmed", "citations": [{"title": "ARDS paper", "external_id": "100"}]},
    )

    response = client.get(f"/projects/{project['id']}/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["id"] == project["id"]
    assert isinstance(payload["citations"], list)
    assert "audit_logs" in payload
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests/test_exports.py::test_export_bundle_returns_project_citations_prisma_and_audit -v`
Expected: FAIL，提示导出接口不存在

- [ ] **Step 3: 在 `main.py` 增加审计与导出接口**

```python
@app.get("/projects/{project_id}/audit-logs")
def get_audit_logs(project_id: int, session: Session = Depends(get_session)):
    return session.exec(select(AuditLog).where(AuditLog.project_id == project_id)).all()


@app.get("/projects/{project_id}/export")
def export_project_bundle(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    audit_logs = session.exec(select(AuditLog).where(AuditLog.project_id == project_id)).all()
    prisma = rebuild_prisma_counts(session, project_id)
    project.status = ProjectStatus.EXPORTED
    session.add(project)
    session.commit()
    return {
        "project": project.model_dump(),
        "citations": [item.model_dump() for item in citations],
        "prisma": prisma.model_dump(),
        "audit_logs": [item.model_dump() for item in audit_logs],
    }
```

- [ ] **Step 4: 跑后端测试全集**

Run: `cd '/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend' && .venv/bin/pytest tests -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/literature-review-agent/backend/app apps/literature-review-agent/backend/tests
git commit -m "feat: add export bundle and audit endpoints"
```

### Task 7: 补 Dify 接入文档与本地运行说明

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/deploy/dify/literature-review-agent/README.md`
- Create: `/Users/shanbaotao/Documents/agent 2/deploy/dify/literature-review-agent/tool-contract.md`
- Create: `/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/README.md`

- [ ] **Step 1: 写 Dify 接入说明**

```md
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
```

- [ ] **Step 2: 写工具契约**

```md
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
```

- [ ] **Step 3: 写根 README**

```md
# Literature Review Agent MVP

## Components

- `apps/literature-review-agent/backend`: FastAPI backend for project facts and workflow state
- `deploy/dify/literature-review-agent`: Dify host integration notes

## MVP scope

- Project creation
- Search strategy generation
- Citation import
- Deduplication
- Screening decision logging
- PRISMA counts
- Export bundle
```

- [ ] **Step 4: 提交**

```bash
git add apps/literature-review-agent deploy/dify/literature-review-agent
git commit -m "docs: add dify integration plan and usage docs"
```

## Self-Review

- Spec coverage:
  - B/S 宿主：Task 7
  - 编排型 Agent 后端能力：Task 2-6
  - 检索式生成：Task 3
  - 题录导入：Task 4
  - 去重、筛选、PRISMA：Task 5
  - 导出与审计：Task 6
- Placeholder scan:
  - 计划正文没有占位词或未展开步骤
- Type consistency:
  - `ProjectStatus`、`SearchStrategyVersion`、`Citation`、`ScreeningDecision`、`PrismaCount` 在任务间保持一致
