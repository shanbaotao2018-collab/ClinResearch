from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Literature Review Agent Backend"
    database_url: str = "sqlite:///./literature_review_agent.db"
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    model_config = SettingsConfigDict(
        env_prefix="LRA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
