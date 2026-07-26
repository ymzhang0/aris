"""AiiDA group naming rules and bridge-backed gateway for chat sessions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from src.aris_apps.aiida.frontend_bridge import (
    inspect_group as bridge_inspect_group,
    list_groups as bridge_list_groups,
    rename_group as bridge_rename_group,
)

DEFAULT_PROJECT_GROUP_LABEL = "Default Project"


def normalize_group_label_segment(value: Any, *, fallback: str) -> str:
    text = " ".join(str(value or "").split()).replace("/", "_").strip()
    return text or fallback


def build_project_group_label(project_name: Any) -> str:
    return normalize_group_label_segment(
        project_name,
        fallback=DEFAULT_PROJECT_GROUP_LABEL,
    )


def build_session_group_label(project_name: Any, session_name: Any) -> str:
    project_group_label = build_project_group_label(project_name)
    session_segment = normalize_group_label_segment(
        session_name,
        fallback="session",
    )
    return f"{project_group_label}/{session_segment}"


class ChatGroupGateway(Protocol):
    def inspect_group(
        self,
        group_label: str,
        *,
        limit: int = 500,
    ) -> dict[str, Any] | None: ...

    def rename_group_label_if_available(
        self,
        old_group_label: str,
        new_group_label: str,
    ) -> bool: ...


class FrontendBridgeGroupGateway:
    """Adapt frontend-bridge group operations to the chat application boundary."""

    def __init__(
        self,
        *,
        list_groups_fn: Callable[..., Any] = bridge_list_groups,
        inspect_group_fn: Callable[..., Any] = bridge_inspect_group,
        rename_group_fn: Callable[..., Any] = bridge_rename_group,
    ) -> None:
        self._list_groups = list_groups_fn
        self._inspect_group = inspect_group_fn
        self._rename_group = rename_group_fn

    def inspect_group(
        self,
        group_label: str,
        *,
        limit: int = 500,
    ) -> dict[str, Any] | None:
        cleaned_label = str(group_label or "").strip()
        if not cleaned_label:
            return None
        payload = self._inspect_group(cleaned_label, limit=max(1, int(limit)))
        return payload if isinstance(payload, dict) else None

    def rename_group_label_if_available(
        self,
        old_group_label: str,
        new_group_label: str,
    ) -> bool:
        cleaned_old = str(old_group_label or "").strip()
        cleaned_new = str(new_group_label or "").strip()
        if not cleaned_old or not cleaned_new or cleaned_old == cleaned_new:
            return False

        try:
            raw_groups = self._list_groups()
            groups = raw_groups if isinstance(raw_groups, list) else []
            existing_by_label = {
                str(group.get("label") or "").strip(): group
                for group in groups
                if isinstance(group, dict) and str(group.get("label") or "").strip()
            }
            if cleaned_new in existing_by_label:
                return False
            existing_old = existing_by_label.get(cleaned_old)
            if not isinstance(existing_old, dict):
                return False
            group_pk = int(existing_old.get("pk") or 0)
            if group_pk <= 0:
                return False
            self._rename_group(group_pk, cleaned_new)
            return True
        except Exception:  # noqa: BLE001
            return False


__all__ = [
    "ChatGroupGateway",
    "DEFAULT_PROJECT_GROUP_LABEL",
    "FrontendBridgeGroupGateway",
    "build_project_group_label",
    "build_session_group_label",
    "normalize_group_label_segment",
]
