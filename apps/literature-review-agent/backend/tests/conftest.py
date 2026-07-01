import pytest
from sqlmodel import SQLModel

from app.db import engine
from app.models import AuditLog, Citation, Project, SearchStrategyVersion


@pytest.fixture(autouse=True)
def reset_database():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
