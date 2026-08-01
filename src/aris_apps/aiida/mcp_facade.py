"""MCP-facing facade for deterministic AiiDA capabilities."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Literal, Mapping

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.aris_apps.aiida.capabilities import AiiDACapability, aiida_capability

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_PREVIEW_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


class SubmissionPreviewRequest(BaseModel):
    """Machine-readable input for the MCP submission preview tool."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "batch"]
    builder_strategy: Literal["protocol", "explicit_inputs"] = "protocol"
    workchain: str = Field(min_length=1)
    code: str | None = Field(default=None, min_length=1)
    protocol: str = Field(default="moderate", min_length=1)
    structure_pk: int | None = Field(default=None, gt=0)
    structure_pks: list[int] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)
    protocol_kwargs: dict[str, Any] = Field(default_factory=dict)
    parameter_grid: dict[str, Any] = Field(default_factory=dict)
    matrix_mode: Literal["product", "zip"] = "product"
    inputs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_topology(self) -> "SubmissionPreviewRequest":
        if self.builder_strategy == "explicit_inputs":
            if not self.inputs:
                raise ValueError("explicit_inputs strategy requires inputs")
            if self.mode == "batch" and not self.parameter_grid:
                raise ValueError("batch explicit_inputs strategy requires parameter_grid")
            return self
        if not self.code:
            raise ValueError("protocol strategy requires code")
        if self.mode == "single":
            if self.structure_pk is None:
                raise ValueError(
                    "single mode requires structure_pk"
                )
            if self.structure_pks:
                raise ValueError(
                    "single mode cannot include structure_pks"
                )
        else:
            if not self.structure_pks:
                raise ValueError(
                    "batch mode requires structure_pks"
                )
            if self.structure_pk is not None:
                raise ValueError(
                    "batch mode cannot include structure_pk"
                )
        return self


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _json_resource(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
    )


