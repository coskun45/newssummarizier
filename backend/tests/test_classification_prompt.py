"""
Tests for the classification system prompt assembly (editable criteria + locked block) and the
seed migration of stored prompts. No network access.
"""
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import crud, seed
from app.services import summary_service
from app.services.summary_service import (
    build_classification_locked_text,
    build_classification_system_prompt,
)
from tests.conftest import _make_topic


@pytest.fixture
def topics(db_session):
    return [
        _make_topic(db_session, "NATO", description="Bündnis"),
        _make_topic(db_session, "Ukrayna Savaşı"),
    ]


@pytest.mark.parametrize("user_text", [
    "",
    "   ",
    "Sadece kısa bir kriter.",
    "Eski prompt.\nTOPIC LİSTESİ:\n{topic_list}\n{topic_list}",
])
def test_locked_block_is_always_appended(topics, user_text):
    """However the user edits the text, the topic list and the JSON contract are still sent."""
    prompt = build_classification_system_prompt(user_text, topics)

    assert "- NATO: Bündnis" in prompt and "- Ukrayna Savaşı" in prompt
    assert '"importance": "unimportant"' in prompt
    assert '"confidence"' in prompt and "confidence >= 0.5" in prompt
    # OpenAI rejects response_format=json_object unless the messages mention "JSON".
    assert "JSON" in prompt
    assert "{topic_list}" not in prompt
    assert prompt.endswith(build_classification_locked_text(topics))


def test_user_text_comes_first_and_is_untouched(topics):
    prompt = build_classification_system_prompt("MY CRITERIA", topics)
    assert prompt.startswith("MY CRITERIA\n\n---")


def test_locked_text_follows_live_topics(db_session, topics):
    before = build_classification_locked_text(crud.get_topics(db_session))
    assert "Yeni Konu" not in before

    _make_topic(db_session, "Yeni Konu", description="Tanım")
    after = build_classification_locked_text(crud.get_topics(db_session))

    assert "- Yeni Konu: Tanım" in after


def test_locked_text_example_uses_real_topic_names(topics):
    locked = build_classification_locked_text(topics)
    assert '{"name": "NATO", "confidence": 0.95}' in locked


def test_locked_text_without_topics_still_valid():
    locked = build_classification_locked_text([])
    assert "(tanımlı konu yok)" in locked and "<konu adı>" in locked and "JSON" in locked


def test_default_prompt_holds_only_editable_criteria():
    default = summary_service._CATEGORIZATION_SYSTEM_PROMPT
    assert "{topic_list}" not in default
    assert '"importance"' not in default and "confidence" not in default


# --- seed migration ------------------------------------------------------------------------

@pytest.fixture
def seed_db(monkeypatch, db_session):
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    return db_session


def _stored(db_session):
    db_session.expire_all()
    return crud.get_system_prompt(db_session, "classification").prompt_text


def test_seed_resets_legacy_prompt_with_topic_list_placeholder(seed_db):
    crud.upsert_system_prompt(seed_db, "classification", "Eski prompt\n{topic_list}\nJSON formatı...", True)

    seed.seed_system_prompts()

    assert _stored(seed_db) == summary_service._CATEGORIZATION_SYSTEM_PROMPT


def test_seed_keeps_user_edited_prompt_without_placeholder(seed_db):
    crud.upsert_system_prompt(seed_db, "classification", "Benim kriterlerim", True)

    seed.seed_system_prompts()
    seed.seed_system_prompts()

    assert _stored(seed_db) == "Benim kriterlerim"


def test_seed_migration_does_not_touch_summarization(seed_db):
    crud.upsert_system_prompt(seed_db, "summarization", "Özel özet promptu", True)

    seed.seed_system_prompts()

    seed_db.expire_all()
    assert crud.get_system_prompt(seed_db, "summarization").prompt_text == "Özel özet promptu"


def test_locked_text_does_not_resubstitute_placeholders_inside_topic_text(db_session):
    """A topic description that looks like a template placeholder must show up verbatim."""
    topics = [
        _make_topic(db_session, "NATO", description="siehe {topics_example} und {topics}"),
        _make_topic(db_session, "Ukrayna Savaşı"),
    ]

    locked = build_classification_locked_text(topics)

    assert "- NATO: siehe {topics_example} und {topics}" in locked
    assert locked.count('"confidence": 0.95') == 1  # the real example appears once, not injected into the list


def test_seed_classification_migration_runs_only_once(seed_db):
    """Once migrated, a prompt an admin saves with the legacy placeholder survives restarts."""
    crud.upsert_system_prompt(seed_db, "classification", "Eski prompt\n{topic_list}", True)

    seed.seed_system_prompts()  # first start after the upgrade: migrates
    assert _stored(seed_db) == summary_service._CATEGORIZATION_SYSTEM_PROMPT

    crud.upsert_system_prompt(seed_db, "classification", "Benim kriterlerim {topic_list}", True)
    seed.seed_system_prompts()  # later restart: must not overwrite the admin's edit

    assert _stored(seed_db) == "Benim kriterlerim {topic_list}"


def test_seed_marks_fresh_install_as_migrated(seed_db):
    seed.seed_system_prompts()
    assert crud.get_setting(seed_db, seed.CLASSIFICATION_MIGRATION_KEY) == "1"

    crud.upsert_system_prompt(seed_db, "classification", "Kriter {topic_list}", True)
    seed.seed_system_prompts()

    assert _stored(seed_db) == "Kriter {topic_list}"
