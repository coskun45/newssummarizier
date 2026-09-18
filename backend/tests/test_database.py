"""
Regression tests for app.db.database.init_db()'s idempotent column-migration loop.
"""
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.db import database as db_module


def test_init_db_rolls_back_after_failed_alter(tmp_path, monkeypatch):
    """Regression: a failed ALTER used to leave the shared connection with no
    rollback, so on a strict-transaction dialect (Postgres) the aborted
    transaction would silently break every later statement on that same
    connection (the remaining ALTERs, the CREATE INDEX) too — not just the
    one that actually failed. SQLite never surfaced this because a failed
    statement there doesn't poison the rest of the connection, which is
    exactly why it went unnoticed until Postgres became a real target.

    Simulates Postgres's "current transaction is aborted" behavior (which a
    plain SQLite engine won't reproduce on its own) by making the ALTER for
    'priority' fail once, then poisoning further statements on the same
    connection until something calls .rollback() — the real fix.
    """
    legacy_db = tmp_path / "legacy.db"
    test_engine = create_engine(f"sqlite:///{legacy_db}")

    # A pre-existing "articles" table missing every column init_db() is
    # supposed to backfill (importance/priority/is_read/is_starred/image_url) —
    # standing in for a database created before those columns existed.
    with test_engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE articles ("
                "id INTEGER PRIMARY KEY, feed_id INTEGER, url VARCHAR, title VARCHAR"
                ")"
            )
        )
        conn.commit()

    monkeypatch.setattr(db_module, "engine", test_engine)

    original_execute = Connection.execute
    original_rollback = Connection.rollback
    state = {"failed_once": False, "poisoned": False, "rollback_called": False}

    def fake_execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "ADD COLUMN priority" in sql and not state["failed_once"]:
            state["failed_once"] = True
            state["poisoned"] = True
            raise OperationalError("stmt", {}, Exception("simulated Postgres failure"))
        if state["poisoned"]:
            raise OperationalError("stmt", {}, Exception("current transaction is aborted"))
        return original_execute(self, statement, *args, **kwargs)

    def fake_rollback(self, *args, **kwargs):
        state["poisoned"] = False
        state["rollback_called"] = True
        return original_rollback(self, *args, **kwargs)

    with patch.object(Connection, "execute", fake_execute), patch.object(
        Connection, "rollback", fake_rollback
    ):
        db_module.init_db()

    assert state["rollback_called"], "init_db() must roll back after a failed ALTER"

    inspector = inspect(test_engine)
    cols = {c["name"] for c in inspector.get_columns("articles")}
    # 'priority' itself was made to fail and is expected to stay missing, but a
    # single failed column must not cascade into blocking the others.
    assert "is_read" in cols
    assert "is_starred" in cols
    assert "image_url" in cols
