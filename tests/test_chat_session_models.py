from __future__ import annotations

from src.aris_apps.aiida.chat import service as chat_service
from src.aris_apps.aiida.chat.session_models import (
    MAX_CHAT_SESSION_MESSAGES,
    MAX_CHAT_SESSION_TAGS,
    normalize_chat_messages,
    normalize_chat_session_snapshot,
    normalize_chat_session_tags,
    serialize_chat_history,
    trim_text,
)

_AUTO_ENVIRONMENT_PROMPT = (
    "Current environment is quantumespresso. Available AiiDA codes are listed above. "
    "Submission draft generation is supported."
)


def test_normalize_chat_messages_filters_entries_and_bounds_history() -> None:
    raw_messages = [
        {
            "role": "assistant",
            "text": f"Message {index}",
            "status": "done",
            "turn_id": index,
            "payload": {"index": index},
        }
        for index in range(MAX_CHAT_SESSION_MESSAGES + 2)
    ]
    raw_messages.insert(1, "invalid")

    normalized = normalize_chat_messages(raw_messages)

    assert len(normalized) == MAX_CHAT_SESSION_MESSAGES
    assert normalized[0]["turn_id"] == 2
    assert normalized[-1]["payload"] == {"index": MAX_CHAT_SESSION_MESSAGES + 1}


def test_serialize_chat_history_keeps_only_supported_message_fields() -> None:
    serialized = serialize_chat_history(
        [
            {
                "role": "assistant",
                "text": "Ready",
                "status": "done",
                "turn_id": 4,
                "payload": {"type": "SUBMISSION_DRAFT"},
                "internal": "not persisted",
            }
        ]
    )

    assert serialized == [
        {
            "role": "assistant",
            "text": "Ready",
            "status": "done",
            "turn_id": 4,
            "payload": {"type": "SUBMISSION_DRAFT"},
        }
    ]


def test_normalize_chat_session_tags_deduplicates_trims_and_limits() -> None:
    raw_tags = [" bands ", "#BANDS", "", *[f"tag-{index}" for index in range(20)]]

    normalized = normalize_chat_session_tags(raw_tags)

    assert normalized[0] == "#bands"
    assert len(normalized) == MAX_CHAT_SESSION_TAGS
    assert normalize_chat_session_tags(["x" * 40]) == [trim_text("#" + "x" * 40, limit=32)]


def test_normalize_chat_session_snapshot_cleans_context_and_preferences() -> None:
    normalized = normalize_chat_session_snapshot(
        {
            "context_nodes": [
                {"pk": "12", "label": " Silicon ", "node_type": "StructureData"},
                {"pk": 12, "label": "duplicate"},
                {"pk": "invalid"},
            ],
            "pinned_nodes": [{"pk": 19}],
            "selected_group": " group-a ",
            "selected_model": " gemini-flash-latest ",
            "session_environment": " QuantumESPRESSO ",
            "session_environment_auto": False,
            "environment_python_path": " /env/bin/python ",
            "environment_active_python_path": "",
            "session_prompt_override": f"Keep four decimals.\n\n{_AUTO_ENVIRONMENT_PROMPT}",
            "session_parameters": [
                {"key": " ecutwfc ", "value": " 40 Ry "},
                {"key": "ECUTWFC", "value": "80 Ry"},
                {"key": "", "value": "ignored"},
            ],
        }
    )

    assert normalized == {
        "context_nodes": [
            {
                "pk": 12,
                "label": "Silicon",
                "formula": None,
                "node_type": "StructureData",
            }
        ],
        "pinned_nodes": [
            {
                "pk": 19,
                "label": "#19",
                "formula": None,
                "node_type": "Unknown",
            }
        ],
        "selected_group": "group-a",
        "selected_model": "gemini-flash-latest",
        "session_environment": "quantumespresso",
        "session_environment_auto": False,
        "environment_python_path": "/env/bin/python",
        "environment_active_python_path": None,
        "prompt_override": "Keep four decimals.",
        "session_parameters": [{"key": "ecutwfc", "value": "40 Ry"}],
    }


def test_chat_service_preserves_normalization_compatibility_exports() -> None:
    assert chat_service._normalize_chat_messages is normalize_chat_messages
    assert chat_service._normalize_chat_session_snapshot is normalize_chat_session_snapshot
    assert chat_service._normalize_chat_session_tags is normalize_chat_session_tags
    assert chat_service.serialize_chat_history is serialize_chat_history
