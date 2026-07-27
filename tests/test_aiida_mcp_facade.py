from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.aris_apps.aiida.capabilities import HttpAiiDACapability
from src.aris_apps.aiida.mcp_facade import (
    AiiDAMCPFacade,
    build_aiida_mcp_server,
)


@dataclass
class _Resources:
    computers: int = 1
    codes: int = 2
    workchains: int = 3


@dataclass
class _Snapshot:
    status: str = "online"
    profile: str = "research"
    resources: _Resources = field(default_factory=_Resources)


class _Capability:
    bridge_url = "http://worker.test"

    def __init__(self) -> None:
        self.calls = []

    async def get_status(self):
        return _Snapshot()

    async def get_plugins(self):
        return ["quantumespresso.pw.base"]

    async def get_resources(self):
        return {"computers": [{"label": "localhost"}]}

    async def get_profiles(self):
        return {"current_profile": "research", "profiles": ["research"]}

    async def switch_profile(self, profile):
        return {"current_profile": profile}

    async def get_system_info(self):
        return {"aiida_version": "2.7"}

    async def list_recent_processes(self, *, limit=20):
        self.calls.append(("recent_processes", limit))
        return {"processes": [{"pk": 42}]}

    async def inspect_process(self, identifier):
        self.calls.append(("inspect_process", identifier))
        return {"pk": int(identifier)}

    async def get_process_logs(self, pk):
        return {"pk": pk, "logs": ["done"]}

    async def list_recent_nodes(self, *, limit=50, node_type=None):
        self.calls.append(("recent_nodes", limit, node_type))
        return {"nodes": []}

    async def list_submission_plugins(self):
        return {"plugins": ["quantumespresso.pw.base"]}

    async def get_submission_spec(self, workchain):
        return {"workchain": workchain, "inputs": {}}

    async def build_submission_draft(self, request):
        self.calls.append(("build_submission_draft", request))
        return {"status": "SUBMISSION_DRAFT", "request": request}

    async def validate_submission_draft(self, draft):
        return {"is_valid": True, "draft": draft}


@pytest.mark.anyio
async def test_http_capability_normalizes_canonical_plugin_list() -> None:
    class _Client:
        bridge_url = "http://worker.test"

        async def request_json(self, method, path):
            assert method == "GET"
            assert path == "/plugins"
            return ["quantumespresso.pw.base"]

    capability = HttpAiiDACapability(_Client())

    assert await capability.list_submission_plugins() == {
        "plugins": ["quantumespresso.pw.base"],
    }


@pytest.mark.anyio
async def test_aiida_mcp_facade_normalizes_limits_and_status() -> None:
    capability = _Capability()
    facade = AiiDAMCPFacade(capability)

    status = await facade.status()
    await facade.recent_processes(limit=999)
    await facade.recent_nodes(limit=0, node_type="StructureData")

    assert status["status"] == "online"
    assert status["resources"]["codes"] == 2
    assert capability.calls == [
        ("recent_processes", 200),
        ("recent_nodes", 1, "StructureData"),
    ]


@pytest.mark.anyio
async def test_aiida_mcp_server_exposes_safe_tools_resources_and_prompt() -> None:
    capability = _Capability()
    server = build_aiida_mcp_server(capability)

    tools = {tool.name: tool for tool in await server.list_tools()}
    resources = {
        str(resource.uri)
        for resource in await server.list_resources()
    }
    prompts = {
        prompt.name
        for prompt in await server.list_prompts()
    }

    assert "aiida_inspect_process" in tools
    assert "aiida_build_submission_preview" in tools
    assert "aiida_submit" not in tools
    assert tools["aiida_inspect_process"].annotations.readOnlyHint is True
    assert tools[
        "aiida_build_submission_preview"
    ].annotations.destructiveHint is False
    preview_schema = tools[
        "aiida_build_submission_preview"
    ].parameters["properties"]["request"]
    assert preview_schema["properties"]["mode"]["enum"] == [
        "single",
        "batch",
    ]
    assert "workchain" in preview_schema["required"]
    assert "code" in preview_schema["required"]
    assert resources == {
        "aiida://profiles",
        "aiida://resources",
        "aiida://status",
    }
    assert prompts == {"aiida_research_workflow"}

    result = await server.call_tool(
        "aiida_inspect_process",
        {"identifier": "42"},
    )
    assert result.structured_content == {"pk": 42}


@pytest.mark.anyio
async def test_aiida_mcp_submission_tool_builds_preview_without_submit() -> None:
    capability = _Capability()
    server = build_aiida_mcp_server(capability)

    result = await server.call_tool(
        "aiida_build_submission_preview",
        {
            "request": {
                "mode": "single",
                "workchain": "quantumespresso.pw.base",
                "structure_pk": 12,
                "code": "pw@localhost",
            }
        },
    )

    assert result.structured_content["status"] == "SUBMISSION_DRAFT"
    assert capability.calls == [
        (
            "build_submission_draft",
            {
                "mode": "single",
                "workchain": "quantumespresso.pw.base",
                "structure_pk": 12,
                "code": "pw@localhost",
                "protocol": "moderate",
                "structure_pks": [],
                "overrides": {},
                "protocol_kwargs": {},
                "parameter_grid": {},
                "matrix_mode": "product",
            },
        )
    ]
