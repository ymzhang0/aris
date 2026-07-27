from __future__ import annotations

import pytest

from src.aris_apps.aiida.agent import tools


@pytest.mark.anyio
async def test_list_remote_plugins_uses_canonical_worker_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "GET"
        assert path == "/plugins"
        return {"plugins": ["quantumespresso.pw.base"]}

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    assert await tools.list_remote_plugins() == ["quantumespresso.pw.base"]


@pytest.mark.anyio
async def test_draft_workchain_builder_uses_canonical_protocol_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "POST"
        assert path == "/submission/draft-builder"
        assert kwargs["json"] == {
            "entry_point": "quantumespresso.pw.base",
            "protocol": "moderate",
            "intent_data": {
                "structure_pk": 12,
                "code": "pw@localhost",
                "electronic_type": "metal",
            },
            "overrides": {"pw": {"metadata": {"options": {"resources": {"num_machines": 1}}}}},
        }
        return {"status": "DRAFT_READY"}

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    result = await tools.draft_workchain_builder(
        "quantumespresso.pw.base",
        12,
        "pw@localhost",
        protocol_kwargs={"electronic_type": "metal"},
        overrides={"pw": {"metadata": {"options": {"resources": {"num_machines": 1}}}}},
    )

    assert result == {"status": "DRAFT_READY"}


@pytest.mark.anyio
async def test_run_python_code_success_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "POST"
        assert path == "/management/run-python"
        assert kwargs.get("json", {}).get("script_content") == "print('hello')"
        return {"success": True, "output": "hello"}

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    result = await tools.run_python_code("print('hello')")

    assert result == "hello"


@pytest.mark.anyio
async def test_run_python_code_returns_missing_module_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "POST"
        assert path == "/management/run-python"
        return {
            "success": False,
            "error": (
                "Traceback (most recent call last):\n"
                "  File \"<string>\", line 1, in <module>\n"
                "ModuleNotFoundError: No module named 'aiida_pseudo.data.family'\n"
            ),
            "output": "",
        }

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    result = await tools.run_python_code("import aiida_pseudo")

    assert isinstance(result, dict)
    assert result["missing_module"] == "aiida_pseudo.data.family"
    assert "missing this Python module" in result["hint"]


@pytest.mark.anyio
async def test_register_specialized_skill_calls_registry_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "POST"
        assert path == "/registry/register"
        body = kwargs.get("json", {})
        assert body["script_name"] == "relax_helper"
        assert "def main" in body["script"]
        return {"status": "registered", "script_name": body["script_name"]}

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    payload = await tools.register_specialized_skill(
        skill_name="relax_helper",
        script="def main(params):\n    return params\n",
        description="Reusable relax helper",
        overwrite=True,
    )

    assert isinstance(payload, dict)
    assert payload["status"] == "registered"
    assert payload["script_name"] == "relax_helper"


@pytest.mark.anyio
async def test_execute_specialized_skill_calls_execute_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "POST"
        assert path == "/execute/relax_helper"
        assert kwargs.get("json") == {"params": {"pk": 264}}
        return {"success": True, "result": {"submitted": [1001]}}

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    payload = await tools.execute_specialized_skill("relax_helper", {"pk": 264})

    assert isinstance(payload, dict)
    assert payload["success"] is True
    assert payload["result"]["submitted"] == [1001]


@pytest.mark.anyio
async def test_list_registered_skills_normalizes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_request_json(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "GET"
        assert path == "/registry/list"
        return {
            "count": 2,
            "items": [
                {"name": "skill_a", "description": "A", "updated_at": "2026-03-01T00:00:00Z"},
                {"name": "skill_b", "entrypoint": "main(params)"},
            ],
        }

    monkeypatch.setattr(tools, "request_json", _fake_request_json)

    payload = await tools.list_registered_skills()

    assert isinstance(payload, dict)
    assert payload["count"] == 2
    assert payload["items"][0]["name"] == "skill_a"
    assert payload["items"][1]["name"] == "skill_b"


def test_list_registered_skills_sync_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_request_json_sync(method: str, path: str, **kwargs):  # noqa: ANN003
        assert method == "GET"
        assert path == "/registry/list"
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(tools, "request_json_sync", _fake_request_json_sync)

    payload = tools.list_registered_skills_sync()

    assert payload == {"count": 0, "items": []}


def test_summarize_worker_error_prefers_traceback_root_cause() -> None:
    error_text = (
        "Traceback (most recent call last):\n"
        "  File \"<string>\", line 2, in <module>\n"
        "ImportError: cannot import name 'load_dbenv' from 'aiida'\n"
    )

    summary = tools._summarize_worker_error(error_text)

    assert summary == "ImportError: cannot import name 'load_dbenv' from 'aiida'"
