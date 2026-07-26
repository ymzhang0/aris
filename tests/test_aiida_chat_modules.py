from __future__ import annotations

from src.aris_apps.aiida.chat.batch_progress import (
    _classify_batch_process_status,
    _summarize_chat_session_batch_progress,
)
from src.aris_apps.aiida.chat.context import (
    _build_user_message_payload,
    _strip_auto_environment_prompt,
    normalize_context_node_ids,
)
from src.aris_apps.aiida.chat.message_payloads import _merge_message_payload


def test_chat_context_protocol_normalizes_node_ids_without_domain_keywords() -> None:
    assert normalize_context_node_ids(["7", 7, -1, "11", "bad"]) == [7, 11]


def test_chat_context_payload_keeps_explicit_preferences() -> None:
    payload = _build_user_message_payload(
        {
            "session_environment": "PROJECT",
            "session_parameters": [{"key": "ecutwfc", "value": "60"}],
        },
        [8],
    )

    assert payload == {
        "context_pks": [8],
        "session_environment": "project",
        "session_parameters": [{"key": "ecutwfc", "value": "60"}],
    }


def test_auto_environment_prompt_removal_preserves_user_override() -> None:
    prompt = (
        "Current environment is demo. Available AiiDA plugins: pw. "
        "Submission draft generation is supported. Standard project layout uses "
        "codes/<filename>.py.\n\nUse 80 Ry for this session."
    )

    assert _strip_auto_environment_prompt(prompt) == "Use 80 Ry for this session."


def test_message_payload_merge_deduplicates_protocol_status() -> None:
    merged = _merge_message_payload(
        {
            "tool_calls": ["inspect_node"],
            "status": {"steps": ["Inspecting node"]},
        },
        {
            "tool_calls": ["inspect_node", "get_bands"],
            "status": {"steps": ["Inspecting node", "Loading bands"]},
        },
    )

    assert merged == {
        "tool_calls": ["inspect_node", "get_bands"],
        "status": {"steps": ["Inspecting node", "Loading bands"]},
    }


def test_batch_progress_uses_process_state_and_exit_status() -> None:
    assert _classify_batch_process_status({"process_state": "finished", "exit_status": 0}) == "success"
    assert _classify_batch_process_status({"process_state": "finished", "exit_status": 300}) == "failed"

    summary = _summarize_chat_session_batch_progress(
        session_id="session-1",
        title="Batch",
        session_group_label="Project/batch",
        nodes=[
            {"pk": 1, "process_state": "running", "process_label": "PwBaseWorkChain"},
            {"pk": 2, "process_state": "finished", "exit_status": 0, "process_label": "PwBaseWorkChain"},
        ],
    )

    assert summary is not None
    assert summary["total"] == 2
    assert summary["running"] == 1
    assert summary["success"] == 1
    assert summary["percent"] == 50
