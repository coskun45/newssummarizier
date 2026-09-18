"""
Regression tests for migrate_sqlite_to_postgres.py's core copy logic.

Exercises migrate_data()/target_has_data() against two temporary SQLite
engines (standing in for "source" and "target") rather than a real Postgres
instance — the FK-safe ordering, row-copying and already-has-data guard are
dialect-independent; only reset_sequence() is Postgres-only and is a no-op
here (see its dialect check).
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import migrate_sqlite_to_postgres as migrate_mod
from app.db import models
from app.db.database import Base
from migrate_sqlite_to_postgres import migrate_data, target_has_data

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_script_registers_all_models_when_imported_standalone():
    """Regression: the script used to import only `Base` (not `app.db.models`),
    so Base.metadata.sorted_tables was empty unless something else in the same
    process had already imported models — which pytest's own test collection
    always does, silently masking the bug in every other test in this file.
    Import in a fresh subprocess (no conftest.py involved) to catch it for real.
    """
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-ci")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import migrate_sqlite_to_postgres as m; "
            "n = len(m.Base.metadata.sorted_tables); "
            "assert n >= 13, f'expected >=13 registered tables, got {n}'",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _make_engine(tmp_path, name):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _seed_source(engine):
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        feed = models.Feed(url="https://example.com/rss", title="Test Feed")
        session.add(feed)
        session.commit()
        session.refresh(feed)

        topic = models.Topic(name="Test Topic")
        session.add(topic)
        session.commit()
        session.refresh(topic)

        article = models.Article(feed_id=feed.id, url="https://example.com/a1", title="A1")
        session.add(article)
        session.commit()
        session.refresh(article)

        session.add(models.ArticleTopic(article_id=article.id, topic_id=topic.id, confidence=0.9))
        session.commit()

        return feed.id, topic.id, article.id
    finally:
        session.close()


def test_migrate_data_copies_all_tables_in_fk_safe_order(tmp_path):
    source_engine = _make_engine(tmp_path, "source.db")
    target_engine = _make_engine(tmp_path, "target.db")
    feed_id, topic_id, article_id = _seed_source(source_engine)

    source_counts, target_counts = migrate_data(source_engine, target_engine)

    assert source_counts == target_counts
    assert source_counts["feeds"] == 1
    assert source_counts["topics"] == 1
    assert source_counts["articles"] == 1
    assert source_counts["article_topics"] == 1

    Session = sessionmaker(bind=target_engine)
    session = Session()
    try:
        migrated_article = session.get(models.Article, article_id)
        assert migrated_article is not None
        assert migrated_article.title == "A1"
        assert migrated_article.feed_id == feed_id  # FK target row exists (feeds copied first)
    finally:
        session.close()


def test_migrate_data_is_repeatable_with_empty_source(tmp_path):
    source_engine = _make_engine(tmp_path, "source_empty.db")
    target_engine = _make_engine(tmp_path, "target_empty.db")
    Base.metadata.create_all(bind=source_engine)

    source_counts, target_counts = migrate_data(source_engine, target_engine)

    assert all(count == 0 for count in source_counts.values())
    assert source_counts == target_counts
    assert target_has_data(target_engine) == (None, 0)


def test_target_has_data_reports_first_non_empty_table(tmp_path):
    source_engine = _make_engine(tmp_path, "source2.db")
    target_engine = _make_engine(tmp_path, "target2.db")
    _seed_source(source_engine)

    migrate_data(source_engine, target_engine)

    table_name, count = target_has_data(target_engine)
    assert table_name is not None
    assert count > 0


def test_main_refuses_when_database_url_is_still_sqlite(monkeypatch, capsys):
    """Regression guard: main() must refuse to run against a DATABASE_URL that
    still points at SQLite — running the copy against the wrong engine would
    silently no-op or point the "target" at the source itself."""
    monkeypatch.setattr(migrate_mod.settings, "database_url", "sqlite:///./news_summary.db")
    monkeypatch.setattr(sys, "argv", ["migrate_sqlite_to_postgres.py"])

    with pytest.raises(SystemExit) as exc_info:
        migrate_mod.main()

    assert exc_info.value.code == 1
    assert "HATA" in capsys.readouterr().out


def test_main_refuses_when_sqlite_source_file_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(migrate_mod.settings, "database_url", "postgresql+psycopg2://u:p@db:5432/bulten")
    missing_path = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(
        sys, "argv", ["migrate_sqlite_to_postgres.py", "--sqlite-path", str(missing_path)]
    )

    with pytest.raises(SystemExit) as exc_info:
        migrate_mod.main()

    assert exc_info.value.code == 1
    assert "HATA" in capsys.readouterr().out


def test_main_refuses_without_force_when_target_already_has_data(tmp_path, monkeypatch, capsys):
    """The whole point of the guard is to prevent an accidental second run from
    duplicating rows — verify main() actually stops instead of just
    target_has_data() (already covered above) in isolation."""
    source_engine = _make_engine(tmp_path, "source3.db")
    _seed_source(source_engine)

    target_engine = _make_engine(tmp_path, "target3.db")
    Base.metadata.create_all(bind=target_engine)
    Session = sessionmaker(bind=target_engine)
    session = Session()
    try:
        session.add(models.Feed(url="https://preexisting.example/rss", title="Preexisting"))
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(migrate_mod.settings, "database_url", "postgresql+psycopg2://u:p@db:5432/bulten")
    monkeypatch.setattr(migrate_mod, "target_engine", target_engine)
    monkeypatch.setattr(
        sys,
        "argv",
        ["migrate_sqlite_to_postgres.py", "--sqlite-path", str(tmp_path / "source3.db")],
    )

    with pytest.raises(SystemExit) as exc_info:
        migrate_mod.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "zaten" in out and "--force" in out

    # Guard didn't get bypassed: the source's feed row was never copied in.
    with target_engine.connect() as conn:
        count = conn.execute(Base.metadata.tables["feeds"].select()).mappings().all()
    assert len(count) == 1
