"""Tests for AiiDA frontend process serialization and process-detail enrichment."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.aris_apps.aiida import router as aiida_router
from src.aris_apps.aiida.presenters import node_view as aiida_node_view
from src.aris_apps.aiida.router import (
    _coerce_chat_metadata,
    _extract_folder_preview,
    _serialize_processes,
)
from src.aris_core.schema.approval import ApprovalDecision, submission_resource_digest


def _submission_request(
    draft: dict[str, object] | list[dict[str, object]],
) -> aiida_router.SubmissionDraftRequest:
    scope = "batch" if isinstance(draft, list) else "single"
    return aiida_router.SubmissionDraftRequest(
        draft=draft,
        approval=ApprovalDecision(
            approval_id="approval-test",
            decision="approved",
            scope=scope,
            actor_type="user",
            decided_at=datetime.now(timezone.utc),
            resource_digest=submission_resource_digest(draft),
        ),
    )


def test_serialize_processes_ignores_noncanonical_preview_field() -> None:
    preview = {
        "formula": "Si2",
        "atom_count": 2,
    }
    processes = [
        {
            "pk": 101,
            "label": "Silicon bulk",
            "state": "finished",
            "node_type": "StructureData",
            "formula": "Si2",
            "preview": preview,
        }
    ]

    serialized = _serialize_processes(processes)

    assert "preview" not in serialized[0]
    assert "preview_info" not in serialized[0]


def test_serialize_processes_does_not_add_preview_info_when_missing() -> None:
    processes = [
        {
            "pk": 202,
            "label": "Relaxation",
            "state": "running",
            "node_type": "ProcessNode",
        }
    ]

    serialized = _serialize_processes(processes)

    assert "preview_info" not in serialized[0]


def test_serialize_processes_passes_preview_info_without_modification() -> None:
    preview_info = {
        "array_names": ["kpoints", "energies"],
    }
    processes = [
        {
            "pk": 303,
            "label": "Bands postprocess",
            "state": "finished",
            "node_type": "XyData",
            "preview_info": preview_info,
        }
    ]

    serialized = _serialize_processes(processes)

    assert serialized[0]["preview_info"] is preview_info
    assert serialized[0]["preview_info"] == preview_info


def test_serialize_processes_passes_process_label() -> None:
    processes = [
        {
            "pk": 404,
            "label": "EPW run",
            "state": "running",
            "node_type": "ProcessNode",
            "process_label": "EpwCalculation",
        }
    ]

    serialized = _serialize_processes(processes)

    assert serialized[0]["process_label"] == "EpwCalculation"


def test_coerce_chat_metadata_drops_empty_keys() -> None:
    metadata = {
        " current_focus_pk ": 123,
        "": "skip",
        "   ": "skip",
    }

    coerced = _coerce_chat_metadata(metadata)

    assert coerced == {"current_focus_pk": 123}


def test_extract_folder_preview_ignores_generic_node_metadata() -> None:
    payload = {
        "pk": 55,
        "node_type": "FolderData",
        "label": "retrieved",
        "state": "stored",
    }

    preview = _extract_folder_preview(payload)

    assert preview is None


def test_extract_folder_preview_prefers_repository_file_listing() -> None:
    payload = {
        "pk": 55,
        "node_type": "FolderData",
        "repository": {
            "files": [
                {"name": "aiida.out"},
                {"name": "scheduler.stderr"},
                {"name": "_scheduler-stdout.txt"},
            ]
        },
    }

    preview = _extract_folder_preview(payload)

    assert preview == {"filenames": ["aiida.out", "scheduler.stderr", "_scheduler-stdout.txt"]}


def test_attach_tree_links_sets_inputs_and_outputs_on_each_tree_node() -> None:
    tree = {
        "pk": 11,
        "children": {
            "child": {
                "pk": 22,
                "children": {},
            }
        },
    }
    root_inputs = [{"link_label": "structure", "node_type": "StructureData", "pk": 5}]
    links_by_pk = {
        11: (root_inputs, [], None, None),
    }

    aiida_router._attach_tree_links(tree, links_by_pk)

    assert tree["inputs"] == {
        "structure": {"link_label": "structure", "node_type": "StructureData", "pk": 5}
    }
    assert tree["outputs"] == {}
    assert tree["children"]["child"]["inputs"] == {}
    assert tree["children"]["child"]["outputs"] == {}


def test_attach_tree_links_prefers_direct_links_for_tree_nodes() -> None:
    tree = {
        "pk": 11,
        "children": {},
    }
    verbose_inputs = [{"link_label": "structure", "node_type": "StructureData", "pk": 5}]
    direct_inputs = [{"link_label": "structure", "node_type": "StructureData", "pk": 7}]
    direct_outputs = [{"link_label": "remote_folder", "node_type": "RemoteData", "pk": 9}]
    links_by_pk = {
        11: (verbose_inputs, [], direct_inputs, direct_outputs),
    }

    aiida_router._attach_tree_links(tree, links_by_pk)

    assert tree["inputs"] == {
        "structure": {"link_label": "structure", "node_type": "StructureData", "pk": 7}
    }
    assert tree["direct_inputs"] == tree["inputs"]
    assert tree["outputs"] == {
        "remote_folder": {"link_label": "remote_folder", "node_type": "RemoteData", "pk": 9}
    }
    assert tree["direct_outputs"] == tree["outputs"]


def test_extract_preview_for_node_type_prefers_embedded_preview_info() -> None:
    payload = {
        "preview_info": {
            "formula": "Si2",
            "atom_count": 2,
        },
        "path": "/remote/workdir",
    }

    preview = aiida_node_view._extract_preview_for_node_type("StructureData", payload)

    assert preview == {
        "formula": "Si2",
        "atom_count": 2,
    }


@pytest.mark.anyio
async def test_frontend_export_group_returns_archive_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aiida_router.hub, "_current_profile", "codex-test-profile")
    monkeypatch.setattr(
        aiida_router,
        "export_group_archive",
        lambda pk: SimpleNamespace(  # noqa: ARG005
            content=b"fake-aiida-archive",
            headers={"content-disposition": 'attachment; filename="Si_batch.aiida"'},
            media_type="application/octet-stream",
        ),
    )

    response = await aiida_router.frontend_export_group(42)

    assert response.body == b"fake-aiida-archive"
    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="Si_batch.aiida"'


@pytest.mark.anyio
async def test_frontend_chat_project_workspace_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "project_id": "proj-1",
        "project_name": "Si Research",
        "workspace_path": "/tmp/si-research",
        "relative_path": "results",
        "entries": [
            {
                "name": "bands",
                "path": "/tmp/si-research/results/bands",
                "relative_path": "results/bands",
                "is_dir": True,
                "size": None,
                "updated_at": "2026-03-08T00:00:00+00:00",
            }
        ],
    }
    monkeypatch.setattr(
        aiida_router,
        "list_chat_project_workspace_files",
        lambda state, project_id, relative_path=None: payload,  # noqa: ARG005
    )

    request = SimpleNamespace(app=SimpleNamespace(state=object()))
    response = await aiida_router.frontend_chat_project_workspace(
        request,
        "proj-1",
        relative_path="results",
    )

    assert response == payload


@pytest.mark.anyio
async def test_enrich_process_detail_payload_always_exposes_link_arrays() -> None:
    payload = {"summary": {"pk": None}}

    enriched = await aiida_router._enrich_process_detail_payload(payload)

    assert enriched["inputs"] == {}
    assert enriched["outputs"] == {}


@pytest.mark.anyio
async def test_frontend_processes_defaults_to_root_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get_frontend_nodes(**kwargs: object) -> list[dict[str, object]]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(aiida_router, "_get_frontend_nodes", _fake_get_frontend_nodes)

    response = await aiida_router.frontend_processes(
        limit=15,
        group_label=None,
        node_type=None,
        root_only=True,
    )

    assert response == {"items": []}
    assert captured == {
        "limit": 15,
        "group_label": None,
        "node_type": None,
        "root_only": True,
    }


def test_clear_pending_submission_memory_sets_none() -> None:
    captured: dict[str, object] = {}

    class _DummyMemory:
        def set_kv(self, key: str, value: object) -> None:
            captured[key] = value

    state = type("State", (), {"memory": _DummyMemory()})()

    aiida_router._clear_pending_submission_memory(state)

    assert captured[aiida_router.PENDING_SUBMISSION_KEY] is None


@pytest.mark.anyio
async def test_frontend_active_specializations_normalizes_query_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_build_active_specializations_payload(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "chips": [],
            "slash_menu": [],
            "active_specializations": [],
            "inactive_specializations": [],
            "environment": {"selected": None, "resolved": "general", "auto_switch": True},
            "context": {
                "context_node_ids": [11, 22],
                "context_node_types": [],
                "project_tags": ["qe", "quantumespresso"],
                "resource_plugins": ["quantumespresso.pw"],
                "worker_plugins": [],
                "worker_plugins_available": True,
            },
        }

    monkeypatch.setattr(aiida_router, "build_active_specializations_payload", _fake_build_active_specializations_payload)

    response = await aiida_router.frontend_active_specializations(
        context_node_ids=[11, 22],
        project_tags=[" qe, quantumespresso ", "QE"],
        resource_plugins=[" quantumespresso.pw , quantumespresso.pw "],
        selected_environment=None,
        auto_switch=True,
    )

    assert captured == {
        "context_node_ids": [11, 22],
        "project_tags": ["qe", "quantumespresso"],
        "resource_plugins": ["quantumespresso.pw"],
        "selected_environment": None,
        "auto_switch": True,
    }
    assert response["environment"]["resolved"] == "general"


@pytest.mark.anyio
async def test_submit_bridge_workchain_single_adds_submitted_pk(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_auto_assign_submission_groups(*_args: object, **_kwargs: object) -> None:
        return None

    async def _fake_request_json(
        method: str,
        path: str,
        json: dict[str, object],
        headers: dict[str, str] | None = None,
    ):  # noqa: ARG001
        assert method == "POST"
        assert path == "/submission/submit"
        assert "draft" in json
        assert headers == {"X-ARIS-Session-Id": "chat-0307"}
        return {"status": "SUBMITTED", "pk": 321}

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)
    monkeypatch.setattr(
        aiida_router,
        "_build_submission_request_headers",
        lambda _state: {"X-ARIS-Session-Id": "chat-0307"},
    )
    monkeypatch.setattr(aiida_router, "_auto_assign_submission_groups", _fake_auto_assign_submission_groups)

    captured: dict[str, object] = {}

    class _DummyMemory:
        def set_kv(self, key: str, value: object) -> None:
            captured[key] = value

    state = SimpleNamespace(memory=_DummyMemory())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    payload = _submission_request({"builder": {"structure_pk": 11}})

    response = await aiida_router.submit_bridge_workchain(request, payload)

    assert response["submitted_pks"] == [321]
    assert response["process_pks"] == [321]
    assert captured[aiida_router.PENDING_SUBMISSION_KEY] is None


@pytest.mark.anyio
async def test_submit_bridge_workchain_unwraps_direct_entry_point_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_request: dict[str, object] = {}

    async def _fake_auto_assign_submission_groups(*_args: object, **_kwargs: object) -> None:
        return None

    async def _fake_request_json(
        method: str,
        path: str,
        json: dict[str, object],
        headers: dict[str, str] | None = None,
    ):  # noqa: ARG001
        assert method == "POST"
        assert path == "/submission/submit"
        captured_request["payload"] = json
        assert headers == {"X-ARIS-Session-Id": "chat-0307"}
        return {"status": "SUBMITTED", "pk": 654}

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)
    monkeypatch.setattr(
        aiida_router,
        "_build_submission_request_headers",
        lambda _state: {"X-ARIS-Session-Id": "chat-0307"},
    )
    monkeypatch.setattr(aiida_router, "_auto_assign_submission_groups", _fake_auto_assign_submission_groups)

    captured: dict[str, object] = {}

    class _DummyMemory:
        def set_kv(self, key: str, value: object) -> None:
            captured[key] = value

    state = SimpleNamespace(memory=_DummyMemory())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    payload = _submission_request(
        {
            "entry_point": "quantumespresso.pw.base",
            "inputs": {
                "pw": {"code": "pw@localhost"},
                "structure": {"pk": 6},
            },
        },
    )

    response = await aiida_router.submit_bridge_workchain(request, payload)

    captured_payload = captured_request["payload"]
    assert isinstance(captured_payload, dict)
    assert captured_payload["entry_point"] == "quantumespresso.pw.base"
    assert captured_payload["inputs"] == {
        "pw": {"code": "pw@localhost"},
        "structure": {"pk": 6},
    }
    assert captured_payload["metadata"]["aris_approval"]["approval_id"] == "approval-test"
    assert response["submitted_pks"] == [654]
    assert response["process_pks"] == [654]
    assert captured[aiida_router.PENDING_SUBMISSION_KEY] is None


@pytest.mark.anyio
async def test_frontend_create_chat_project_ensures_project_group(monkeypatch: pytest.MonkeyPatch) -> None:
    state = SimpleNamespace()
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    ensured: list[str] = []

    monkeypatch.setattr(
        aiida_router,
        "create_chat_project",
        lambda *_args, **_kwargs: {"id": "project-1", "group_label": "Test_multitask_Si_Thermal_Expansion"},
    )
    monkeypatch.setattr(aiida_router, "get_active_chat_project_id", lambda _state: "project-1")
    monkeypatch.setattr(aiida_router, "list_chat_projects", lambda _state: [{"id": "project-1"}])

    async def _fake_ensure_named_groups(labels: list[str]) -> dict[str, str]:
        ensured.extend(labels)
        return {label: label for label in labels}

    monkeypatch.setattr(aiida_router, "_ensure_named_groups", _fake_ensure_named_groups)

    response = await aiida_router.frontend_create_chat_project(
        request,
        aiida_router.FrontendChatProjectCreateRequest(name="Test_multitask_Si_Thermal_Expansion"),
    )

    assert response["project"]["id"] == "project-1"
    assert ensured == ["Test_multitask_Si_Thermal_Expansion"]


@pytest.mark.anyio
async def test_frontend_write_chat_project_file_proxies_service_result(monkeypatch: pytest.MonkeyPatch) -> None:
    state = SimpleNamespace()
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    monkeypatch.setattr(
        aiida_router,
        "write_chat_project_file",
        lambda *_args, **_kwargs: {
            "project_id": "project-1",
            "project_name": "Silicon EOS",
            "workspace_path": "/tmp/projects/project-1",
            "path": "/tmp/projects/project-1/codes/submit_si_eos_20260314.py",
            "relative_path": "codes/submit_si_eos_20260314.py",
            "directory_path": "codes",
            "filename": "submit_si_eos_20260314.py",
            "size": 18,
            "updated_at": "2026-03-14T12:00:00+00:00",
            "created": True,
        },
    )

    response = await aiida_router.frontend_write_chat_project_file(
        request,
        "project-1",
        aiida_router.FrontendChatProjectFileWriteRequest(
            relative_path="codes/submit_si_eos_20260314.py",
            content="print('si eos')\n",
            overwrite=True,
        ),
    )

    assert response.project_id == "project-1"
    assert response.relative_path == "codes/submit_si_eos_20260314.py"


@pytest.mark.anyio
async def test_frontend_create_chat_session_ensures_project_and_session_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(chat_sessions_version=1)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    ensured: list[str] = []

    monkeypatch.setattr(
        aiida_router,
        "create_chat_session",
        lambda *_args, **_kwargs: {
            "id": "chat-0307",
            "project_group_label": "Test_multitask_Si_Thermal_Expansion",
            "session_group_label": "Test_multitask_Si_Thermal_Expansion/chat-0307",
        },
    )
    monkeypatch.setattr(aiida_router, "get_chat_snapshot", lambda _state: {"messages": []})
    monkeypatch.setattr(aiida_router, "get_active_chat_session_id", lambda _state: "chat-0307")
    monkeypatch.setattr(aiida_router, "get_active_chat_project_id", lambda _state: "project-1")
    monkeypatch.setattr(aiida_router, "list_chat_projects", lambda _state: [{"id": "project-1"}])

    async def _fake_ensure_named_groups(labels: list[str]) -> dict[str, str]:
        ensured.extend(labels)
        return {label: label for label in labels}

    monkeypatch.setattr(aiida_router, "_ensure_named_groups", _fake_ensure_named_groups)

    response = await aiida_router.frontend_create_chat_session(
        request,
        aiida_router.FrontendChatSessionCreateRequest(title="Session"),
    )

    assert response["session"]["id"] == "chat-0307"
    assert ensured == [
        "Test_multitask_Si_Thermal_Expansion",
        "Test_multitask_Si_Thermal_Expansion/chat-0307",
    ]


@pytest.mark.anyio
async def test_frontend_delete_chat_project_deletes_project_and_session_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(chat_sessions_version=3)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    deleted_group_pks: list[int] = []

    monkeypatch.setattr(
        aiida_router,
        "list_chat_projects",
        lambda _state: [{"id": "project-1", "group_label": "Project One"}],
    )
    monkeypatch.setattr(
        aiida_router,
        "list_chat_sessions",
        lambda _state: [{"id": "session-1", "project_id": "project-1", "session_group_label": "Project One/session-1"}],
    )
    monkeypatch.setattr(
        aiida_router,
        "delete_chat_items",
        lambda *_args, **_kwargs: {"deleted_project_ids": ["project-1"], "deleted_session_ids": ["session-1"]},
    )
    monkeypatch.setattr(aiida_router, "get_chat_snapshot", lambda _state: {"session_id": None, "messages": [], "snapshot": {}})
    monkeypatch.setattr(aiida_router, "_chat_sessions_payload", lambda _state: {"version": 4, "active_session_id": None, "active_project_id": None, "projects": [], "items": []})
    monkeypatch.setattr(
        aiida_router,
        "list_groups",
        lambda: [
            {"pk": 11, "label": "Project One"},
            {"pk": 12, "label": "Project One/session-1"},
        ],
    )
    monkeypatch.setattr(aiida_router, "delete_group", lambda pk: deleted_group_pks.append(pk))

    response = await aiida_router.frontend_delete_chat_project(request, "project-1")

    assert response["deleted_project_ids"] == ["project-1"]
    assert response["deleted_session_ids"] == ["session-1"]
    assert deleted_group_pks == [11, 12]


@pytest.mark.anyio
async def test_frontend_delete_chat_items_supports_mixed_bulk_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(chat_sessions_version=3)
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    monkeypatch.setattr(aiida_router, "list_chat_projects", lambda _state: [])
    monkeypatch.setattr(
        aiida_router,
        "list_chat_sessions",
        lambda _state: [{"id": "session-2", "project_id": "project-2", "session_group_label": "Project Two/session-2"}],
    )
    monkeypatch.setattr(
        aiida_router,
        "delete_chat_items",
        lambda *_args, **_kwargs: {"deleted_project_ids": ["project-2"], "deleted_session_ids": ["session-2"]},
    )
    monkeypatch.setattr(aiida_router, "get_chat_snapshot", lambda _state: {"session_id": None, "messages": [], "snapshot": {}})
    monkeypatch.setattr(aiida_router, "_chat_sessions_payload", lambda _state: {"version": 5, "active_session_id": None, "active_project_id": None, "projects": [], "items": []})

    async def _fake_delete_named_groups(_labels: list[str]) -> dict[str, str]:
        return {}

    monkeypatch.setattr(aiida_router, "_delete_named_groups", _fake_delete_named_groups)

    response = await aiida_router.frontend_delete_chat_items(
        request,
        aiida_router.FrontendChatDeleteRequest(project_ids=["project-2"], session_ids=["session-2"]),
    )

    assert response["deleted_project_ids"] == ["project-2"]
    assert response["deleted_session_ids"] == ["session-2"]


@pytest.mark.anyio
async def test_submit_bridge_workchain_batch_collects_submitted_pks(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted = [901, 902, 903]
    captured_request: dict[str, object] = {}

    async def _fake_auto_assign_submission_groups(*_args: object, **_kwargs: object) -> None:
        return None

    async def _fake_request_json(
        method: str,
        path: str,
        json: dict[str, object],
        headers: dict[str, str] | None = None,
    ):  # noqa: ARG001
        assert method == "POST"
        assert path == "/submission/submit"
        captured_request["payload"] = json
        assert headers == {"X-ARIS-Session-Id": "chat-0307"}
        return {
            "status": "SUBMITTED_BATCH",
            "total": 3,
            "submitted_count": 3,
            "failed_count": 0,
            "submitted_pks": submitted,
            "process_pks": submitted,
            "responses": [
                {"index": index, "response": {"status": "SUBMITTED", "pk": pk}}
                for index, pk in enumerate(submitted)
            ],
            "failures": [],
        }

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)
    monkeypatch.setattr(
        aiida_router,
        "_build_submission_request_headers",
        lambda _state: {"X-ARIS-Session-Id": "chat-0307"},
    )
    monkeypatch.setattr(aiida_router, "_auto_assign_submission_groups", _fake_auto_assign_submission_groups)

    captured: dict[str, object] = {}

    class _DummyMemory:
        def set_kv(self, key: str, value: object) -> None:
            captured[key] = value

    state = SimpleNamespace(memory=_DummyMemory())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    payload = _submission_request(
        [
            {"builder": {"structure_pk": 11}},
            {"builder": {"structure_pk": 22}},
            {"builder": {"structure_pk": 33}},
        ],
    )

    response = await aiida_router.submit_bridge_workchain(request, payload)

    captured_payload = captured_request["payload"]
    assert isinstance(captured_payload, dict)
    assert captured_payload["draft"] == [
        {"builder": {"structure_pk": 11}},
        {"builder": {"structure_pk": 22}},
        {"builder": {"structure_pk": 33}},
    ]
    assert captured_payload["metadata"]["aris_approval"]["approval_id"] == "approval-test"
    assert response["status"] == "SUBMITTED_BATCH"
    assert response["submitted_pks"] == submitted
    assert response["process_pks"] == submitted
    assert response["failures"] == []
    assert len(response["responses"]) == 3
    assert captured[aiida_router.PENDING_SUBMISSION_KEY] is None


@pytest.mark.anyio
async def test_submit_bridge_workchain_batch_alias_requires_list() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    payload = _submission_request({"builder": {"structure_pk": 11}})

    with pytest.raises(aiida_router.HTTPException) as exc_info:
        await aiida_router.submit_bridge_workchain_batch(request, payload)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Batch submission draft list is required"


def test_build_active_submission_group_labels_uses_session_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aiida_router, "get_active_chat_session_id", lambda _state: "chat-0307")
    monkeypatch.setattr(
        aiida_router,
        "get_chat_session_detail",
        lambda _state, _session_id: {
            "project_group_label": "Si_Research",
            "session_group_label": "Si_Research/chat-0307",
        },
    )

    labels = aiida_router._build_active_submission_group_labels(SimpleNamespace())

    assert labels == {
        "project": "Si_Research",
        "session": "Si_Research/chat-0307",
    }


@pytest.mark.anyio
async def test_auto_assign_submission_groups_creates_missing_groups_and_adds_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_labels: list[str] = []
    assigned_calls: list[tuple[int, list[int]]] = []
    groups = [
        {
            "pk": 10,
            "label": "Si_Research",
            "count": 3,
        }
    ]

    monkeypatch.setattr(
        aiida_router,
        "_build_active_submission_group_labels",
        lambda _state: {
            "project": "Si_Research",
            "session": "Si_Research/chat-0307",
        },
    )
    monkeypatch.setattr(aiida_router, "list_groups", lambda: list(groups))

    def _fake_create_group(label: str) -> dict[str, object]:
        created_labels.append(label)
        item = {
            "pk": 11,
            "label": label,
            "count": 0,
        }
        groups.append(item)
        return {"item": item}

    monkeypatch.setattr(aiida_router, "create_group", _fake_create_group)
    monkeypatch.setattr(
        aiida_router,
        "add_nodes_to_group",
        lambda pk, node_pks: assigned_calls.append((pk, node_pks)) or {"group": {"pk": pk}, "added": node_pks},
    )

    labels = await aiida_router._auto_assign_submission_groups(SimpleNamespace(), [903, 901, 901])

    assert labels == {
        "project": "Si_Research",
        "session": "Si_Research/chat-0307",
    }
    assert created_labels == ["Si_Research/chat-0307"]
    assert assigned_calls == [
        (10, [901, 903]),
        (11, [901, 903]),
    ]


@pytest.mark.anyio
async def test_frontend_node_hover_metadata_resolves_formula_spacegroup_and_node_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        aiida_router,
        "get_context_nodes",
        lambda _ids: [
            {
                "pk": 11,
                "node_type": "StructureData",
                "formula": "Si2",
                "attributes": {
                    "spacegroup": {
                        "symbol": "Fm-3m",
                        "number": 225,
                    }
                },
            }
        ],
    )
    monkeypatch.setattr(aiida_router.hub, "start", lambda: None)
    monkeypatch.setattr(aiida_router.hub, "_current_profile", "test-profile")

    response = await aiida_router.frontend_node_hover_metadata(11)

    assert response.pk == 11
    assert response.formula == "Si2"
    assert response.spacegroup == "Fm-3m (225)"
    assert response.node_type == "StructureData"


@pytest.mark.anyio
async def test_frontend_node_hover_metadata_returns_safe_fallback_when_node_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aiida_router, "get_context_nodes", lambda _ids: [])
    monkeypatch.setattr(aiida_router.hub, "start", lambda: None)
    monkeypatch.setattr(aiida_router.hub, "_current_profile", "test-profile")

    response = await aiida_router.frontend_node_hover_metadata(9999)

    assert response.pk == 9999
    assert response.formula is None
    assert response.spacegroup is None
    assert response.node_type == "Unknown"


@pytest.mark.anyio
async def test_frontend_node_script_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "pk": 88,
        "node_type": "StructureData",
        "language": "python",
        "script": "from ase import Atoms\natoms = Atoms(...)",
    }

    async def _fake_request_json(method: str, path: str, **_: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/management/nodes/88/script"
        return expected

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.frontend_node_script(88)

    assert response.model_dump() == expected


@pytest.mark.anyio
async def test_worker_repository_files_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/data/repository/314/files"
        assert kwargs.get("params") == {"source": "folder"}
        return {"pk": 314, "files": ["aiida.out", "_scheduler-stderr.txt"], "source": "folder"}

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.worker_repository_files(314, source="folder")

    assert response["pk"] == 314
    assert response["files"] == ["aiida.out", "_scheduler-stderr.txt"]


@pytest.mark.anyio
async def test_worker_remote_files_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **_kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/data/remote/280/files"
        return {"pk": 280, "files": ["aiida.out"]}

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.worker_remote_files(280)

    assert response == {"pk": 280, "files": ["aiida.out"]}


@pytest.mark.anyio
async def test_worker_bands_data_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "pk": 335,
        "data": {
            "paths": [{"x": [0.0, 1.0], "values": [[-1.0, 0.5]]}],
            "tick_pos": [0.0, 1.0],
            "tick_labels": ["G", "X"],
        },
    }

    async def _fake_request_json(method: str, path: str, **_kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/data/bands/335"
        return expected

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.worker_bands_data(335)

    assert response == expected


@pytest.mark.anyio
async def test_export_management_computer_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "kind": "computer",
        "label": "localhost",
        "filename": "localhost-setup.yaml",
        "format": "yaml",
        "content": "label: localhost\nhostname: localhost\n",
    }

    async def _fake_request_json(method: str, path: str, **_: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/management/infrastructure/computer/pk/7/export"
        return expected

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.export_management_computer(7)

    assert response.model_dump() == expected


@pytest.mark.anyio
async def test_get_management_infrastructure_capabilities_proxies_worker_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "aiida_core_version": "2.7.3",
        "available_transports": ["core.local", "core.ssh", "core.ssh_async"],
        "recommended_transport": "core.ssh_async",
        "supports_async_ssh": True,
        "transport_auth_fields": {
            "core.local": ["use_login_shell", "safe_interval"],
            "core.ssh": [
                "username",
                "port",
                "look_for_keys",
                "key_filename",
                "timeout",
                "allow_agent",
                "proxy_jump",
                "proxy_command",
                "compress",
                "gss_auth",
                "gss_kex",
                "gss_deleg_creds",
                "gss_host",
                "load_system_host_keys",
                "key_policy",
                "use_login_shell",
                "safe_interval",
            ],
            "core.ssh_async": ["host", "max_io_allowed", "authentication_script", "backend", "use_login_shell", "safe_interval"],
        },
    }

    async def _fake_capabilities() -> dict[str, object]:
        return expected

    monkeypatch.setattr(aiida_router.aiida_worker_client, "get_infrastructure_capabilities", _fake_capabilities)

    response = await aiida_router.get_management_infrastructure_capabilities()

    assert response.model_dump() == expected


@pytest.mark.anyio
async def test_test_management_infrastructure_connection_proxies_worker_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "status": "success",
        "connection_status": "success",
        "connection_error": None,
    }

    async def _fake_request_json(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "POST"
        assert path == "/management/infrastructure/test-connection"
        assert kwargs.get("json") == {"computer_label": "manneback_async"}
        return expected

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.test_management_infrastructure_connection({"computer_label": "manneback_async"})

    assert response == expected


@pytest.mark.anyio
async def test_export_management_code_proxies_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "kind": "code",
        "label": "pw-7.5",
        "filename": "pw-7.5@localhost.yaml",
        "format": "yaml",
        "content": "label: pw-7.5\ncomputer: localhost\n",
    }

    async def _fake_request_json(method: str, path: str, **_: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/management/infrastructure/code/42/export"
        return expected

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    response = await aiida_router.export_management_code(42)

    assert response.model_dump() == expected


@pytest.mark.anyio
async def test_frontend_clone_process_draft_enriches_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_payload = {
        "process_label": "PwBaseWorkChain",
        "entry_point": "aiida.workflows:quantumespresso.pw.base",
        "inputs": {"structure": 11, "pw": {"code": "pw@localhost"}},
        "meta": {
            "draft": {
                "entry_point": "aiida.workflows:quantumespresso.pw.base",
                "inputs": {"structure": 11, "pw": {"code": "pw@localhost"}},
            }
        },
    }
    enriched_payload = {
        "process_label": "PwBaseWorkChain",
        "inputs": {"structure": 11, "pw": {"code": "pw@localhost"}},
        "meta": {"draft": worker_payload["meta"]["draft"], "port_spec": {"entry_point": "aiida.workflows:quantumespresso.pw.base"}},
    }

    async def _fake_request_json(method: str, path: str, **_: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/process/321/clone-draft"
        return worker_payload

    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)
    monkeypatch.setattr(aiida_router, "enrich_submission_draft_payload", lambda payload: enriched_payload if payload == worker_payload else payload)

    response = await aiida_router.frontend_clone_process_draft("321")

    assert response["submission_draft"] == enriched_payload
    assert response["approval_request"]["action"] == "submission.execute"
    assert response["approval_request"]["scope"] == "single"
    assert response["approval_request"]["resource_digest"] == (
        submission_resource_digest(worker_payload["meta"]["draft"])
    )


@pytest.mark.anyio
async def test_frontend_chat_session_batch_progress_returns_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        aiida_router,
        "get_chat_session_detail",
        lambda _state, session_id: {"id": session_id, "title": "Si 批量能带"},
    )
    monkeypatch.setattr(
        aiida_router,
        "get_chat_session_batch_progress",
        lambda _state, _session_id: {
            "label": "Si 批量能带",
            "total": 7,
            "done": 5,
            "percent": 71,
            "success": 5,
            "running": 1,
            "queued": 1,
            "failed": 0,
            "items": [],
        },
    )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    response = await aiida_router.frontend_chat_session_batch_progress(request, "session-1")

    assert response["item"]["total"] == 7
    assert response["item"]["running"] == 1


@pytest.mark.anyio
async def test_frontend_chat_session_batch_progress_returns_404_for_missing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aiida_router, "get_chat_session_detail", lambda _state, _session_id: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(aiida_router.HTTPException) as exc_info:
        await aiida_router.frontend_chat_session_batch_progress(request, "missing-session")

    assert exc_info.value.status_code == 404


def test_estimate_runtime_from_history_prefers_matching_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        aiida_router,
        "_get_frontend_nodes",
        lambda **_: [
            {
                "pk": 1,
                "process_label": "PwBandsWorkChain",
                "node_type": "WorkChainNode",
                "process_state": "finished",
                "preview_info": {
                    "computer_label": "aris",
                    "atom_count": 88,
                    "execution_time_seconds": 2700,
                    "num_machines": 4,
                },
            },
            {
                "pk": 2,
                "process_label": "PwBandsWorkChain",
                "node_type": "WorkChainNode",
                "process_state": "finished",
                "preview_info": {
                    "computer_label": "aris",
                    "atom_count": 92,
                    "execution_time_seconds": 3000,
                    "num_machines": 4,
                },
            },
            {
                "pk": 3,
                "process_label": "PwRelaxWorkChain",
                "node_type": "WorkChainNode",
                "process_state": "finished",
                "preview_info": {
                    "computer_label": "other-cluster",
                    "atom_count": 12,
                    "execution_time_seconds": 300,
                    "num_machines": 1,
                },
            },
        ],
    )

    estimate = aiida_router._estimate_runtime_from_history(
        {
            "pk": 99,
            "process_label": "PwBandsWorkChain",
            "node_type": "WorkChainNode",
            "computer_label": "aris",
            "atom_count": 90,
            "num_machines": 4,
        },
        computer_label="aris",
        reference_process_pk=99,
    )

    assert estimate.available is True
    assert estimate.sample_size == 2
    assert estimate.num_machines == 4
    assert estimate.display == "~48 mins on 4 nodes"


def test_build_scheduler_probe_script_uses_configured_user_lookup() -> None:
    script = aiida_router._build_scheduler_probe_script("aris")

    assert 'project=["label"]' in script
    assert 'project=["label", "is_enabled"]' not in script
    assert "load_profile()" in script
    assert "User.collection.get_default()" in script
    assert 'if selected is None and not payload["computer_label"]:' in script
    assert '("hold", "suspend")' in script
    assert '("pend", "wait", "queue")' in script


@pytest.mark.anyio
async def test_run_worker_json_script_uses_default_environment_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_inspect_default_environment(*, force_refresh: bool = False) -> dict[str, object]:
        assert force_refresh is False
        return {
            "success": True,
            "python_interpreter_path": "/tmp/worker-python",
        }

    async def _fake_request_json(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "POST"
        assert path == "/management/run-python"
        assert kwargs.get("json") == {
            "script_content": "print('hello')",
            "python_interpreter_path": "/tmp/worker-python",
        }
        return {"output": f"noise\n{aiida_router.WORKER_JSON_MARKER}{{\"available\": true}}\n"}

    monkeypatch.setattr(aiida_router.aiida_worker_client, "inspect_default_environment", _fake_inspect_default_environment)
    monkeypatch.setattr(aiida_router, "request_json", _fake_request_json)

    payload = await aiida_router._run_worker_json_script("print('hello')")

    assert payload == {"available": True}


@pytest.mark.anyio
async def test_frontend_compute_health_returns_queue_warning_and_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch_process_detail_payload(identifier: str | int) -> dict[str, object]:
        assert identifier == 321
        return {
            "summary": {
                "pk": 321,
                "process_label": "PwBandsWorkChain",
                "node_type": "WorkChainNode",
            },
            "preview_info": {"computer_label": "aris", "atom_count": 88, "num_machines": 4},
        }

    async def _fake_resolve_compute_health_computer_label(**_: object) -> str:
        return "aris"

    async def _fake_fetch_scheduler_snapshot(computer_label: str | None) -> dict[str, object]:
        assert computer_label == "aris"
        return {
            "available": True,
            "computer_label": "aris",
            "scheduler_type": "core.slurm",
            "queue": {"running": 12, "pending": 45, "queued": 1204, "total": 1261},
        }

    monkeypatch.setattr(aiida_router, "_fetch_process_detail_payload", _fake_fetch_process_detail_payload)
    monkeypatch.setattr(
        aiida_router,
        "_resolve_compute_health_computer_label",
        _fake_resolve_compute_health_computer_label,
    )
    monkeypatch.setattr(aiida_router, "_fetch_scheduler_snapshot", _fake_fetch_scheduler_snapshot)
    monkeypatch.setattr(
        aiida_router,
        "_estimate_runtime_from_history",
        lambda *_args, **_kwargs: aiida_router.ComputeHealthEstimateResponse(
            available=True,
            duration_seconds=2700,
            display="~45 mins on 4 nodes",
            num_machines=4,
            sample_size=7,
            basis="Historical runs matched by computer, workflow, and task scale",
            matched_process_label="PwBandsWorkChain",
        ),
    )

    response = await aiida_router.frontend_compute_health(reference_process_pk=321)

    assert response.available is True
    assert response.computer_label == "aris"
    assert response.scheduler_type == "core.slurm"
    assert response.queue.queued == 1204
    assert response.queue.congested is True
    assert response.warning_message is not None
    assert "1204" in response.warning_message
    assert response.estimate.display == "~45 mins on 4 nodes"


@pytest.mark.anyio
async def test_build_process_diagnostics_prefers_repository_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch_process_detail_payload(identifier: str | int) -> dict[str, object]:
        assert identifier == 77
        return {
            "summary": {
                "pk": 77,
                "node_type": "CalcJobNode",
                "process_label": "PwCalculation",
                "state": "failed",
                "exit_status": 301,
                "exit_message": "SCF did not converge",
                "label": "pw.x",
            },
            "preview_info": {"computer_label": "aris"},
            "direct_outputs": {
                "retrieved": {"link_label": "retrieved", "node_type": "FolderData", "pk": 900},
                "remote_folder": {"link_label": "remote_folder", "node_type": "RemoteData", "pk": 901},
            },
        }

    async def _fake_request_optional_json(method: str, path: str, **_: object) -> dict[str, object] | None:
        assert method == "GET"
        if path == "/process/77/logs":
            return {
                "lines": ["report line 1", "report line 2"],
                "stderr_excerpt": "scheduler stderr tail",
                "text": "report line 1\nreport line 2",
            }
        if path == "/data/repository/900/files":
            return {"files": ["aiida.out", "scheduler.stderr"]}
        if path == "/data/repository/900/files/aiida.out":
            return {"content": "line 1\nline 2\nline 3"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(aiida_router, "_fetch_process_detail_payload", _fake_fetch_process_detail_payload)
    monkeypatch.setattr(aiida_router, "_request_optional_json", _fake_request_optional_json)

    response = await aiida_router._build_process_diagnostics(77)

    assert response.available is True
    assert response.process_pk == 77
    assert response.process_label == "PwCalculation"
    assert response.exit_status == 301
    assert response.exit_message == "SCF did not converge"
    assert response.computer_label == "aris"
    assert response.is_calcjob is True
    assert response.stdout_excerpt.source == "repository"
    assert response.stdout_excerpt.filename == "aiida.out"
    assert response.stdout_excerpt.line_count == 3
    assert response.stdout_excerpt.text == "line 1\nline 2\nline 3"
    assert response.stderr_excerpt == "scheduler stderr tail"
