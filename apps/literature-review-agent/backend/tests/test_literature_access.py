import asyncio

import pytest
import httpx
from pydantic import ValidationError

from app.config import Settings, settings
from app.services.literature_access import (
    LiteratureAccessError,
    literature_access_status,
    translate_literature_request_error,
)
from app.services.literature_sources import search_europepmc_records, search_pubmed_records


def test_offline_mode_reports_file_import_only(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "offline")

    status = literature_access_status()

    assert status["mode"] == "offline"
    assert status["live_database_requests_enabled"] is False
    assert status["offline_file_import_enabled"] is True
    assert status["supported_online_sources"] == []


def test_offline_mode_blocks_pubmed_before_network_access(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "offline")

    with pytest.raises(LiteratureAccessError, match="import_citations_file_to_project"):
        asyncio.run(search_pubmed_records("heart failure", limit=1))


def test_offline_mode_blocks_europe_pmc_before_network_access(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "offline")

    with pytest.raises(LiteratureAccessError, match="europe_pmc retrieval is disabled"):
        asyncio.run(search_europepmc_records("heart failure", limit=1))


def test_auto_mode_turns_source_failure_into_offline_import_instruction(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "auto")

    error = translate_literature_request_error("pubmed", httpx.ConnectError("blocked"))

    assert error is not None
    assert "pubmed is unreachable" in str(error)
    assert "import_citations_file_to_project" in str(error)


def test_online_mode_keeps_live_database_requests_enabled(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "online")

    status = literature_access_status()

    assert status["mode"] == "online"
    assert status["live_database_requests_enabled"] is True
    assert status["auto_fallback_enabled"] is False


def test_client_online_mode_requires_desktop_retrieval_connector(monkeypatch):
    monkeypatch.setattr(settings, "literature_access_mode", "client_online")

    status = literature_access_status()

    assert status["live_database_requests_enabled"] is False
    assert status["client_database_requests_required"] is True
    with pytest.raises(LiteratureAccessError, match="desktop-local literature_client MCP"):
        asyncio.run(search_pubmed_records("heart failure", limit=1))


def test_settings_rejects_unknown_literature_access_mode():
    with pytest.raises(ValidationError):
        Settings(literature_access_mode="unknown")
