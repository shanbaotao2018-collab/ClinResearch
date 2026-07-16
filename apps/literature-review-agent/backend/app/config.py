from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "Literature Review Agent Backend"
    database_url: str = "sqlite:///./literature_review_agent.db"
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    # This key is deliberately not exposed to MCP or the model runtime.
    study_design_approval_key: str | None = None
    research_writing_approval_key: str | None = None
    randomization_storage_dir: str = "runtime/study-design-randomization"
    # Shared only by the OpenCode runtime plugin and this backend; never exposed to the model.
    skill_receipt_key: str | None = None
    skill_receipt_dir: str = str(Path(__file__).resolve().parents[4] / "runtime" / "skill-receipts")

    model_config = SettingsConfigDict(
        env_prefix="LRA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
