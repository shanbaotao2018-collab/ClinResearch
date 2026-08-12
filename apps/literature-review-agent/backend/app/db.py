from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from .config import settings

engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # This MVP keeps a local SQLite database. `create_all` does not add columns
    # to an existing table, so apply the two safe additive migrations here.
    with engine.begin() as connection:
        project_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(project)"))
        }
        if "review_mode" not in project_columns:
            connection.execute(text(
                "ALTER TABLE project ADD COLUMN review_mode TEXT NOT NULL DEFAULT 'formal_review'"
            ))
        availability_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(fulltextavailability)"))
        }
        if "local_cache_path" not in availability_columns:
            connection.execute(text(
                "ALTER TABLE fulltextavailability ADD COLUMN local_cache_path TEXT"
            ))
        writing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(researchwritingdraft)"))
        }
        if "review_draft" not in writing_columns:
            connection.execute(text(
                "ALTER TABLE researchwritingdraft ADD COLUMN review_draft TEXT"
            ))


def get_session():
    with Session(engine) as session:
        yield session
