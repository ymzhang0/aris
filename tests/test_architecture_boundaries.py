from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.aris_apps.aiida.agent import runtime as aiida_runtime
from src.aris_apps.aiida.capabilities import ManagedAiiDACapability
from src.aris_apps.aiida.chat import service as chat_service
from src.aris_apps.aiida.chat.session_application_service import (
    ChatSessionApplicationService,
)
from src.aris_apps.aiida.chat.session_query_service import (
    ChatSessionQueryService,
)
from src.aris_apps.aiida.domain.submissions import (
    extract_recovery_plan,
    normalize_submission_request,
    render_submission_blocker_message,
    submission_draft_is_batch,
)
from src.aris_core.agent import AgentModelRejectedError, AgentRunRequest
from src.aris_core.schema.ui_event import (
    build_ag_ui_sse_event,
    build_ag_ui_state_snapshot,
)


def test_ag_ui_state_snapshot_contains_atomic_aris_state() -> None:
    encoded = build_ag_ui_sse_event(
        build_ag_ui_state_snapshot(
            chat={"version": 4, "messages": []},
            sessions={"version": 2, "items": []},
        )
    )

    assert "event" not in encoded
    data = json.loads(encoded["data"])
    assert data["type"] == "STATE_SNAPSHOT"
    assert data["snapshot"]["aris"]["chat"]["version"] == 4
    assert data["snapshot"]["aris"]["sessions"]["version"] == 2


def test_submission_domain_uses_explicit_task_mode() -> None:
    normalized = normalize_submission_request(
        {
            "mode": "batch",
            "workchain": "quantumespresso.pw.relax",
            "code": "pw@localhost",
            "structure_pks": [1, "2", 0],
            "matrix_mode": "zip",
        }
    )

    assert normalized == {
        "mode": "batch",
        "workchain": "quantumespresso.pw.relax",
        "code": "pw@localhost",
        "protocol": "moderate",
        "structure_pks": [1, 2],
        "matrix_mode": "zip",
    }
    assert normalize_submission_request(
        {
            "workchain": "quantumespresso.pw.relax",
            "code": "pw@localhost",
            "structure_pks": [1, 2],
        }
    ) is None


def test_submission_domain_reports_batch_and_recovery() -> None:
    recovery_plan = {"summary": "A code is missing", "issues": [{"message": "Choose a code"}]}
    draft = {
        "meta": {
            "job_count": 2,
            "recovery_plan": recovery_plan,
        }
    }

    assert submission_draft_is_batch(draft) is True
    assert extract_recovery_plan(draft) is recovery_plan
    assert render_submission_blocker_message(
        task_mode="batch",
        recovery_plan=recovery_plan,
        next_step="Select a code.",
    ) == (
        "ARIS could not prepare the batch submission preview yet.\n\n"
        "Blocked reason: A code is missing\n\n"
        "Reported issues:\n"
        "- Choose a code\n\n"
        "Next step: Select a code."
    )


def test_chat_session_commands_and_queries_use_dedicated_services() -> None:
    assert isinstance(
        chat_service._get_session_application_service(),
        ChatSessionApplicationService,
    )
    assert isinstance(
        chat_service._get_session_query_service(),
        ChatSessionQueryService,
    )


@pytest.mark.anyio
async def test_pydantic_runtime_returns_provider_neutral_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = SimpleNamespace(answer="done")

    class FakeAgent:
        async def run(self, prompt, **kwargs):
            assert prompt == "inspect node 42"
            assert kwargs["model"] == "resolved-model"
            return SimpleNamespace(output=output)

    monkeypatch.setattr(aiida_runtime, "_build_gemini_model", lambda _name: "resolved-model")
    monkeypatch.setattr(aiida_runtime, "_build_gemini_model_settings", lambda: None)
    runtime = aiida_runtime.PydanticAIGeminiRuntime(FakeAgent())

    result = await runtime.run(
        AgentRunRequest(
            prompt="inspect node 42",
            deps=SimpleNamespace(),
            model_name="gemini-test",
        )
    )

    assert result.output is output
    assert result.provider == "Gemini"
    assert result.model_name == "gemini-test"


@pytest.mark.anyio
async def test_pydantic_runtime_maps_provider_model_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        async def run(self, *_args, **_kwargs):
            raise RuntimeError("status_code: 404 model is not found for api version")

    monkeypatch.setattr(aiida_runtime, "_build_gemini_model", lambda _name: "resolved-model")
    runtime = aiida_runtime.PydanticAIGeminiRuntime(FakeAgent())

    with pytest.raises(AgentModelRejectedError) as error:
        await runtime.run(
            AgentRunRequest(
                prompt="hello",
                deps=SimpleNamespace(),
                model_name="missing-model",
            )
        )

    assert error.value.provider == "Gemini"
    assert error.value.model_name == "missing-model"


@pytest.mark.anyio
async def test_managed_aiida_capability_delegates_to_worker_client() -> None:
    snapshot = SimpleNamespace(status="online")

    class FakeClient:
        bridge_url = "http://worker.test"

        def __init__(self) -> None:
            self.requests = []

        async def get_status(self):
            return snapshot

        async def get_plugins(self):
            return ["plugin"]

        async def get_resources(self):
            return {"computers": []}

        async def get_profiles(self):
            return {"profiles": []}

        async def switch_profile(self, profile):
            return {"current_profile": profile}

        async def get_system_info(self):
            return {"version": "2.7"}

        async def worker_call(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            return {"method": method, "path": path, **kwargs}

    client = FakeClient()
    capability = ManagedAiiDACapability(client)  # type: ignore[arg-type]

    assert capability.bridge_url == "http://worker.test"
    assert await capability.get_status() is snapshot
    assert await capability.get_plugins() == ["plugin"]
    assert await capability.get_resources() == {"computers": []}
    assert await capability.get_profiles() == {"profiles": []}
    assert await capability.switch_profile("research") == {"current_profile": "research"}
    assert await capability.get_system_info() == {"version": "2.7"}
    assert await capability.inspect_process("12") == {
        "method": "GET",
        "path": "/process/12",
    }
    assert await capability.get_submission_spec("quantumespresso.pw.base") == {
        "method": "GET",
        "path": "/submission/spec/quantumespresso.pw.base",
    }
    assert await capability.build_submission_draft({"workchain": "pw.base"}) == {
        "method": "POST",
        "path": "/submission/draft-builder",
        "json": {"workchain": "pw.base"},
        "retries": 0,
    }
