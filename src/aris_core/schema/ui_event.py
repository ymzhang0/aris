"""Versioned application-to-UI event protocol."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from ag_ui.core import BaseEvent, StateSnapshotEvent
from pydantic import BaseModel, Field

UIEventType = Literal[
    "chat.snapshot",
    "sessions.snapshot",
    "processes.snapshot",
    "groups.snapshot",
    "infrastructure.snapshot",
    "logs.snapshot",
    "error",
    "heartbeat",
]

_LEGACY_EVENT_NAMES: dict[UIEventType, str] = {
    "chat.snapshot": "chat",
    "sessions.snapshot": "sessions",
    "processes.snapshot": "processes",
    "groups.snapshot": "groups",
    "infrastructure.snapshot": "infrastructure",
    "logs.snapshot": "logs",
    "error": "error",
    "heartbeat": "heartbeat",
}


class UIEventEnvelope(BaseModel):
    """Typed internal event with a legacy SSE compatibility representation."""

    protocol_version: Literal["1"] = "1"
    type: UIEventType
    payload: dict[str, Any]
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None

    def to_legacy_sse(self) -> dict[str, str]:
        """Emit the existing SSE shape while clients migrate to envelopes."""

        return {
            "event": _LEGACY_EVENT_NAMES[self.type],
            "data": json.dumps(self.payload),
            "id": self.event_id,
        }


def build_legacy_sse_event(
    event_type: UIEventType,
    payload: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> dict[str, str]:
    return UIEventEnvelope(
        type=event_type,
        payload=payload,
        correlation_id=correlation_id,
    ).to_legacy_sse()


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
    "UIEventEnvelope",
    "UIEventType",
    "build_ag_ui_sse_event",
    "build_ag_ui_state_snapshot",
    "build_legacy_sse_event",
]
