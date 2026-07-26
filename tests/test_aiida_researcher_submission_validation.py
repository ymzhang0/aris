"""Tests for pre-submission validation flow in the AiiDA researcher agent."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src.aris_apps.aiida.deps import AiiDADeps

os.environ.setdefault("GOOGLE_API_KEY", "dummy")

from src.aris_apps.aiida.agent import researcher  # noqa: E402


def _ctx(
    *,
    session_id: str | None = None,
    app_state: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        deps=AiiDADeps(
            session_id=session_id,
            app_state=app_state,
        )
    )


def test_extract_submission_inputs_ignores_request_wrapper_only_payload() -> None:
    draft = {
        "workchain": "quantumespresso.pw.relax",
        "structure_pk": 264,
        "code": "pw-7.5@localhost",
        "protocol": "moderate",
        "overrides": {},
    }

    extracted = researcher._extract_submission_inputs(draft)

    assert extracted == {}


def test_extract_submission_inputs_prefers_nested_inputs_namespace() -> None:
    draft = {
        "builder": {
            "inputs": {
                "base": {"pw": {"code": "pw-7.5@localhost"}},
                "structure": 264,
            },
            "code": "pw-7.5@localhost",
            "protocol": "moderate",
        }
    }

    extracted = researcher._extract_submission_inputs(draft)

    assert "base" in extracted
    assert "code" not in extracted


def test_build_batch_input_aggregation_collapses_empty_structure_metadata_fields() -> None:
    aggregation = researcher._build_batch_input_aggregation(
        [
            {
                "inputs": {
                    "structure": {
                        "label": "",
                        "pk": "",
                        "uuid": "",
                        "node_type": "StructureData",
                    },
                    "scf": {"kpoints_distance": 0.5},
                }
            },
            {
                "inputs": {
                    "structure": {
                        "label": "",
                        "pk": "",
                        "uuid": "",
                        "node_type": "StructureData",
                    },
                    "scf": {"kpoints_distance": 0.5},
                }
            },
        ],
        raw_drafts=[
            {"structure_pk": 11},
            {"structure_pk": 22},
        ],
        structure_metadata=[
            {"pk": 11, "formula": "Si"},
            {"pk": 22, "formula": "Si"},
        ],
    )

    assert aggregation is not None
    assert aggregation["common"] == {"scf": {"kpoints_distance": 0.5}}
    assert aggregation["variable_paths"] == ["structure"]
    assert aggregation["variation_count"] == 1
    assert aggregation["items"][0]["diff"] == {"structure": "Si (PK 11)"}
    assert aggregation["items"][1]["diff"] == {"structure": "Si (PK 22)"}


@pytest.mark.anyio
async def test_submit_new_workflow_validates_before_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_draft(workchain: str, structure_pk: int, code: str, protocol: str):
        calls.append("draft")
        assert workchain == "quantumespresso.pw.base"
        assert structure_pk == 11
        assert code == "pw@localhost"
        assert protocol == "moderate"
        return {"status": "DRAFT_READY", "builder": {"workchain": workchain}}

    async def _fake_validate(draft_data: dict):
        calls.append("validate")
        assert draft_data.get("status") == "DRAFT_READY"
        return {"status": "VALIDATION_OK", "warnings": ["resource estimate is high"], "errors": []}

    async def _fake_submit(draft_data: dict):  # noqa: ARG001
        calls.append("submit")
        return {"status": "SUBMITTED"}

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)
    monkeypatch.setattr(researcher, "submit_job", _fake_submit)

    result = await researcher.submit_new_workflow(
        _ctx(),
        workchain="quantumespresso.pw.base",
        structure_pk=11,
        code="pw@localhost",
    )

    assert result["status"] == "SUBMISSION_DRAFT"
    assert result["validation_summary"]["is_valid"] is True
    assert result["submission_draft"]["process_label"] == "quantumespresso.pw.base"
    assert isinstance(result["submission_draft"]["primary_inputs"], dict)
    assert isinstance(result["submission_draft"]["advanced_settings"], dict)
    assert isinstance(result["submission_draft"]["meta"]["pk_map"], list)
    assert "submission_draft_tag" not in result
    assert "summary_text" in result["validation_summary"]
    assert calls == ["draft", "validate"]


@pytest.mark.anyio
async def test_submit_new_workflow_applies_explicit_bands_kpoints_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_draft(
        workchain: str,
        structure_pk: int,
        code: str,
        protocol: str,
        overrides: dict | None = None,
        protocol_kwargs: dict | None = None,
    ):
        captured["workchain"] = workchain
        captured["structure_pk"] = structure_pk
        captured["code"] = code
        captured["protocol"] = protocol
        captured["overrides"] = overrides
        captured["protocol_kwargs"] = protocol_kwargs
        return {
            "status": "DRAFT_READY",
            "builder": {"workchain": workchain},
            "builder_inputs": {
                "scf": {"kpoints_distance": overrides["scf"]["kpoints_distance"]},
                "bands_kpoints_distance": overrides["bands_kpoints_distance"],
            },
        }

    async def _fake_validate(_draft_data: dict):
        return {"status": "VALIDATION_OK", "warnings": [], "errors": []}

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)

    result = await researcher.submit_new_workflow(
        _ctx(),
        workchain="quantumespresso.pw.bands",
        structure_pk=11,
        code="pw@localhost",
        protocol_kwargs={"kpoints_distance": 0.5},
    )

    assert result["status"] == "SUBMISSION_DRAFT"
    assert captured["overrides"] == {
        "scf": {"kpoints_distance": 0.5},
        "bands_kpoints_distance": 0.5,
    }
    assert captured["protocol_kwargs"] is None


@pytest.mark.anyio
async def test_submit_new_workflow_returns_blocked_recovery_plan_for_invalid_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_draft(
        workchain: str,
        structure_pk: int,
        code: str,
        protocol: str,
    ):
        assert workchain == "quantumespresso.pw.base"
        assert structure_pk == 19
        assert code == "pw@localhost"
        assert protocol == "moderate"
        return {
            "status": "DRAFT_INVALID",
            "errors": [
                {
                    "stage": "resolve_protocol_argument",
                    "port": "structure",
                    "message": "Could not load node for 'structure' with pk=19",
                }
            ],
            "missing_ports": ["structure"],
            "recovery_plan": {
                "status": "blocked",
                "summary": "Missing required inputs: structure",
                "missing_ports": ["structure"],
                "issues": [
                    {
                        "type": "resource_reference_unresolved",
                        "message": "Could not load node for 'structure' with pk=19",
                        "resource_domain": "structure",
                    }
                ],
                "recommended_actions": [
                    {
                        "action": "inspect_spec",
                        "reason": "Review the WorkChain spec first.",
                    },
                    {
                        "action": "ask_user",
                        "reason": "Confirm the user's preferred fix before changing inputs.",
                    },
                ],
                "user_decision_required": True,
            },
        }

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)

    result = await researcher.submit_new_workflow(
        _ctx(),
        workchain="quantumespresso.pw.base",
        structure_pk=19,
        code="pw@localhost",
    )

    assert result["error"] == "Failed to draft workflow"
    assert result["recovery_plan"]["summary"] == "Missing required inputs: structure"
    assert result["recovery_plan"]["issues"][0]["resource_domain"] == "structure"
    assert "inspect_spec" in result["next_step"]


@pytest.mark.anyio
async def test_submit_validated_workflow_blocks_invalid_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_draft(workchain: str, structure_pk: int, code: str, protocol: str):  # noqa: ARG001
        return {"status": "DRAFT_READY", "builder": {"workchain": workchain}}

    async def _fake_validate(draft_data: dict):  # noqa: ARG001
        return {"status": "VALIDATION_FAILED", "errors": ["Missing required pseudo family"]}

    async def _fake_submit(draft_data: dict):  # noqa: ARG001
        raise AssertionError("submit_job should not be called for invalid validation")

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)
    monkeypatch.setattr(researcher, "submit_job", _fake_submit)

    ctx = _ctx()
    drafted = await researcher.submit_new_workflow(
        ctx,
        workchain="quantumespresso.pw.base",
        structure_pk=11,
        code="pw@localhost",
    )
    result = await researcher.submit_validated_workflow(ctx)

    assert drafted["status"] == "SUBMISSION_BLOCKED"
    assert drafted["validation_summary"]["is_valid"] is False
    assert isinstance(drafted["recovery_plan"], dict)
    assert "error" in result
    assert "No validated workflow" in result["error"]


@pytest.mark.anyio
async def test_submit_validated_workflow_submits_and_clears_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_draft(workchain: str, structure_pk: int, code: str, protocol: str):  # noqa: ARG001
        return {"status": "DRAFT_READY", "builder": {"workchain": workchain}}

    async def _fake_validate(draft_data: dict):  # noqa: ARG001
        return {"status": "VALIDATION_OK", "warnings": []}

    async def _fake_submit(draft_data: dict):
        assert draft_data.get("status") == "DRAFT_READY"
        return {"status": "SUBMITTED", "job_id": 987}

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)
    monkeypatch.setattr(researcher, "submit_job", _fake_submit)

    ctx = _ctx()
    await researcher.submit_new_workflow(
        ctx,
        workchain="quantumespresso.pw.base",
        structure_pk=11,
        code="pw@localhost",
    )

    submitted = await researcher.submit_validated_workflow(ctx)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission"]["job_id"] == 987

    second_attempt = await researcher.submit_validated_workflow(ctx)
    assert "error" in second_attempt
    assert "No validated workflow" in second_attempt["error"]


@pytest.mark.anyio
async def test_submit_validated_workflow_auto_assigns_current_session_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_draft(workchain: str, structure_pk: int, code: str, protocol: str):  # noqa: ARG001
        return {"status": "DRAFT_READY", "builder": {"workchain": workchain}}

    async def _fake_validate(draft_data: dict):  # noqa: ARG001
        return {"status": "VALIDATION_OK", "warnings": []}

    async def _fake_submit(draft_data: dict):
        assert draft_data.get("status") == "DRAFT_READY"
        return {"status": "SUBMITTED", "submitted_pks": [321]}

    created_labels: list[str] = []
    assigned: list[tuple[int, list[int]]] = []

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)
    monkeypatch.setattr(researcher, "submit_job", _fake_submit)
    monkeypatch.setattr(
        researcher,
        "get_chat_session_detail",
        lambda _state, _session_id: {
            "project_group_label": "Si_Research",
            "session_group_label": "Si_Research/Chat_0307",
        },
    )
    monkeypatch.setattr(researcher, "bridge_list_groups", lambda: [])
    monkeypatch.setattr(
        researcher,
        "bridge_create_group",
        lambda label: (
            created_labels.append(label),
            {"item": {"pk": 11 if label == "Si_Research" else 12, "label": label}},
        )[1],
    )
    monkeypatch.setattr(
        researcher,
        "bridge_add_nodes_to_group",
        lambda group_pk, node_pks: assigned.append((group_pk, list(node_pks))) or {"group": {"pk": group_pk}},
    )

    ctx = _ctx(session_id="Chat_0307", app_state=object())
    await researcher.submit_new_workflow(
        ctx,
        workchain="quantumespresso.pw.base",
        structure_pk=11,
        code="pw@localhost",
    )

    submitted = await researcher.submit_validated_workflow(ctx)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["auto_groups"] == {
        "project": "Si_Research",
        "session": "Si_Research/Chat_0307",
    }
    assert created_labels == ["Si_Research", "Si_Research/Chat_0307"]
    assert assigned == [(11, [321]), (12, [321])]


@pytest.mark.anyio
async def test_submit_new_batch_workflow_builds_pending_batch_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_draft(
        workchain: str,
        structure_pk: int,
        code: str,
        protocol: str,
        overrides: dict | None = None,
        protocol_kwargs: dict | None = None,
    ):
        return {
            "status": "DRAFT_READY",
            "entry_point": workchain,
            "protocol": protocol,
            "code": code,
            "structure_pk": structure_pk,
            "overrides": overrides or {},
            "builder_inputs": {
                "structure": structure_pk,
                "scf": {
                    "kpoints_distance": ((overrides or {}).get("scf") or {}).get("kpoints_distance"),
                },
                "bands_kpoints_distance": (overrides or {}).get("bands_kpoints_distance"),
            },
        }

    async def _fake_validate(draft_data: dict):
        assert draft_data.get("status") == "DRAFT_READY"
        return {"status": "VALIDATION_OK", "warnings": []}

    captured_submit: dict[str, object] = {}

    async def _fake_submit(draft_data: dict | list[dict]):
        captured_submit["draft"] = draft_data
        return {"status": "SUBMITTED_BATCH", "submitted_pks": [401, 402]}

    monkeypatch.setattr(researcher, "draft_workchain_builder", _fake_draft)
    monkeypatch.setattr(researcher, "validate_job", _fake_validate)
    monkeypatch.setattr(researcher, "submit_job", _fake_submit)

    ctx = _ctx()
    drafted = await researcher.submit_new_batch_workflow(
        ctx,
        workchain="quantumespresso.pw.bands",
        structure_pks=[11, 22],
        code="pw@localhost",
        protocol="moderate",
        protocol_kwargs={"kpoints_distance": 0.5},
    )

    assert drafted["status"] == "SUBMISSION_DRAFT"
    assert drafted["job_count"] == 2
    assert drafted["validation_summary"]["is_valid"] is True
    assert len(drafted["submission_draft"]["meta"]["draft"]) == 2
    assert drafted["submission_draft"]["meta"]["validation_summary"]["job_count"] == 2
    assert drafted["submission_draft"]["inputs"] == {
        "scf": {"kpoints_distance": 0.5},
        "bands_kpoints_distance": 0.5,
    }
    batch_aggregation = drafted["submission_draft"]["meta"]["batch_aggregation"]
    assert batch_aggregation["common"] == {
        "scf": {"kpoints_distance": 0.5},
        "bands_kpoints_distance": 0.5,
    }
    assert batch_aggregation["variable_paths"] == ["structure"]
    assert batch_aggregation["items"][0]["label"] == "Structure #11"
    assert batch_aggregation["items"][0]["diff"] == {"structure": "Structure #11"}
    assert batch_aggregation["items"][1]["diff"] == {"structure": "Structure #22"}

    submitted = await researcher.submit_validated_workflow(ctx)

    assert submitted["status"] == "SUBMITTED"
    submitted_draft = captured_submit["draft"]
    assert isinstance(submitted_draft, list)
    assert len(submitted_draft) == 2
    assert all(item.get("workchain") == "quantumespresso.pw.bands" for item in submitted_draft)


@pytest.mark.anyio
async def test_run_aiida_code_script_adds_recovery_hint_on_missing_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_run_python_code(
        script: str,  # noqa: ARG001
        *,
        intent: str | None = None,  # noqa: ARG001
        nodes_involved: list[int] | None = None,  # noqa: ARG001
        turn_id: int | None = None,  # noqa: ARG001
    ):
        return {
            "error": "ModuleNotFoundError: No module named 'aiida_pseudo.data.family'",
            "missing_module": "aiida_pseudo.data.family",
            "output": "",
        }

    monkeypatch.setattr(researcher, "run_python_code", _fake_run_python_code)
    ctx = _ctx()
    result = await researcher.run_aiida_code_script(
        ctx,
        script="print('test')",
        intent="test",
        nodes_involved=[264],
    )

    assert isinstance(result, dict)
    assert result["missing_module"] == "aiida_pseudo.data.family"
    assert "submit_new_workflow" in result["recovery_suggestion"]


@pytest.mark.anyio
async def test_call_specialized_skill_forwards_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_execute_specialized_skill(skill_name: str, args: dict | None = None):
        assert skill_name == "relax_helper"
        assert args == {"structure_pk": 264}
        return {"success": True, "result": {"pk": 9001}}

    monkeypatch.setattr(researcher, "execute_specialized_skill", _fake_execute_specialized_skill)

    payload = await researcher.call_specialized_skill(
        _ctx(),
        skill_name="relax_helper",
        args={"structure_pk": 264},
    )

    assert payload["success"] is True
    assert payload["result"]["pk"] == 9001


@pytest.mark.anyio
async def test_persist_current_script_forwards_to_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_register_specialized_skill(
        skill_name: str,
        script: str,
        *,
        description: str | None = None,
        overwrite: bool = True,
    ):
        assert skill_name == "relax_helper"
        assert "def main" in script
        assert description == "Reusable helper"
        assert overwrite is False
        return {"status": "registered", "skill_name": skill_name}

    monkeypatch.setattr(researcher, "register_specialized_skill", _fake_register_specialized_skill)

    payload = await researcher.persist_current_script(
        _ctx(),
        name="relax_helper",
        script="def main(params):\n    return params\n",
        description="Reusable helper",
        overwrite=False,
    )

    assert payload["status"] == "registered"
    assert payload["skill_name"] == "relax_helper"


@pytest.mark.anyio
async def test_switch_aiida_profile_requires_prior_profile_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_switch_profile(profile_name: str):  # noqa: ARG001
        raise AssertionError("switch_profile should not be called without prior discovery")

    monkeypatch.setattr(researcher, "switch_profile", _fake_switch_profile)

    result = await researcher.switch_aiida_profile(_ctx(), "dev")

    assert result["target_profile"] == "dev"
    assert "Call list_profiles first" in result["error"]


@pytest.mark.anyio
async def test_switch_aiida_profile_allows_one_switch_per_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_list_system_profiles():
        return {
            "current_profile": "sandbox",
            "profiles": [
                {"name": "sandbox"},
                {"name": "dev"},
                {"name": "agent"},
            ],
        }

    async def _fake_switch_profile(profile_name: str):
        return {"status": "switched", "current_profile": profile_name}

    monkeypatch.setattr(researcher, "list_system_profiles", _fake_list_system_profiles)
    monkeypatch.setattr(researcher, "switch_profile", _fake_switch_profile)

    ctx = _ctx()
    profiles = await researcher.list_profiles(ctx)
    assert isinstance(profiles, list)

    first = await researcher.switch_aiida_profile(ctx, "dev")
    second = await researcher.switch_aiida_profile(ctx, "agent")

    assert first["status"] == "switched"
    assert first["current_profile"] == "dev"
    assert second["target_profile"] == "agent"
    assert "one switch per turn" in second["error"]
