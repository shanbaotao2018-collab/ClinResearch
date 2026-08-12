from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_unified_backend_hosts_mcp_and_exposes_its_access_policy(monkeypatch):
    """The workbench API and OpenCode MCP transport share one backend setting."""
    monkeypatch.setattr(settings, "literature_access_mode", "offline")
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["literature_access"]["mode"] == "offline"

        initialized = client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Host": "127.0.0.1:8010",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]

        status = client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id,
                "Host": "127.0.0.1:8010",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_literature_access_status", "arguments": {}},
            },
        )

    assert status.status_code == 200
    assert '\\"mode\\": \\"offline\\"' in status.text
