from __future__ import annotations

import httpx

from app.config import settings


class LiteratureAccessError(RuntimeError):
    """A deployment policy or connectivity error for external literature sources."""


def literature_access_status() -> dict[str, object]:
    """Return the active retrieval policy without performing a network request."""
    mode = settings.literature_access_mode
    client_online = mode == "client_online"
    return {
        "mode": mode,
        "live_database_requests_enabled": mode not in {"offline", "client_online"},
        "client_database_requests_required": client_online,
        "offline_file_import_enabled": True,
        "auto_fallback_enabled": mode == "auto",
        "supported_online_sources": ["pubmed", "europe_pmc"] if mode != "offline" else [],
        "next_step": (
            "List validated local packages with list_offline_evidence_packages, then import one with "
            "import_offline_evidence_package; use import_citations_file_to_project only for a loose "
            "RIS, NBIB, CSV, or JSON file."
            if mode == "offline"
            else "Use the desktop-local literature_client MCP for PubMed and Europe PMC retrieval, then import its normalized records into this backend. Do not call this backend's server-side search tools."
            if client_online
            else "Use the live search tools; auto mode will return an offline-import instruction if a source is unreachable."
        ),
    }


def require_live_literature_access(source: str) -> None:
    """Block network retrieval before a request when the server is offline-only."""
    if settings.literature_access_mode == "offline":
        raise LiteratureAccessError(
            f"{source} retrieval is disabled because LRA_LITERATURE_ACCESS_MODE=offline. "
            "Import a RIS, NBIB, CSV, or JSON citation file with import_citations_file_to_project instead."
        )
    if settings.literature_access_mode == "client_online":
        raise LiteratureAccessError(
            f"{source} retrieval is disabled on this server because LRA_LITERATURE_ACCESS_MODE=client_online. "
            "Use the desktop-local literature_client MCP, then import its normalized records into this backend."
        )


def translate_literature_request_error(source: str, error: httpx.HTTPError) -> LiteratureAccessError | None:
    """In auto mode, convert a failed live request into an actionable offline fallback."""
    if settings.literature_access_mode != "auto":
        return None
    return LiteratureAccessError(
        f"{source} is unreachable from this server ({error.__class__.__name__}). "
        "The deployment is in auto mode; use import_citations_file_to_project to continue from an exported "
        "RIS, NBIB, CSV, or JSON citation file."
    )
