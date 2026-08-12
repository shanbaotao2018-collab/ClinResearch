import asyncio

from app.client_retrieval_mcp import (
    _cache_verified_full_texts,
    _retrieve_and_import_formal_records,
    client_fetch_europepmc_open_access_full_text,
    client_search_europepmc,
    client_search_pubmed,
    get_client_literature_access_status,
)


def test_client_connector_reports_local_only_capability():
    status = get_client_literature_access_status()

    assert status["mode"] == "client_online"
    assert status["execution_location"] == "desktop_local"
    assert status["project_storage"] == "none"


def test_client_connector_returns_normalized_pubmed_records(monkeypatch):
    async def fake_search(query: str, limit: int):
        return [{"source": "pubmed", "title": "Local client result", "external_id": "1"}]

    monkeypatch.setattr("app.client_retrieval_mcp.search_pubmed_records", fake_search)
    result = asyncio.run(client_search_pubmed("heart failure", limit=1))

    assert result["retrieval_channel"] == "client_online"
    assert result["records"][0]["title"] == "Local client result"


def test_client_connector_returns_normalized_europe_pmc_records(monkeypatch):
    async def fake_search(query: str, limit: int):
        return [{"source": "europe_pmc", "title": "Local client result", "external_id": "2"}]

    monkeypatch.setattr("app.client_retrieval_mcp.search_europepmc_records", fake_search)
    result = asyncio.run(client_search_europepmc("heart failure", limit=1))

    assert result["retrieval_channel"] == "client_online"
    assert result["records"][0]["title"] == "Local client result"


def test_formal_pubmed_retrieval_pages_and_persists_every_record(monkeypatch):
    requested_offsets: list[int] = []
    persisted_batches: list[list[str]] = []

    async def fake_page(query: str, *, page_size: int, offset: int):
        requested_offsets.append(offset)
        if offset == 0:
            return {
                "records": [
                    {"source": "pubmed", "title": "Record 1", "external_id": "1"},
                    {"source": "pubmed", "title": "Record 2", "external_id": "2"},
                ],
                "total_count": 3,
                "offset": offset,
                "page_size": page_size,
                "has_more": True,
            }
        return {
            "records": [{"source": "pubmed", "title": "Record 3", "external_id": "3"}],
            "total_count": 3,
            "offset": offset,
            "page_size": page_size,
            "has_more": False,
        }

    async def fake_import(project_id: int, source: str, citations: list[dict]):
        assert project_id == 9
        assert source == "pubmed"
        persisted_batches.append([citation["external_id"] for citation in citations])
        return len(citations)

    monkeypatch.setattr("app.client_retrieval_mcp.search_pubmed_records_page", fake_page)
    monkeypatch.setattr("app.client_retrieval_mcp._import_formal_retrieval_batch", fake_import)
    monkeypatch.setattr("app.client_retrieval_mcp._record_formal_retrieval_run", lambda _: asyncio.sleep(0))

    result = asyncio.run(_retrieve_and_import_formal_records(9, "type 2 diabetes", "pubmed", 10))

    assert requested_offsets == [0, 2]
    assert persisted_batches == [["1", "2"], ["3"]]
    assert result["database_total_count"] == 3
    assert result["retrieved_count"] == 3
    assert result["imported_count"] == 3
    assert result["complete"] is True
    assert result["truncated"] is False


def test_formal_europe_pmc_retrieval_stops_before_partial_import_when_over_budget(monkeypatch):
    requested_cursors: list[str] = []

    async def fake_page(query: str, *, page_size: int, cursor_mark: str):
        requested_cursors.append(cursor_mark)
        return {
            "records": [
                {"source": "europe_pmc", "title": "Record 1", "external_id": "1"},
                {"source": "europe_pmc", "title": "Record 2", "external_id": "2"},
            ],
            "total_count": 4,
            "cursor_mark": cursor_mark,
            "next_cursor_mark": "next-page",
            "has_more": True,
        }

    async def fake_import(project_id: int, source: str, citations: list[dict]):
        return len(citations)

    monkeypatch.setattr("app.client_retrieval_mcp.search_europepmc_records_page", fake_page)
    monkeypatch.setattr("app.client_retrieval_mcp._import_formal_retrieval_batch", fake_import)
    monkeypatch.setattr("app.client_retrieval_mcp._record_formal_retrieval_run", lambda _: asyncio.sleep(0))

    result = asyncio.run(_retrieve_and_import_formal_records(9, "type 2 diabetes", "europe_pmc", 2))

    assert requested_cursors == ["*"]
    assert result["retrieved_count"] == 0
    assert result["imported_count"] == 0
    assert result["complete"] is False
    assert result["truncated"] is True
    assert result["requires_refinement"] is True


def test_client_full_text_batch_reports_one_network_failure_without_aborting(monkeypatch):
    async def fake_fetch(_: str):
        raise RuntimeError("temporary source outage")

    monkeypatch.setattr("app.client_retrieval_mcp.fetch_europepmc_open_access_full_text", fake_fetch)
    result = asyncio.run(client_fetch_europepmc_open_access_full_text([
        {"citation_id": 1, "pmid": "12345"},
    ]))

    assert result["documents"][0]["status"] == "verification_failed"


def test_client_full_text_cache_writes_verified_xml_to_workspace(tmp_path):
    cached = _cache_verified_full_texts(
        str(tmp_path),
        12,
        [{
            "citation_id": 9,
            "pmid": "12345",
            "pmcid": "PMC12345",
            "status": "full_text_ready",
            "content_text": "<article><body>Verified public XML.</body></article>",
        }],
    )

    destination = tmp_path / "临床科研智能体工作台导出" / "全文缓存" / "项目12" / "citation-9-PMID12345-PMC12345.xml"
    assert cached[9]["local_cache_status"] == "saved"
    assert cached[9]["local_cache_path"] == str(destination)
    assert destination.read_text(encoding="utf-8") == "<article><body>Verified public XML.</body></article>"
