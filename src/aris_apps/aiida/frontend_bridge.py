from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.aris_apps.aiida.client import (
    WorkerBinaryResponse,
    WorkerRPCError,
    WorkerOfflineError,
    aiida_worker_client,
    request_content_sync,
    worker_call_sync,
)








def _normalize_group_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    label = str(raw.get("label") or "").strip()
    if not label:
        return None

    try:
        pk = int(raw.get("pk", 0))
    except (TypeError, ValueError):
        pk = 0

    try:
        count = int(raw.get("count", 0))
    except (TypeError, ValueError):
        count = 0

    payload: dict[str, Any] = {
        "pk": pk,
        "label": label,
        "count": max(0, count),
    }

    type_string = raw.get("type_string")
    if isinstance(type_string, str) and type_string.strip():
        payload["type_string"] = type_string.strip()

    return payload


def list_groups(search: str | None = None) -> list[dict[str, Any]]:
    params = {"search": search} if search else None
    try:
        payload = worker_call_sync("group.list", params, timeout=6.0)
    except (WorkerOfflineError, WorkerRPCError):
        return []
    except Exception:  # noqa: BLE001
        return []

    items: list[Any]
    if isinstance(payload, dict):
        raw_items = payload.get("items")
        items = raw_items if isinstance(raw_items, list) else []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    groups: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in items:
        normalized = _normalize_group_item(item)
        if not normalized:
            continue
        pk = int(normalized["pk"])
        if pk in seen:
            continue
        seen.add(pk)
        groups.append(normalized)

    return groups


def get_recent_nodes(
    limit: int = 15,
    group_label: str | None = None,
    node_type: str | None = None,
    *,
    root_only: bool = True,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": int(limit), "root_only": bool(root_only)}
    if group_label:
        params["group_label"] = group_label
    if node_type:
        params["node_type"] = node_type

    try:
        payload = worker_call_sync("node.recent", params, timeout=8.0)
    except (WorkerOfflineError, WorkerRPCError):
        return []
    except Exception:  # noqa: BLE001
        return []

    if isinstance(payload, dict):
        items = payload.get("items")
        return items if isinstance(items, list) else []
    return payload if isinstance(payload, list) else []


def get_context_nodes(node_ids: list[int]) -> list[dict[str, Any]]:
    ids = [int(pk) for pk in node_ids if isinstance(pk, int) or str(pk).isdigit()]
    if not ids:
        return []

    try:
        payload = worker_call_sync("node.context", {"ids": ids[:30]}, timeout=8.0)
    except (WorkerOfflineError, WorkerRPCError):
        return []
    except Exception:  # noqa: BLE001
        return []

    if isinstance(payload, dict):
        items = payload.get("items")
        return items if isinstance(items, list) else []
    return payload if isinstance(payload, list) else []


def inspect_group(group_label: str, *, limit: int = 500) -> dict[str, Any] | None:
    cleaned_label = str(group_label or "").strip()
    if not cleaned_label:
        return None

    try:
        payload = worker_call_sync(
            "GET",
            f"/management/groups/{quote(cleaned_label, safe='')}",
            params={"limit": max(1, int(limit))},
            timeout=8.0,
        )
    except (WorkerOfflineError, WorkerRPCError):
        return None
    except Exception:  # noqa: BLE001
        return None

    return payload if isinstance(payload, dict) else None


def create_group(label: str) -> dict[str, Any]:
    return worker_call_sync("group.create", {"label": str(label)}, timeout=8.0)


def delete_group(pk: int) -> dict[str, Any]:
    return worker_call_sync("group.delete", {"pk": int(pk)}, timeout=8.0)


def rename_group(pk: int, label: str) -> dict[str, Any]:
    return worker_call_sync("group.rename", {"pk": int(pk), "label": str(label)}, timeout=8.0)


def add_nodes_to_group(pk: int, node_pks: list[int]) -> dict[str, Any]:
    ids = [int(raw_pk) for raw_pk in node_pks if isinstance(raw_pk, int) or str(raw_pk).isdigit()]
    return worker_call_sync(
        "POST",
        f"/management/groups/{int(pk)}/nodes",
        json={"node_pks": ids[:200]},
        timeout=10.0,
    )


def export_group_archive(pk: int) -> WorkerBinaryResponse:
    return request_content_sync("GET", f"/management/groups/{int(pk)}/export", timeout=120.0)


def soft_delete_node(pk: int, *, deleted: bool = True) -> dict[str, Any]:
    return worker_call_sync(
        "POST",
        f"/management/nodes/{int(pk)}/soft-delete",
        json={"deleted": bool(deleted)},
        timeout=8.0,
    )
