import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel import create_engine

import app.db as database


# Keep pytest data in-process so test cleanup never touches the local demo database.
database.engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(autouse=True)
def reset_database():
    SQLModel.metadata.drop_all(database.engine)
    SQLModel.metadata.create_all(database.engine)
    yield
