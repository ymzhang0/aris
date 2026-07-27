from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.aris_apps.aiida.chat.turn_state_machine import (
    ChatTurnState,
    ChatTurnStateMachine,
    InvalidChatTurnTransition,
    execute_agent_turn,
)
from src.aris_core.agent import AgentModelRejectedError, AgentRunRequest


def test_turn_state_machine_tracks_retry_and_completion() -> None:
    machine = ChatTurnStateMachine(
        turn_id=7,
        unavailable_retries=2,
        base_backoff_seconds=0.5,
    )

    machine.begin_attempt()
    retry = machine.schedule_retry(RuntimeError("temporarily unavailable"))
    machine.begin_attempt()
    machine.mark_processing()
    machine.complete()

    assert retry.attempt == 1
    assert retry.max_attempts == 3
    assert retry.wait_seconds == 0.5
    assert machine.to_payload() == {
        "state": "completed",
        "attempt": 2,
        "max_attempts": 3,
        "retry_count": 1,
        "terminal": True,
    }


def test_turn_state_machine_rejects_invalid_transition() -> None:
    machine = ChatTurnStateMachine(
        turn_id=8,
        unavailable_retries=0,
        base_backoff_seconds=1,
    )

    with pytest.raises(InvalidChatTurnTransition):
        machine.complete()


@pytest.mark.anyio
async def test_execute_agent_turn_retries_then_enters_processing() -> None:
    sleeps: list[float] = []
    retries = []

    class Runtime:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, request):
            self.calls += 1
            assert request.prompt == "inspect node 42"
            if self.calls < 3:
                raise RuntimeError("provider unavailable")
            return SimpleNamespace(output="done")

        @staticmethod
        def is_retryable_unavailable_error(error: Exception) -> bool:
            return "unavailable" in str(error)

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    machine = ChatTurnStateMachine(
        turn_id=9,
        unavailable_retries=2,
        base_backoff_seconds=0.25,
    )
    result = await execute_agent_turn(
        runtime=Runtime(),
        request=AgentRunRequest(prompt="inspect node 42", deps=None),
        machine=machine,
        on_retry=retries.append,
        sleep=_fake_sleep,
    )

    assert result.output == "done"
    assert sleeps == [0.25, 0.5]
    assert [retry.attempt for retry in retries] == [1, 2]
    assert machine.state == ChatTurnState.PROCESSING
    assert machine.attempt == 3
    assert machine.retry_count == 2


@pytest.mark.anyio
async def test_execute_agent_turn_marks_exhausted_provider_failure() -> None:
    class Runtime:
        async def run(self, _request):
            raise RuntimeError("provider unavailable")

        @staticmethod
        def is_retryable_unavailable_error(_error: Exception) -> bool:
            return True

    machine = ChatTurnStateMachine(
        turn_id=10,
        unavailable_retries=1,
        base_backoff_seconds=0,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await execute_agent_turn(
            runtime=Runtime(),
            request=AgentRunRequest(prompt="hello", deps=None),
            machine=machine,
        )

    assert machine.state == ChatTurnState.FAILED
    assert machine.attempt == 2
    assert machine.failure_kind == "provider_unavailable_exhausted"


@pytest.mark.anyio
async def test_execute_agent_turn_does_not_retry_rejected_model() -> None:
    class Runtime:
        async def run(self, _request):
            raise AgentModelRejectedError(
                provider="Example",
                model_name="missing",
                detail="Not supported",
            )

        @staticmethod
        def is_retryable_unavailable_error(_error: Exception) -> bool:
            return True

    machine = ChatTurnStateMachine(
        turn_id=11,
        unavailable_retries=3,
        base_backoff_seconds=0,
    )

    with pytest.raises(AgentModelRejectedError):
        await execute_agent_turn(
            runtime=Runtime(),
            request=AgentRunRequest(prompt="hello", deps=None),
            machine=machine,
        )

    assert machine.state == ChatTurnState.FAILED
    assert machine.attempt == 1
    assert machine.retry_count == 0
    assert machine.failure_kind == "model_rejected"
