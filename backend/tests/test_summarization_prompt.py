"""
Tests for the locked (read-only) part of the summarization prompt. No network access.
"""
from app.services import summary_service
from app.services.summary_service import DEFAULT_SUMMARY_INSTRUCTIONS, build_summarization_locked_text


def test_default_lists_all_types_in_canonical_order():
    locked = build_summarization_locked_text()
    positions = [locked.index(f"{t}: ") for t in ("brief", "standard", "detailed")]
    assert positions == sorted(positions)


def test_only_requested_types_are_listed_in_canonical_order_and_unknown_ignored():
    locked = build_summarization_locked_text(["detailed", "brief", "bogus"])

    assert f"brief: {DEFAULT_SUMMARY_INSTRUCTIONS['brief']}" in locked
    assert f"detailed: {DEFAULT_SUMMARY_INSTRUCTIONS['detailed']}" in locked
    assert "standard: " not in locked and "bogus" not in locked
    assert locked.index("brief: ") < locked.index("detailed: ")


def test_instruction_override_replaces_only_that_type_and_blank_falls_back():
    locked = build_summarization_locked_text(["brief", "standard"], {"brief": "Nur ein Satz.", "standard": ""})

    assert "brief: Nur ein Satz." in locked
    assert f"standard: {DEFAULT_SUMMARY_INSTRUCTIONS['standard']}" in locked


def test_no_types_shows_placeholder_and_keeps_language_line():
    locked = build_summarization_locked_text([])

    assert "(etkin özet türü yok)" in locked
    assert locked.rstrip().endswith(summary_service.SUMMARY_LANGUAGE_INSTRUCTION)


def test_locked_text_is_built_from_the_pieces_the_playground_receives(db_session):
    """The playground joins these pieces itself, so they must be exactly what the text is made of."""
    pieces = summary_service.get_pipeline_settings(db_session)["summarization_locked"]
    locked = build_summarization_locked_text(["brief"])

    assert locked.startswith(pieces["heading"])
    assert locked.endswith(pieces["language_line"])
    assert summary_service.SUMMARY_LANGUAGE_INSTRUCTION in pieces["language_line"]
