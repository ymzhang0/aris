"""Tests for chat context metadata normalization and priority injection."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "dummy")

from src.aris_apps.aiida.agent import researcher
from src.aris_apps.aiida.agent.runtime import PydanticAIGeminiRuntime
from src.aris_apps.aiida.chat import service as chat_service


class _Memory:
    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def get_kv(self, key: str):
        return self._values.get(key)

    def set_kv(self, key: str, value: object) -> None:
        self._values[key] = value


def _make_chat_state() -> SimpleNamespace:
    chat_service.settings.ARIS_MEMORY_DIR = tempfile.mkdtemp(prefix="aris-chat-memory-")
    chat_service.settings.ARIS_PROJECTS_ROOT = tempfile.mkdtemp(prefix="aris-chat-projects-")
    return SimpleNamespace(memory=_Memory(), chat_version=0)


def _session_file_path(session_id: str) -> Path:
    return Path(chat_service.settings.ARIS_MEMORY_DIR) / "sessions" / f"{session_id}.json"


_AUTO_ENVIRONMENT_PROMPT = (
    "Context: Current environment is demo-project. Mode: worker default interpreter. "
    "Available AiiDA plugins: quantumespresso.*: quantumespresso.pw.base, quantumespresso.pw.relax. "
    "Submission draft generation is supported in both worker-default and project-interpreter modes when the worker can validate the request. "
    "Standard project layout: save reusable Python scripts under codes/ and exported results under data/. "
    "When suggesting a save location, explicitly recommend codes/<filename>.py."
)


def test_create_chat_session_defaults_to_new_conversation_title() -> None:
    state = _make_chat_state()

    session = chat_service.create_chat_session(state)

    assert session["title"] == "New Conversation"
    assert session["auto_title"] is True
    assert session["title_state"] == "idle"


def test_update_chat_session_manual_title_marks_title_ready() -> None:
    state = _make_chat_state()
    session = chat_service.create_chat_session(state)

    updated = chat_service.update_chat_session(state, session["id"], title="Si能带任务")

    assert updated is not None
    assert updated["title"] == "Si"
    assert updated["session_slug"] == "si"
    assert updated["auto_title"] is False
    assert updated["title_state"] == "ready"


def test_chat_sessions_persist_each_session_to_dedicated_file(tmp_path) -> None:
    state = _make_chat_state()
    original_memory_dir = chat_service.settings.ARIS_MEMORY_DIR
    chat_service.settings.ARIS_MEMORY_DIR = str(tmp_path)
    try:
        session = chat_service.create_chat_session(state, title="Si EOS", activate=True)
        history = chat_service.get_chat_history(state, session["id"])
        history.append({"role": "user", "text": "run eos", "turn_id": 1})
        history.append({"role": "assistant", "text": "draft ready", "turn_id": 1, "status": "done"})
        chat_service._touch_chat_sessions(state)
        chat_service._persist_chat_session_store(state)
        session_file = _session_file_path(session["id"])
        persisted_index = state.memory.get_kv(chat_service._CHAT_SESSIONS_KV_KEY)
    finally:
        chat_service.settings.ARIS_MEMORY_DIR = original_memory_dir

    assert session_file.is_file()
    payload = json.loads(session_file.read_text(encoding="utf-8"))
    assert [message["text"] for message in payload["messages"]] == ["run eos", "draft ready"]
    assert isinstance(persisted_index, dict)
    assert "messages" not in persisted_index["sessions"][0]


def test_chat_sessions_reload_messages_from_session_files(tmp_path) -> None:
    original_memory_dir = chat_service.settings.ARIS_MEMORY_DIR
    chat_service.settings.ARIS_MEMORY_DIR = str(tmp_path)
    try:
        state = _make_chat_state()
        created = chat_service.create_chat_session(state, title="Bands", activate=True)
        history = chat_service.get_chat_history(state, created["id"])
        history.append({"role": "user", "text": "plot bands", "turn_id": 1})
        history.append({"role": "assistant", "text": "done", "turn_id": 1, "status": "done"})
        chat_service._touch_chat_sessions(state)
        chat_service._persist_chat_session_store(state)

        reloaded_state = SimpleNamespace(memory=state.memory, chat_version=0)
        detail = chat_service.get_chat_session_detail(reloaded_state, created["id"])
    finally:
        chat_service.settings.ARIS_MEMORY_DIR = original_memory_dir

    assert detail is not None
    assert [message["text"] for message in detail["messages"]] == ["plot bands", "done"]


def test_chat_session_snapshot_preserves_environment_python_path() -> None:
    snapshot = chat_service._build_chat_session_snapshot(
        {
            "environment_python_path": "/tmp/project/.venv/bin/python",
            "session_environment": "qe",
        }
    )

    assert snapshot["environment_python_path"] == "/tmp/project/.venv/bin/python"


def test_normalize_task_mode_accepts_known_values() -> None:
    preview_service = chat_service._submission_preview_service

    assert preview_service.normalize_task_mode("single") == "single"
    assert preview_service.normalize_task_mode("batch") == "batch"
    assert preview_service.normalize_task_mode("none") == "none"
    assert preview_service.normalize_task_mode("  BATCH ") == "batch"


def test_normalize_task_mode_falls_back_to_none_for_unknown_values() -> None:
    preview_service = chat_service._submission_preview_service

    assert preview_service.normalize_task_mode("") == "none"
    assert preview_service.normalize_task_mode("eos") == "none"
    assert preview_service.normalize_task_mode(None) == "none"


def test_normalize_submission_request_accepts_batch_parameter_grid() -> None:
    request = chat_service._submission_preview_service.normalize_request(
        {
            "mode": "batch",
            "workchain": "quantumespresso.pw.base",
            "structure_pks": [19],
            "code": "pw@localhost",
            "protocol": "moderate",
            "parameter_grid": {"scale_factor": [0.96, 0.98, 1.0, 1.02, 1.04]},
        }
    )

    assert request is not None
    assert request["mode"] == "batch"
    assert request["structure_pks"] == [19]
    assert request["parameter_grid"] == {"scale_factor": [0.96, 0.98, 1.0, 1.02, 1.04]}


def test_chat_session_snapshot_preserves_active_environment_python_path() -> None:
    snapshot = chat_service._build_chat_session_snapshot(
        {
            "environment_active_python_path": "/tmp/worker-default/.venv/bin/python",
            "session_environment": "worker-default",
        }
    )

    assert snapshot["environment_active_python_path"] == "/tmp/worker-default/.venv/bin/python"


def test_build_worker_context_includes_environment_python_path() -> None:
    state = _make_chat_state()
    session = chat_service.create_chat_session(state, title="Injected preview", activate=True)
    stored_session, _store = chat_service._find_chat_session(state, session["id"])
    assert stored_session is not None
    stored_session["snapshot"] = chat_service._build_chat_session_snapshot(
        {"environment_python_path": "/tmp/project/.venv/bin/python"}
    )

    context = chat_service._build_worker_context(state, session["id"])

    assert context is not None
    assert context["python_interpreter_path"] == "/tmp/project/.venv/bin/python"


def test_build_worker_context_falls_back_to_active_environment_python_path() -> None:
    state = _make_chat_state()
    session = chat_service.create_chat_session(state, title="Worker default", activate=True)
    stored_session, _store = chat_service._find_chat_session(state, session["id"])
    assert stored_session is not None
    stored_session["snapshot"] = chat_service._build_chat_session_snapshot(
        {"environment_active_python_path": "/tmp/worker-default/.venv/bin/python"}
    )

    context = chat_service._build_worker_context(state, session["id"])

    assert context is not None
    assert context["python_interpreter_path"] == "/tmp/worker-default/.venv/bin/python"


def test_title_prompt_prefers_pinned_node_context() -> None:
    session = {
        "title": "New Conversation",
        "title_first_intent": "帮我看看这个结构",
        "snapshot": {
            "pinned_nodes": [
                {
                    "pk": 101,
                    "label": "Silicon",
                    "formula": "Si",
                    "node_type": "StructureData",
                }
            ],
            "context_nodes": [],
            "selected_group": "semiconductor",
            "selected_model": "gemini-flash-latest",
            "session_environment": "research",
            "session_environment_auto": True,
            "prompt_override": None,
            "session_parameters": [],
        },
        "messages": [
            {"role": "user", "text": "帮我看看这个结构", "turn_id": 1},
            {"role": "assistant", "text": "我先检查 Si 节点 #101。", "turn_id": 1, "status": "done"},
        ],
    }

    prompt = chat_service._build_title_generation_prompt(
        session,
        stage=chat_service._TITLE_STAGE_INITIAL,
        completed_turn_id=1,
    )

    assert "Silicon" in prompt or "Si" in prompt
    assert "#101" in prompt
    assert "First user request: 帮我看看这个结构" in prompt
    assert "ASCII only" in prompt


def test_should_schedule_deep_summary_after_sixth_user_turn() -> None:
    session = {
        "auto_title": True,
        "title_state": "ready",
        "title_generation_count": 1,
        "title_last_generated_turn": 1,
        "title_last_context_key": "same-context",
        "snapshot": {
            "pinned_nodes": [],
            "context_nodes": [],
            "selected_group": None,
            "selected_model": None,
            "session_environment": None,
            "session_environment_auto": True,
            "prompt_override": None,
            "session_parameters": [],
        },
        "messages": [
            {"role": "user", "text": f"问题 {index}", "turn_id": index}
            for index in range(1, 7)
        ],
    }

    stage = chat_service._should_schedule_title_generation(session, completed_turn_id=6)

    assert stage == chat_service._TITLE_STAGE_DEEP_SUMMARY


def test_merge_context_node_ids_prefers_union_of_fields() -> None:
    metadata = {
        "context_pks": [4, "8", 4],
        "context_node_pks": ["8", 10, "invalid"],
    }

    merged = chat_service._merge_context_node_ids([2, 4], metadata)

    assert merged == [2, 4, 8, 10]


def test_inject_context_priority_instruction_adds_primary_scope() -> None:
    intent = "Compare these nodes and summarize."

    scoped = chat_service._inject_context_priority_instruction(intent, [22, 35])

    assert "context_pks: [22, 35]" in scoped
    assert "Treat these PKs as the primary subjects" in scoped
    assert "USER REQUEST" in scoped
    assert intent in scoped


def test_build_chat_message_payload_includes_structured_task_mode() -> None:
    output = SimpleNamespace(task_mode="batch", data_payload={"source": "agent"})

    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        tool_calls=None,
        task_mode=output.task_mode,
    )

    assert payload is not None
    assert payload["task_mode"] == "batch"


def test_build_chat_message_payload_includes_structured_research_plan() -> None:
    plan = {
        "title": "Silicon EOS",
        "objective": "Determine the equilibrium volume and bulk modulus.",
        "stages": [{"id": "eos", "label": "Run volume sweep", "status": "ready"}],
        "assumptions": [{"label": "Functional", "value": "PBE", "source": "ai"}],
        "outputs": ["EOS fit"],
    }
    output = SimpleNamespace(task_mode="none", data_payload=None, research_plan=plan)

    payload = chat_service._submission_preview_service.build_message_payload(output)

    assert payload is not None
    assert payload["research_plan"] == plan


def test_build_chat_message_payload_includes_structure_resolution() -> None:
    output = SimpleNamespace(
        task_mode="none",
        data_payload=None,
        research_plan=None,
        structure_resolution=SimpleNamespace(
            model_dump=lambda mode: {
                "status": "selection_required",
                "query": {"formula": "Si"},
                "candidates": [],
            }
        ),
    )

    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        task_mode="none",
    )

    assert payload["structure_resolution"]["status"] == "selection_required"


def test_summarize_chat_session_batch_progress_counts_terminal_and_active_jobs() -> None:
    summary = chat_service._summarize_chat_session_batch_progress(
        session_id="session-1",
        title="Si Thermal Expansion",
        session_group_label="Test/session-1",
        nodes=[
            {"pk": 11, "label": "bands-1", "type": "WorkChainNode", "process_state": "finished", "exit_status": 0},
            {"pk": 12, "label": "bands-2", "type": "WorkChainNode", "process_state": "running", "exit_status": None},
            {"pk": 13, "label": "bands-3", "type": "WorkChainNode", "process_state": "created", "exit_status": None},
            {"pk": 14, "label": "bands-4", "type": "WorkChainNode", "process_state": "finished", "exit_status": 301},
            {"pk": 15, "label": "Si primitive", "type": "StructureData", "process_state": "N/A", "exit_status": None},
        ],
    )

    assert summary is not None
    assert summary["total"] == 4
    assert summary["done"] == 2
    assert summary["percent"] == 50
    assert summary["success"] == 1
    assert summary["running"] == 1
    assert summary["queued"] == 1
    assert summary["failed"] == 1


def test_get_chat_session_batch_progress_reads_session_group() -> None:
    state = _make_chat_state()
    session = chat_service.create_chat_session(state, title="Si Thermal Expansion", activate=True)
    captured: dict[str, object] = {}

    def _fake_inspect_group(group_label: str, *, limit: int = 500):
        captured["group_label"] = group_label
        captured["limit"] = limit
        return {
            "nodes": [
                {"pk": 21, "label": "bands-1", "type": "WorkChainNode", "process_state": "finished", "exit_status": 0},
                {"pk": 22, "label": "bands-2", "type": "WorkChainNode", "process_state": "waiting", "exit_status": None},
            ]
        }

    state.chat_group_gateway = SimpleNamespace(
        inspect_group=_fake_inspect_group,
        rename_group_label_if_available=lambda _old, _new: False,
    )

    summary = chat_service.get_chat_session_batch_progress(state, session["id"])

    assert summary is not None
    assert summary["label"] == "Si Thermal Expansion"
    assert summary["total"] == 2
    assert summary["success"] == 1
    assert summary["queued"] == 1
    assert captured["limit"] == 500
    assert captured["group_label"] == "Default Project/si-thermal-expansion"


def test_serialize_chat_history_keeps_payload() -> None:
    history = [
        {
            "role": "assistant",
            "text": "Validation ready",
            "status": "done",
            "turn_id": 3,
            "payload": {
                "type": "SUBMISSION_DRAFT",
                "submission_draft": {
                    "process_label": "PwBaseWorkChain",
                    "inputs": {},
                    "primary_inputs": {"structure": {"label": "Structure", "value": "PK 11", "pk": 11}},
                    "advanced_settings": {"num_machines": 2},
                    "meta": {"pk_map": [{"pk": 11}]},
                },
            },
        }
    ]

    serialized = chat_service.serialize_chat_history(history)

    assert serialized[0]["payload"]["type"] == "SUBMISSION_DRAFT"
    assert serialized[0]["payload"]["submission_draft"]["meta"]["pk_map"][0]["pk"] == 11


def test_build_chat_message_payload_includes_submission_draft_fields() -> None:
    submission_draft = chat_service._build_submission_draft_payload(
        {
            "builder": {
                "structure_pk": 11,
                "metadata": {
                    "options": {
                        "resources": {"num_machines": 2, "num_mpiprocs_per_machine": 8},
                    },
                    "computer": "localhost",
                },
            }
        },
        validation=None,
        validation_summary={"status": "VALIDATION_OK", "is_valid": True},
    )
    output = SimpleNamespace(data_payload={"submission_draft": submission_draft})

    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        tool_calls=["GET management.statistics", "POST submission.draft-builder"],
    )

    assert payload is not None
    assert payload["type"] == "SUBMISSION_DRAFT"
    assert payload["tool_calls"] == ["GET management.statistics", "POST submission.draft-builder"]
    submission_draft = payload["submission_draft"]
    assert submission_draft["inputs"]["structure_pk"] == 11
    assert submission_draft["primary_inputs"]["structure"]["pk"] == 11
    assert submission_draft["advanced_settings"]["num_machines"] == 2
    assert submission_draft["advanced_settings"]["num_mpiprocs_per_machine"] == 8
    assert submission_draft["meta"]["pk_map"][0]["pk"] == 11
    assert submission_draft["meta"]["target_computer"] == "localhost"
    assert submission_draft["meta"]["parallel_settings"]["num_machines"] == 2
    assert submission_draft["meta"]["validation_summary"]["status"] == "VALIDATION_OK"
    assert payload["approval_request"]["action"] == "submission.execute"
    assert payload["approval_request"]["status"] == "pending"
    assert payload["approval_request"]["scope"] == "single"
    assert len(payload["approval_request"]["resource_digest"]) == 64


def test_build_chat_message_payload_blocks_single_draft_for_batch_intent() -> None:
    output = SimpleNamespace(
        task_mode="batch",
        data_payload={
            "submission_draft": {
                "process_label": "PwBaseWorkChain",
                "inputs": {"structure_pk": 19},
                "meta": {"pk_map": [{"pk": 19}]},
            }
        },
    )
    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        tool_calls=None,
        task_mode=output.task_mode,
    )

    assert payload is not None
    assert payload["task_mode"] == "batch"
    assert "submission_draft" not in payload
    assert payload["status"] == "SUBMISSION_BLOCKED"
    assert payload["recovery_plan"]["issues"][0]["type"] == "batch_draft_required"


@pytest.mark.anyio
async def test_prepare_structured_submission_request_auto_builds_batch_preview(
    monkeypatch,
) -> None:
    async def _fake_submit_new_batch_workflow(ctx, **kwargs):  # noqa: ANN001
        assert kwargs["structure_pks"] == [19]
        assert kwargs["parameter_grid"] == {"scale_factor": [0.96, 0.98, 1.0, 1.02, 1.04]}
        return {
            "status": "SUBMISSION_DRAFT",
            "submission_draft": {
                "process_label": "PwBaseWorkChain",
                "inputs": {},
                "meta": {
                    "draft": [{}, {}, {}, {}, {}],
                    "structure_pks": [19],
                    "job_count": 5,
                },
            },
        }

    monkeypatch.setattr(researcher, "submit_new_batch_workflow", _fake_submit_new_batch_workflow)

    payload = await chat_service._submission_preview_service.prepare_request(
        {
            "mode": "batch",
            "workchain": "quantumespresso.pw.base",
            "structure_pks": [19],
            "code": "pw@localhost",
            "protocol": "moderate",
            "parameter_grid": {"scale_factor": [0.96, 0.98, 1.0, 1.02, 1.04]},
        },
        deps=SimpleNamespace(),
        tool_calls=[],
    )

    assert payload is not None
    assert payload["status"] == "SUBMISSION_DRAFT"
    assert payload["submission_draft"]["meta"]["job_count"] == 5


def test_build_chat_message_payload_extracts_submission_draft_from_output_payload() -> None:
    output = SimpleNamespace(
        data_payload={
            "type": "SUBMISSION_DRAFT",
            "submission_draft": {
                "process_label": "PwRelaxWorkChain",
                "inputs": {"structure_pk": 34},
                "meta": {"pk_map": [{"pk": 34}]},
            },
        }
    )
    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        tool_calls=None,
    )

    assert payload is not None
    assert payload["type"] == "SUBMISSION_DRAFT"
    assert payload["submission_draft"]["process_label"] == "PwRelaxWorkChain"
    assert payload["submission_draft"]["meta"]["pk_map"][0]["pk"] == 34


def test_build_chat_message_payload_surfaces_recovery_plan_and_next_step() -> None:
    output = SimpleNamespace(
        data_payload={
            "status": "SUBMISSION_BLOCKED",
            "next_step": "Inspect the spec, verify resources, and ask the user before retrying.",
            "recovery_plan": {
                "status": "blocked",
                "summary": "Missing required inputs: structure, code",
                "missing_ports": ["structure", "code"],
                "issues": [
                    {
                        "type": "missing_required_inputs",
                        "message": "Required inputs are still missing after builder construction: structure, code",
                    }
                ],
                "recommended_actions": [
                    {
                        "action": "inspect_spec",
                        "reason": "Review the WorkChain spec first.",
                    }
                ],
            },
        }
    )
    payload = chat_service._submission_preview_service.build_message_payload(
        output,
        tool_calls=["POST submission.draft-builder"],
    )

    assert payload is not None
    assert payload["status"] == "SUBMISSION_BLOCKED"
    assert payload["next_step"] == "Inspect the spec, verify resources, and ask the user before retrying."
    assert payload["recovery_plan"]["summary"] == "Missing required inputs: structure, code"
    assert payload["recovery_plan"]["missing_ports"] == ["structure", "code"]
    assert payload["tool_calls"] == ["POST submission.draft-builder"]


def test_render_canonical_submission_blocker_message_uses_protocol_data_only() -> None:
    message = chat_service._submission_preview_service.render_blocker_message(
        task_mode="batch",
        recovery_plan={
            "status": "blocked",
            "summary": "Missing required inputs: structure, code",
            "issues": [
                {
                    "type": "missing_required_inputs",
                    "message": "Required inputs are still missing after builder construction: structure, code",
                },
                {
                    "type": "resource_reference_unresolved",
                    "message": "Code qe-750-pw@lucia could not be resolved",
                },
            ],
        },
        next_step="Inspect the spec, verify resources, and ask the user before retrying.",
    )

    assert message is not None
    assert "ARIS could not prepare the batch submission preview yet." in message
    assert "Blocked reason: Missing required inputs: structure, code" in message
    assert "Required inputs are still missing after builder construction: structure, code" in message
    assert "Code qe-750-pw@lucia could not be resolved" in message
    assert "Next step: Inspect the spec, verify resources, and ask the user before retrying." in message


def test_normalize_submission_draft_payload_derives_batch_submit_draft_from_jobs() -> None:
    normalized = chat_service._normalize_submission_draft_payload(
        {
            "process_label": "quantumespresso.pw.base",
            "inputs": {"kpoints_distance": 0.3},
            "batch_aggregation": {
                "common": {"kpoints_distance": 0.3},
                "items": [
                    {"label": "Structure #6", "diff": {"structure": {"pk": 6}}},
                    {"label": "Structure #7", "diff": {"structure": {"pk": 7}}},
                ],
                "variable_paths": ["structure"],
            },
            "jobs": [
                {
                    "workchain": "quantumespresso.pw.base",
                    "structure_pk": 6,
                    "code": "pw@localhost",
                    "protocol": "fast",
                },
                {
                    "workchain": "quantumespresso.pw.base",
                    "structure_pk": 7,
                    "code": "pw@localhost",
                    "protocol": "fast",
                },
            ],
            "meta": {"workchain": "quantumespresso.pw.base"},
        },
        draft=None,
        validation=None,
        validation_summary=None,
    )

    assert isinstance(normalized["meta"]["draft"], list)
    assert normalized["meta"]["draft"][0]["structure_pk"] == 6
    assert normalized["meta"]["draft"][1]["structure_pk"] == 7
    assert normalized["meta"]["preview_mode"] == "batch"
    assert normalized["meta"]["preview_overview"]["job_count"] == 2
    assert normalized["meta"]["preview_overview"]["varying_paths"] == ["structure"]
    assert normalized["batch_aggregation"]["variable_paths"] == ["structure"]


def test_build_user_message_payload_keeps_context_nodes() -> None:
    metadata = {
        "context_nodes": [
            {"pk": 8, "label": "Si", "formula": "Si2", "node_type": "StructureData"},
            {"pk": "12", "label": "", "node_type": "WorkChainNode"},
            {"pk": "bad", "label": "Skip me"},
        ]
    }

    payload = chat_service._build_user_message_payload(metadata, [8, 12, 8])

    assert payload == {
        "context_pks": [8, 12],
        "context_nodes": [
            {"pk": 8, "label": "Si", "formula": "Si2", "node_type": "StructureData"},
            {"pk": 12, "label": "#12", "formula": None, "node_type": "WorkChainNode"},
        ],
    }


def test_build_user_message_payload_keeps_session_preferences() -> None:
    metadata = {
        "context_nodes": [
            {"pk": 8, "label": "Si", "formula": "Si2", "node_type": "StructureData"},
        ],
        "pinned_nodes": [
            {"pk": 21, "label": "Pinned Si", "formula": "Si2", "node_type": "StructureData"},
        ],
        "session_environment": "quantumespresso",
        "prompt_override": "Keep four decimal places.",
        "session_parameters": [
            {"key": "ecutwfc", "value": "40 Ry"},
            {"key": "kspacing", "value": "0.15 1/Ang"},
        ],
    }

    payload = chat_service._build_user_message_payload(metadata, [8, 21])

    assert payload is not None
    assert payload["session_environment"] == "quantumespresso"
    assert payload["prompt_override"] == "Keep four decimal places."
    assert payload["pinned_nodes"][0]["pk"] == 21
    assert payload["session_parameters"][0]["key"] == "ecutwfc"


def test_build_user_message_payload_prefers_session_prompt_override() -> None:
    metadata = {
        "session_environment": "quantumespresso",
        "prompt_override": f"Keep four decimal places.\n\n{_AUTO_ENVIRONMENT_PROMPT}",
        "session_prompt_override": "Keep four decimal places.",
    }

    payload = chat_service._build_user_message_payload(metadata, [])

    assert payload is not None
    assert payload["prompt_override"] == "Keep four decimal places."


def test_inject_session_preference_instruction_adds_session_defaults() -> None:
    intent = "Run a relaxation."
    metadata = {
        "session_environment": "quantumespresso",
        "prompt_override": "Keep four decimal places.",
        "pinned_nodes": [{"pk": 22, "label": "Si", "node_type": "StructureData"}],
        "session_parameters": [{"key": "ecutwfc", "value": "40 Ry"}],
    }

    scoped = chat_service._inject_session_preference_instruction(intent, metadata)

    assert "SESSION PREFERENCES" in scoped
    assert "active_environment: quantumespresso" in scoped
    assert "pinned_nodes: [#22]" in scoped
    assert "session_parameters: ecutwfc=40 Ry" in scoped
    assert "prompt_override: Keep four decimal places." in scoped
    assert intent in scoped


def test_normalize_chat_session_snapshot_strips_auto_environment_prompt() -> None:
    normalized = chat_service._normalize_chat_session_snapshot(
        {
            "prompt_override": f"Keep four decimal places.\n\n{_AUTO_ENVIRONMENT_PROMPT}",
            "selected_model": "gemini-flash-latest",
        }
    )

    assert normalized["prompt_override"] == "Keep four decimal places."


def test_build_chat_session_snapshot_prefers_session_prompt_override() -> None:
    snapshot = chat_service._build_chat_session_snapshot(
        {
            "prompt_override": f"Keep four decimal places.\n\n{_AUTO_ENVIRONMENT_PROMPT}",
            "session_prompt_override": "Keep four decimal places.",
        },
        selected_model="gemini-flash-latest",
    )

    assert snapshot["prompt_override"] == "Keep four decimal places."


def test_normalize_submission_draft_payload_derives_primary_and_advanced() -> None:
    draft = {
        "builder": {
            "structure_pk": 22,
            "metadata": {
                "options": {
                    "resources": {
                        "num_machines": 1,
                        "num_mpiprocs_per_machine": 4,
                    }
                }
            },
            "parameters": {
                "SYSTEM": {
                    "ecutwfc": 80,
                }
            },
        }
    }

    normalized = chat_service._normalize_submission_draft_payload(
        {},
        draft=draft,
        validation=None,
        validation_summary=None,
    )

    assert normalized["primary_inputs"]["structure"]["pk"] == 22
    assert normalized["advanced_settings"]["num_mpiprocs_per_machine"] == 4
    assert normalized["advanced_settings"]["ecutwfc"] == 80
    assert "num_machines" not in normalized["advanced_settings"]
    assert isinstance(normalized["all_inputs"], dict)
    assert isinstance(normalized["input_groups"], list)
    assert normalized["meta"]["input_groups"] == normalized["input_groups"]


def test_extract_submission_inputs_ignores_request_wrapper_only_payload() -> None:
    draft = {
        "workchain": "quantumespresso.pw.relax",
        "structure_pk": 264,
        "code": "pw-7.5@localhost",
        "protocol": "moderate",
        "overrides": {},
    }

    extracted = chat_service._extract_submission_inputs(draft)

    assert extracted == {}


def test_extract_submission_inputs_prefers_nested_inputs_namespace() -> None:
    draft = {
        "builder": {
            "inputs": {
                "base": {
                    "pw": {
                        "code": "pw-7.5@localhost",
                    }
                },
                "structure": 264,
            },
            "code": "pw-7.5@localhost",
            "protocol": "moderate",
        }
    }

    extracted = chat_service._extract_submission_inputs(draft)

    assert "base" in extracted
    assert "code" not in extracted


def test_normalize_submission_draft_payload_builds_port_grouping_with_ui_types() -> None:
    normalized = chat_service._normalize_submission_draft_payload(
        {
            "process_label": "PwRelaxWorkChain",
            "inputs": {
                "base": {
                    "pw": {
                        "parameters": {
                            "SYSTEM": {"ecutwfc": 55},
                        }
                    }
                },
                "kpoints": {"mesh": [4, 4, 1]},
                "metadata": {
                    "options": {
                        "resources": {"num_machines": 2},
                        "max_wallclock_seconds": 3600,
                    }
                },
                "protocol": "moderate",
                "pseudo_family": "PseudoDojo/0.5/PBE/SR/standard/upf",
            },
            "advanced_settings": {"protocol": "moderate"},
        },
        draft=None,
        validation=None,
        validation_summary=None,
    )

    groups = normalized["input_groups"]
    assert isinstance(groups, list)
    group_titles = {entry.get("title") for entry in groups}
    assert "Computational Details" in group_titles
    assert "Brillouin Zone" in group_titles
    assert "System Environment" in group_titles
    assert "Physics Protocol" in group_titles

    mesh_entry = normalized["all_inputs"]["kpoints.mesh"]
    assert mesh_entry["ui_type"] == "mesh"


def test_normalize_submission_draft_payload_ignores_node_metadata_envelopes_in_advanced_settings() -> None:
    normalized = chat_service._normalize_submission_draft_payload(
        {
            "process_label": "ExampleWorkChain",
            "inputs": {
                "Nbands_Factor": {
                    "pk": None,
                    "uuid": "draft-node-1",
                    "type": "Float",
                },
                "clean_workdir": {
                    "pk": None,
                    "uuid": "draft-node-2",
                    "type": "Bool",
                    "value": True,
                },
            },
        },
        draft=None,
        validation=None,
        validation_summary=None,
    )

    assert "nbands_factor" not in normalized["advanced_settings"]
    assert normalized["advanced_settings"]["clean_workdir"] is True


def test_normalize_submission_draft_payload_preserves_existing_all_inputs_without_inputs() -> None:
    normalized = chat_service._normalize_submission_draft_payload(
        {
            "process_label": "quantumespresso.pw.base",
            "primary_inputs": {
                "code": "q-e-qe-7.5-pw@manneback_async",
                "structure": "Si2 (PK: 6)",
            },
            "recommended_inputs": {
                "protocol": "moderate",
            },
            "all_inputs": {
                "kpoints": {
                    "value": [4, 4, 4],
                    "is_recommended": True,
                },
                "metadata.options.resources": {
                    "num_machines": 1,
                    "num_mpiprocs_per_machine": 1,
                },
            },
        },
        draft=None,
        validation=None,
        validation_summary=None,
    )

    assert normalized["inputs"] == {}
    assert normalized["all_inputs"]["kpoints"]["value"] == [4, 4, 4]
    assert normalized["all_inputs"]["metadata.options.resources"]["num_machines"] == 1
    assert normalized["meta"]["all_inputs"]["kpoints"]["value"] == [4, 4, 4]


def test_update_assistant_message_keeps_existing_text_when_status_payload_arrives() -> None:
    state = _make_chat_state()
    session = chat_service.create_chat_session(state, activate=True)
    history = chat_service.get_chat_history(state, session["id"])
    history.append(
        {
            "role": "assistant",
            "turn_id": 9,
            "text": "Partial result is already visible.",
            "status": "thinking",
        }
    )

    chat_service._update_assistant_message(
        state,
        9,
        "Running: custom script...",
        status="thinking",
        session_id=session["id"],
        payload={
            "type": "status",
            "tool_calls": ["POST management.run-python"],
            "status": {
                "current_step": "Running custom script",
                "steps": ["Running custom script"],
            },
        },
    )

    message = history[0]
    assert message["text"] == "Partial result is already visible."
    assert message["status"] == "thinking"
    assert message["payload"]["type"] == "status"
    assert message["payload"]["status"]["current_step"] == "Running custom script"


def test_is_retryable_model_unavailable_error_detects_high_demand_503() -> None:
    error = RuntimeError(
        "Request failed: status_code: 503, model_name: gemini-flash-latest, "
        "body: {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. "
        "Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
    )
    runtime = PydanticAIGeminiRuntime(SimpleNamespace())
    assert runtime.is_retryable_unavailable_error(error) is True


def test_is_retryable_model_unavailable_error_ignores_non_retryable_errors() -> None:
    model_rejected = RuntimeError("Request failed: status_code: 404, model is not found for api version")
    runtime = PydanticAIGeminiRuntime(SimpleNamespace())
    assert runtime.is_retryable_unavailable_error(model_rejected) is False


def test_create_chat_session_archives_previous_active_session() -> None:
    state = _make_chat_state()

    original = chat_service.create_chat_session(state, title="Original", activate=True)
    fresh = chat_service.create_chat_session(
        state,
        title="Fresh",
        activate=True,
        archive_session_id=original["id"],
    )

    sessions = {session["id"]: session for session in chat_service.list_chat_sessions(state)}

    assert chat_service.get_active_chat_session_id(state) == fresh["id"]
    assert sessions[original["id"]]["is_archived"] is True
    assert sessions[fresh["id"]]["is_archived"] is False


def test_activate_chat_session_unarchives_history_session() -> None:
    state = _make_chat_state()

    archived = chat_service.create_chat_session(state, title="Archived candidate", activate=True)
    current = chat_service.create_chat_session(
        state,
        title="Current",
        activate=True,
        archive_session_id=archived["id"],
    )

    restored = chat_service.activate_chat_session(state, archived["id"])

    assert current["id"] != archived["id"]
    assert restored is not None
    assert restored["id"] == archived["id"]
    assert restored["is_archived"] is False
    assert chat_service.get_active_chat_session_id(state) == archived["id"]


def test_normalize_chat_session_store_skips_archived_active_session() -> None:
    normalized = chat_service._normalize_chat_session_store(
        {
            "active_session_id": "archived-session",
            "sessions": [
                {"id": "archived-session", "title": "Archived", "is_archived": True},
                {"id": "active-session", "title": "Active", "is_archived": False},
            ],
        }
    )

    assert normalized["active_session_id"] == "active-session"


def test_create_chat_session_creates_default_project_workspace(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        session = chat_service.create_chat_session(state, title="Workspace session", activate=True)
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert session["project_id"]
    assert session["project_label"] == "Default Project"
    workspace_path = Path(session["workspace_path"])
    assert workspace_path.exists()
    assert workspace_path == Path(chat_service.get_chat_session_project_root_path(state, session["id"]))
    assert (workspace_path / "codes").is_dir()
    assert (workspace_path / "data").is_dir()
    assert (workspace_path / "sessions").exists() is False


def test_create_chat_project_assigns_new_sessions_to_requested_project(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        project = chat_service.create_chat_project(
            state,
            name="Born Charge Study",
            root_path=str(tmp_path / "born-study"),
            activate=True,
        )
        session = chat_service.create_chat_session(
            state,
            title="Analyze Born charges",
            activate=True,
            project_id=project["id"],
        )
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert session["project_id"] == project["id"]
    assert session["project_label"] == "Born Charge Study"
    assert Path(session["workspace_path"]) == Path(project["root_path"])
    assert (Path(project["root_path"]) / "codes").is_dir()
    assert (Path(project["root_path"]) / "data").is_dir()


def test_write_chat_project_file_persists_content_under_project_root(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        project = chat_service.create_chat_project(state, name="EOS", activate=True)
        payload = chat_service.write_chat_project_file(
            state,
            project["id"],
            relative_path="codes/submit_si_eos_20260314.py",
            content="print('si eos')\n",
            overwrite=True,
        )
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert payload is not None
    assert payload["relative_path"] == "codes/submit_si_eos_20260314.py"
    assert payload["filename"] == "submit_si_eos_20260314.py"
    assert (Path(project["root_path"]) / "codes" / "submit_si_eos_20260314.py").read_text(encoding="utf-8") == (
        "print('si eos')\n"
    )


def test_get_chat_session_project_root_path_returns_project_root(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        project = chat_service.create_chat_project(state, name="Bands", activate=True)
        session = chat_service.create_chat_session(state, title="Bands", activate=True, project_id=project["id"])
        project_root = chat_service.get_chat_session_project_root_path(state, session["id"])
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert project_root == str(Path(project["root_path"]))


def test_delete_chat_items_removes_session_workspace_and_reassigns_active_session(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    original_memory_dir = chat_service.settings.ARIS_MEMORY_DIR
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    chat_service.settings.ARIS_MEMORY_DIR = str(tmp_path / "memories")
    try:
        older = chat_service.create_chat_session(state, title="Older", activate=True)
        newer = chat_service.create_chat_session(state, title="Newer", activate=True)
        older_workspace = Path(older["workspace_path"])
        newer_workspace = Path(newer["workspace_path"])
        newer_session_file = _session_file_path(newer["id"])

        deleted = chat_service.delete_chat_items(state, session_ids=[newer["id"]])
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root
        chat_service.settings.ARIS_MEMORY_DIR = original_memory_dir

    assert deleted["deleted_session_ids"] == [newer["id"]]
    assert deleted["deleted_project_ids"] == []
    assert older_workspace.exists() is True
    assert newer_workspace == older_workspace
    assert newer_session_file.exists() is False
    assert chat_service.get_active_chat_session_id(state) == older["id"]


def test_delete_chat_items_removes_project_and_child_sessions(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        doomed_project = chat_service.create_chat_project(state, name="To Delete", activate=True)
        doomed_session = chat_service.create_chat_session(state, title="Delete me", activate=True, project_id=doomed_project["id"])
        survivor_project = chat_service.create_chat_project(state, name="Keep", activate=True)
        survivor_session = chat_service.create_chat_session(state, title="Keep me", activate=True, project_id=survivor_project["id"])
        doomed_root = Path(doomed_project["root_path"])

        deleted = chat_service.delete_chat_items(state, project_ids=[doomed_project["id"]])
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    remaining_projects = {project["id"] for project in chat_service.list_chat_projects(state)}
    remaining_sessions = {session["id"] for session in chat_service.list_chat_sessions(state)}

    assert deleted["deleted_project_ids"] == [doomed_project["id"]]
    assert deleted["deleted_session_ids"] == [doomed_session["id"]]
    assert doomed_project["id"] not in remaining_projects
    assert doomed_session["id"] not in remaining_sessions
    assert survivor_project["id"] in remaining_projects
    assert survivor_session["id"] in remaining_sessions
    assert chat_service.get_active_chat_session_id(state) == survivor_session["id"]
    assert doomed_root.exists() is False


def test_list_chat_session_workspace_files_returns_saved_entries(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        session = chat_service.create_chat_session(state, title="Workspace browser", activate=True)
        workspace_path = Path(session["workspace_path"])
        (workspace_path / "plots").mkdir(parents=True, exist_ok=True)
        (workspace_path / "plots" / "band-structure.png").write_bytes(b"png")
        payload = chat_service.list_chat_session_workspace_files(state, session["id"], relative_path="plots")
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert payload is not None
    assert payload["relative_path"] == "plots"
    assert payload["entries"][0]["name"] == "band-structure.png"


def test_create_chat_session_uses_english_slug_for_group_and_workspace(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        session = chat_service.create_chat_session(state, title="Si Bands Study", activate=True)
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert session["title"] == "Si Bands Study"
    assert session["session_slug"] == "si-bands-study"
    assert session["session_group_label"] == "Default Project/si-bands-study"
    assert Path(session["workspace_path"]).name != "si-bands-study"


def test_create_chat_session_with_non_english_title_falls_back_to_default_english_name(tmp_path) -> None:
    state = _make_chat_state()
    original_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path)
    try:
        session = chat_service.create_chat_session(state, title="硅热膨胀", activate=True)
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_root

    assert session["title"] == "New Conversation"
    assert session["session_slug"] == "new-conversation"
    assert session["session_group_label"] == "Default Project/new-conversation"
    assert Path(session["workspace_path"]).exists()
