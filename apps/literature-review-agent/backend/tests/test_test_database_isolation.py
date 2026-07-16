from app.db import engine


def test_suite_uses_an_ephemeral_database():
    assert engine.url.database in (None, "")
