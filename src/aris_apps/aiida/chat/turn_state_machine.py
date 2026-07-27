"""Explicit state machine for one chat turn and its model retries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable

from src.aris_core.agent import AgentModelRejectedError, AgentRunRequest


class ChatTurnState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    PROCESSING = "processing"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidChatTurnTransition(RuntimeError):
    """Raised when application code attempts an invalid turn transition."""


@dataclass(frozen=True)
class ChatTurnRetry:
    attempt: int
    max_attempts: int
    wait_seconds: float
    error: str


_ALLOWED_TRANSITIONS: dict[ChatTurnState, frozenset[ChatTurnState]] = {
    ChatTurnState.QUEUED: frozenset(
        {
            ChatTurnState.RUNNING,
            ChatTurnState.RECOVERING,
            ChatTurnState.CANCELLED,
        }
    ),
    ChatTurnState.RUNNING: frozenset(
        {
            ChatTurnState.RETRY_WAIT,
            ChatTurnState.PROCESSING,
            ChatTurnState.RECOVERING,
            ChatTurnState.CANCELLED,
        }
    ),
    ChatTurnState.RETRY_WAIT: frozenset(
        {
            ChatTurnState.RUNNING,
            ChatTurnState.RECOVERING,
            ChatTurnState.CANCELLED,
        }
    ),
    ChatTurnState.PROCESSING: frozenset(
        {
            ChatTurnState.COMPLETED,
            ChatTurnState.RECOVERING,
            ChatTurnState.CANCELLED,
        }
    ),
    ChatTurnState.RECOVERING: frozenset(
        {
            ChatTurnState.FAILED,
            ChatTurnState.CANCELLED,
        }
    ),
    ChatTurnState.COMPLETED: frozenset(),
    ChatTurnState.FAILED: frozenset(),
    ChatTurnState.CANCELLED: frozenset(),
}


class ChatTurnStateMachine:
    """Tracks legal execution, retry, recovery, and terminal transitions."""

    def __init__(
        self,
        *,
        turn_id: int,
        unavailable_retries: int,
        base_backoff_seconds: float,
    ) -> None:
        self.turn_id = int(turn_id)
        self.state = ChatTurnState.QUEUED
        self.max_attempts = max(1, int(unavailable_retries) + 1)
        self.base_backoff_seconds = max(
            0.0,
            float(base_backoff_seconds),
        )
        self.attempt = 0
        self.retry_count = 0
        self.error: str | None = None
        self.failure_kind: str | None = None
        self.retry_wait_seconds: float | None = None

    @property
    def terminal(self) -> bool:
        return not _ALLOWED_TRANSITIONS[self.state]

    def transition(self, target: ChatTurnState) -> None:
        if target == self.state:
            return
        if target not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidChatTurnTransition(
                f"Cannot transition chat turn {self.turn_id} "
                f"from {self.state.value} to {target.value}"
            )
        self.state = target

    def begin_attempt(self) -> None:
        self.transition(ChatTurnState.RUNNING)
        self.attempt += 1
        self.retry_wait_seconds = None

    def schedule_retry(self, error: Exception) -> ChatTurnRetry:
        if self.attempt >= self.max_attempts:
            raise InvalidChatTurnTransition(
                f"Chat turn {self.turn_id} exhausted its retry budget"
            )
        wait_seconds = self.base_backoff_seconds * (
            2 ** max(0, self.attempt - 1)
        )
        self.error = str(error)
        self.failure_kind = "provider_unavailable"
        self.retry_count += 1
        self.retry_wait_seconds = wait_seconds
        self.transition(ChatTurnState.RETRY_WAIT)
        return ChatTurnRetry(
            attempt=self.attempt,
            max_attempts=self.max_attempts,
            wait_seconds=wait_seconds,
            error=self.error,
        )

    def mark_processing(self) -> None:
        self.error = None
        self.failure_kind = None
        self.retry_wait_seconds = None
        self.transition(ChatTurnState.PROCESSING)

    def begin_recovery(
        self,
        error: Exception,
        *,
        failure_kind: str,
    ) -> None:
        if self.state in {
            ChatTurnState.COMPLETED,
            ChatTurnState.FAILED,
            ChatTurnState.CANCELLED,
        }:
            return
        self.error = str(error)
        self.failure_kind = str(failure_kind or "execution_error")
        self.retry_wait_seconds = None
        self.transition(ChatTurnState.RECOVERING)

    def complete(self) -> None:
        self.transition(ChatTurnState.COMPLETED)

    def fail(
        self,
        error: Exception,
        *,
        failure_kind: str = "execution_error",
    ) -> None:
        if self.state != ChatTurnState.RECOVERING:
            self.begin_recovery(error, failure_kind=failure_kind)
        self.transition(ChatTurnState.FAILED)

    def cancel(self) -> None:
        if self.state in {
            ChatTurnState.COMPLETED,
            ChatTurnState.FAILED,
            ChatTurnState.CANCELLED,
        }:
            return
        self.failure_kind = "cancelled"
        self.retry_wait_seconds = None
        self.transition(ChatTurnState.CANCELLED)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state.value,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "retry_count": self.retry_count,
            "terminal": self.terminal,
        }
        if self.failure_kind:
            payload["failure_kind"] = self.failure_kind
        if self.error:
            payload["error"] = self.error
        if self.retry_wait_seconds is not None:
            payload["retry_wait_seconds"] = self.retry_wait_seconds
        return payload


RetryCallback = Callable[[ChatTurnRetry], None]
Sleep = Callable[[float], Awaitable[None]]


async def execute_agent_turn(
    *,
    runtime: Any,
    request: AgentRunRequest,
    machine: ChatTurnStateMachine,
    on_retry: RetryCallback | None = None,
    sleep: Sleep = asyncio.sleep,
) -> Any:
    """Invoke an agent runtime while driving the turn state machine."""

    while machine.attempt < machine.max_attempts:
        machine.begin_attempt()
        try:
            result = await runtime.run(request)
        except asyncio.CancelledError:
            machine.cancel()
            raise
        except Exception as error:  # noqa: BLE001
            is_model_rejected = isinstance(error, AgentModelRejectedError)
            is_retryable = (
                not is_model_rejected
                and runtime.is_retryable_unavailable_error(error)
            )
            if is_retryable and machine.attempt < machine.max_attempts:
                retry = machine.schedule_retry(error)
                if on_retry is not None:
                    on_retry(retry)
                await sleep(retry.wait_seconds)
                continue

            if is_model_rejected:
                failure_kind = "model_rejected"
            elif is_retryable:
                failure_kind = "provider_unavailable_exhausted"
            else:
                failure_kind = "runtime_error"
            machine.fail(error, failure_kind=failure_kind)
            raise

        machine.mark_processing()
        return result

    error = RuntimeError("Model call failed: retry loop ended without a result")
    machine.fail(error, failure_kind="provider_unavailable_exhausted")
    raise error


__all__ = [
    "ChatTurnRetry",
    "ChatTurnState",
    "ChatTurnStateMachine",
    "InvalidChatTurnTransition",
    "execute_agent_turn",
]
