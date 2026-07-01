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
