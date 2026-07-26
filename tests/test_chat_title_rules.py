from __future__ import annotations

from src.aris_apps.aiida.chat import service as chat_service
from src.aris_apps.aiida.chat.title_rules import (
    DEFAULT_SESSION_TITLE,
    TITLE_STAGE_CONTEXT_SWITCH,
    TITLE_STAGE_DEEP_SUMMARY,
    TITLE_STAGE_INITIAL,
    build_title_context_key,
    build_title_generation_prompt,
    looks_like_session_identifier_title,
    normalize_session_title,
    normalize_title_state,
    sanitize_generated_title,
    sanitize_session_title_text,
    should_schedule_title_generation,
    slugify_session_name,
)


def _snapshot(*, pk: int | None = None, group: str | None = None) -> dict:
    pinned_nodes = []
    if pk is not None:
        pinned_nodes.append(
            {
                "pk": pk,
                "label": "Silicon",
                "formula": "Si",
                "node_type": "StructureData",
            }
        )
    return {
        "pinned_nodes": pinned_nodes,
        "context_nodes": [],
        "selected_group": group,
        "session_environment": "research",
    }


def test_title_text_normalization_and_slugging_are_provider_independent() -> None:
    assert sanitize_session_title_text("Title: `Si Bands`") == "Si Bands"
    assert normalize_session_title("硅能带") == DEFAULT_SESSION_TITLE
    assert slugify_session_name("GaAs Étude") == "gaas-etude"
    assert len(sanitize_generated_title("A deliberately verbose research title", "Fallback")) <= 12


def test_identifier_titles_are_detected_for_legacy_migration() -> None:
    session_id = "6b1499a6d6ac4f12a3f86d164b37d53e"

    assert looks_like_session_identifier_title(session_id, session_id)
    assert looks_like_session_identifier_title(
        "6b1499a6-d6ac-4f12-a3f8-6d164b37d53e",
        "different",
    )
    assert not looks_like_session_identifier_title("Si Bands", session_id)


def test_title_context_key_is_stable_and_changes_with_research_context() -> None:
    first = build_title_context_key(_snapshot(pk=101, group="semiconductor"))
    same = build_title_context_key(_snapshot(pk=101, group="semiconductor"))
    changed = build_title_context_key(_snapshot(pk=102, group="semiconductor"))

    assert first
    assert first == same
    assert first != changed


def test_title_prompt_contains_session_context_without_runtime_access() -> None:
    prompt = build_title_generation_prompt(
        {
            "title": DEFAULT_SESSION_TITLE,
            "title_first_intent": "Inspect this structure",
            "snapshot": _snapshot(pk=101, group="semiconductor"),
            "messages": [
                {"role": "user", "text": "Inspect this structure", "turn_id": 1},
                {"role": "assistant", "text": "Silicon is ready.", "turn_id": 1},
            ],
        },
        stage=TITLE_STAGE_INITIAL,
        completed_turn_id=1,
    )

    assert "Stage: Initial Naming" in prompt
    assert "First user request: Inspect this structure" in prompt
    assert "Si (#101), type=StructureData" in prompt
    assert "Selected group: semiconductor" in prompt


def test_title_schedule_rules_cover_initial_context_switch_and_deep_summary() -> None:
    initial_session = {
        "auto_title": True,
        "title_state": "idle",
        "title_generation_count": 0,
        "title_last_generated_turn": 0,
        "snapshot": _snapshot(),
        "messages": [{"role": "user", "text": "Start", "turn_id": 1}],
    }
    assert should_schedule_title_generation(initial_session, 1) == TITLE_STAGE_INITIAL

    context_switch_session = {
        **initial_session,
        "title_state": "ready",
        "title_generation_count": 1,
        "title_last_generated_turn": 1,
        "title_last_context_key": build_title_context_key(_snapshot(pk=101)),
        "snapshot": _snapshot(pk=102),
    }
    assert should_schedule_title_generation(context_switch_session, 2) == TITLE_STAGE_CONTEXT_SWITCH

    deep_summary_session = {
        **initial_session,
        "title_state": "ready",
        "title_generation_count": 1,
        "title_last_generated_turn": 1,
        "title_last_context_key": "",
        "messages": [
            {"role": "user", "text": f"Question {turn_id}", "turn_id": turn_id}
            for turn_id in range(1, 7)
        ],
    }
    assert should_schedule_title_generation(deep_summary_session, 6) == TITLE_STAGE_DEEP_SUMMARY


def test_pending_or_manual_title_does_not_schedule_generation() -> None:
    session = {
        "auto_title": True,
        "title_state": "pending",
        "title_generation_count": 0,
        "snapshot": _snapshot(),
        "messages": [{"role": "user", "text": "Start", "turn_id": 1}],
    }

    assert normalize_title_state(" PENDING ") == "pending"
    assert should_schedule_title_generation(session, 1) is None
    session["auto_title"] = False
    session["title_state"] = "idle"
    assert should_schedule_title_generation(session, 1) is None


def test_chat_service_preserves_title_rule_compatibility_aliases() -> None:
    assert chat_service._build_title_context_key is build_title_context_key
    assert chat_service._build_title_generation_prompt is build_title_generation_prompt
    assert chat_service._normalize_session_title is normalize_session_title
    assert chat_service._should_schedule_title_generation is should_schedule_title_generation
    assert chat_service._slugify_session_name is slugify_session_name
