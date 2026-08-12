from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Literal


class Settings(BaseSettings):
    app_name: str = "Literature Review Agent Backend"
    database_url: str = "sqlite:///./literature_review_agent.db"
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    # Controls where external literature databases may be reached.
    # client_online keeps this backend as the system of record but requires the
    # desktop-local MCP connector to perform PubMed/Europe PMC requests.
    literature_access_mode: Literal["online", "client_online", "offline", "auto"] = "auto"
    literature_import_dir: str = str(Path(__file__).resolve().parents[4] / "runtime" / "literature-imports")
    offline_evidence_package_dir: str = str(Path(__file__).resolve().parents[4] / "data" / "offline-evidence-packages")
    # This key is deliberately not exposed to MCP or the model runtime.
    study_design_approval_key: str | None = None
    research_writing_approval_key: str | None = None
    systematic_evidence_approval_key: str | None = None
    randomization_storage_dir: str = "runtime/study-design-randomization"
    # Shared only by the OpenCode runtime plugin and this backend; never exposed to the model.
    skill_receipt_key: str | None = None
    skill_receipt_dir: str = str(Path(__file__).resolve().parents[4] / "runtime" / "skill-receipts")
    # A protected research workflow must not advance without signed evidence of the
    # required Skill calls. Development environments can explicitly set this to warn.
    skill_receipt_enforcement: Literal["warn", "strict"] = "strict"

    model_config = SettingsConfigDict(
        env_prefix="LRA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
