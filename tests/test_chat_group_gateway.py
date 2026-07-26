from __future__ import annotations

from types import SimpleNamespace

from src.aris_apps.aiida.chat import service as chat_service
from src.aris_apps.aiida.chat.group_gateway import (
    FrontendBridgeGroupGateway,
    build_project_group_label,
    build_session_group_label,
    normalize_group_label_segment,
)


def test_group_label_rules_normalize_hierarchy_segments() -> None:
    assert normalize_group_label_segment("  Si / Bands  ", fallback="fallback") == "Si _ Bands"
    assert build_project_group_label("") == "Default Project"
    assert build_session_group_label(" Project / A ", " session / 1 ") == (
        "Project _ A/session _ 1"
    )


def test_gateway_renames_existing_group_without_overwriting_target() -> None:
    rename_calls: list[tuple[int, str]] = []
    list_calls = 0

    def _list_groups():
        nonlocal list_calls
        list_calls += 1
        return [{"pk": 17, "label": "Project/old"}]

    gateway = FrontendBridgeGroupGateway(
        list_groups_fn=_list_groups,
        rename_group_fn=lambda pk, label: rename_calls.append((pk, label)),
    )

    renamed = gateway.rename_group_label_if_available(
        "Project/old",
        "Project/new",
    )

    assert renamed is True
    assert list_calls == 1
    assert rename_calls == [(17, "Project/new")]


def test_gateway_does_not_overwrite_existing_group_or_raise_bridge_errors() -> None:
    rename_calls: list[tuple[int, str]] = []
    gateway = FrontendBridgeGroupGateway(
        list_groups_fn=lambda: [
            {"pk": 17, "label": "Project/old"},
            {"pk": 18, "label": "Project/new"},
        ],
        rename_group_fn=lambda pk, label: rename_calls.append((pk, label)),
    )

    assert gateway.rename_group_label_if_available("Project/old", "Project/new") is False
    assert rename_calls == []

    failing_gateway = FrontendBridgeGroupGateway(
        list_groups_fn=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert failing_gateway.rename_group_label_if_available("Project/old", "Project/new") is False


def test_gateway_inspection_normalizes_label_limit_and_payload() -> None:
    captured: dict[str, object] = {}

    def _inspect(group_label: str, *, limit: int):
        captured["label"] = group_label
        captured["limit"] = limit
        return {"nodes": [{"pk": 1}]}

    gateway = FrontendBridgeGroupGateway(inspect_group_fn=_inspect)

    assert gateway.inspect_group(" Project/session ", limit=0) == {
        "nodes": [{"pk": 1}]
    }
    assert captured == {"label": "Project/session", "limit": 1}
    assert gateway.inspect_group(" ") is None


def test_chat_service_uses_injected_gateway_for_session_group_rename() -> None:
    rename_calls: list[tuple[str, str]] = []
    gateway = SimpleNamespace(
        inspect_group=lambda _label, limit=500: None,
        rename_group_label_if_available=lambda old, new: (
            rename_calls.append((old, new)) or True
        ),
    )
    state = SimpleNamespace(chat_group_gateway=gateway)
    session = {
        "id": "session-1",
        "project_id": "project-1",
        "session_slug": "new-title",
    }
    store = {
        "active_project_id": "project-1",
        "projects": [{"id": "project-1", "name": "Research / Project"}],
        "sessions": [session],
    }

    chat_service._rename_session_group_label_if_needed(
        state,
        store,
        session,
        "old-title",
    )

    assert rename_calls == [
        ("Research _ Project/old-title", "Research _ Project/new-title")
    ]


def test_chat_service_preserves_group_label_compatibility_aliases() -> None:
    assert chat_service._build_project_group_label is build_project_group_label
    assert chat_service._build_session_group_label is build_session_group_label
