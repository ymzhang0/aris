"""AG-UI event encoding for the application state stream."""

from __future__ import annotations

from ag_ui.core import BaseEvent, StateSnapshotEvent


def build_ag_ui_sse_event(
    event: BaseEvent,
    *,
    event_id: str | None = None,
) -> dict[str, str]:
    """Encode an official AG-UI event as a data-only SSE message."""

    encoded = {
        "data": event.model_dump_json(by_alias=True, exclude_none=True),
    }
    if event_id:
        encoded["id"] = event_id
    return encoded


def build_ag_ui_state_snapshot(
    *,
    chat: dict[str, Any],
    sessions: dict[str, Any],
) -> StateSnapshotEvent:
    """Publish the complete ARIS UI state as one atomic AG-UI snapshot."""

    return StateSnapshotEvent(
        snapshot={
            "aris": {
                "chat": chat,
                "sessions": sessions,
            }
        }
    )


__all__ = [
    "build_ag_ui_sse_event",
    "build_ag_ui_state_snapshot",
]