class AiiDAMCPFacade:
    """Maps MCP operations to AiiDA without owning model orchestration."""

    def __init__(self, capability: AiiDACapability) -> None:
        self._capability = capability

    async def status(self) -> dict[str, Any]:
        return _jsonable(await self._capability.get_status())

    async def resources(self) -> dict[str, Any]:
        return await self._capability.get_resources()

    async def profiles(self) -> dict[str, Any]:
        return await self._capability.get_profiles()

    async def system_info(self) -> dict[str, Any]:
        return await self._capability.get_system_info()

    async def recent_processes(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self._capability.list_recent_processes(
            limit=max(1, min(int(limit), 200)),
        )

    async def inspect_process(
        self,
        *,
        identifier: str,
    ) -> dict[str, Any]:
        cleaned = str(identifier or "").strip()
        if not cleaned:
            raise ValueError("Process identifier is required")
        return await self._capability.inspect_process(cleaned)

    async def process_logs(self, *, pk: int) -> dict[str, Any]:
        normalized_pk = int(pk)
        if normalized_pk <= 0:
            raise ValueError("Process PK must be positive")
        return await self._capability.get_process_logs(normalized_pk)

    async def recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]:
        return await self._capability.list_recent_nodes(
            limit=max(1, min(int(limit), 500)),
            node_type=str(node_type or "").strip() or None,
        )

    async def submission_plugins(self) -> dict[str, Any]:
        return await self._capability.list_submission_plugins()

    async def workflow_catalog(self) -> dict[str, Any]:
        return await self._capability.get_workflow_catalog()

    async def input_candidates(
        self,
        *,
        workchain: str,
        port_path: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        return await self._capability.resolve_input_candidates(
            workchain,
            port_path,
            limit=limit,
        )

    async def submission_spec(
        self,
        *,
        workchain: str,
    ) -> dict[str, Any]:
        cleaned = str(workchain or "").strip()
        if not cleaned:
            raise ValueError("WorkChain entry point is required")
        return await self._capability.get_submission_spec(cleaned)

    async def build_submission_preview(
        self,
        *,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(request, dict) or not request:
            raise ValueError("Structured submission request is required")
        return await self._capability.build_submission_draft(request)

    async def validate_submission_preview(
        self,
        *,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(draft, dict) or not draft:
            raise ValueError("Submission draft is required")
        return await self._capability.validate_submission_draft(draft)


def build_aiida_mcp_server(
    capability: AiiDACapability = aiida_capability,
) -> FastMCP:
    """Build an MCP server exposing safe AiiDA inspection and preview tools."""

    facade = AiiDAMCPFacade(capability)
    server = FastMCP(
        "aris-aiida",
        instructions=(
            "Use structured AiiDA tools for inspection and submission preview "
            "preparation. This server never launches a submission; execution "
            "approval remains in the ARIS application."
        ),
    )

    @server.tool(
        name="aiida_status",
        description="Read the current AiiDA worker and profile status.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_status() -> dict[str, Any]:
        return await facade.status()

    @server.tool(
        name="aiida_system_info",
        description="Read deterministic AiiDA system information.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_system_info() -> dict[str, Any]:
        return await facade.system_info()

    @server.tool(
        name="aiida_recent_processes",
        description="List recent AiiDA processes.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_recent_processes(limit: int = 20) -> dict[str, Any]:
        return await facade.recent_processes(limit=limit)

    @server.tool(
        name="aiida_inspect_process",
        description="Inspect one AiiDA process by PK or UUID.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_inspect_process(identifier: str) -> dict[str, Any]:
        return await facade.inspect_process(identifier=identifier)

    @server.tool(
        name="aiida_process_logs",
        description="Read logs for one AiiDA process PK.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_process_logs(pk: int) -> dict[str, Any]:
        return await facade.process_logs(pk=pk)

    @server.tool(
        name="aiida_recent_nodes",
        description="List recent AiiDA nodes with an optional node type.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_recent_nodes(
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]:
        return await facade.recent_nodes(
            limit=limit,
            node_type=node_type,
        )

    @server.tool(
        name="aiida_submission_plugins",
        description="List installed submission-capable AiiDA WorkChains.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_submission_plugins() -> dict[str, Any]:
        return await facade.submission_plugins()

    @server.tool(
        name="aiida_workflow_catalog",
        description=(
            "List registered AiiDA WorkChains with package, description, protocols, "
            "builder strategy, and required inputs for workflow selection."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_workflow_catalog() -> dict[str, Any]:
        return await facade.workflow_catalog()

    @server.tool(
        name="aiida_input_candidates",
        description=(
            "Resolve stored AiiDA entities compatible with one WorkChain input port."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_input_candidates(
        workchain: str,
        port_path: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        return await facade.input_candidates(
            workchain=workchain,
            port_path=port_path,
            limit=limit,
        )

    @server.tool(
        name="aiida_submission_spec",
        description="Read the structured input specification for a WorkChain.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_submission_spec(workchain: str) -> dict[str, Any]:
        return await facade.submission_spec(workchain=workchain)

    @server.tool(
        name="aiida_build_submission_preview",
        description=(
            "Build a structured submission preview without launching it."
        ),
        annotations=_PREVIEW_ANNOTATIONS,
    )
    async def aiida_build_submission_preview(
        request: SubmissionPreviewRequest,
    ) -> dict[str, Any]:
        return await facade.build_submission_preview(
            request=request.model_dump(mode="json"),
        )

    @server.tool(
        name="aiida_validate_submission_preview",
        description=(
            "Validate a structured submission preview without launching it."
        ),
        annotations=_PREVIEW_ANNOTATIONS,
    )
    async def aiida_validate_submission_preview(
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        return await facade.validate_submission_preview(draft=draft)

    @server.resource(
        "aiida://status",
        name="AiiDA status",
        description="Current worker, profile, daemon, and plugin status.",
        mime_type="application/json",
    )
    async def aiida_status_resource() -> str:
        return _json_resource(await facade.status())

    @server.resource(
        "aiida://resources",
        name="AiiDA resources",
        description="Configured AiiDA computers, codes, and WorkChains.",
        mime_type="application/json",
    )
    async def aiida_resources_resource() -> str:
        return _json_resource(await facade.resources())

    @server.resource(
        "aiida://profiles",
        name="AiiDA profiles",
        description="Available and current AiiDA profiles.",
        mime_type="application/json",
    )
    async def aiida_profiles_resource() -> str:
        return _json_resource(await facade.profiles())

    @server.prompt(
        name="aiida_research_workflow",
        description="Protocol-first guidance for using the AiiDA tools.",
    )
    def aiida_research_workflow() -> str:
        return (
            "Inspect AiiDA state using read-only tools first. When calculation "
            "inputs are known, build and validate a structured submission "
            "preview. Do not claim that a calculation was launched: this MCP "
            "server intentionally exposes no submit tool, and ARIS requires a "
            "separate typed approval decision before execution."
        )

    return server


aiida_mcp_facade = AiiDAMCPFacade(aiida_capability)


__all__ = [
    "AiiDAMCPFacade",
    "SubmissionPreviewRequest",
    "aiida_mcp_facade",
    "build_aiida_mcp_server",
]
