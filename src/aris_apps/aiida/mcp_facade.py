"""MCP-facing facade for deterministic AiiDA capabilities."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, Literal, Mapping

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.aris_apps.aiida.capabilities import AiiDACapability, aiida_capability
from src.aris_apps.aiida.client import (
    reset_worker_request_context,
    set_worker_request_context,
)
from src.aris_apps.aiida.mcp_context import AiiDAProjectCatalog
from src.aris_apps.aiida.mcp_ui import (
    AIIDA_EXPLORER_HTML,
    AIIDA_EXPLORER_RESOURCE_URI,
    AIIDA_WORKSPACE_HTML,
    AIIDA_WORKSPACE_RESOURCE_URI,
)

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

    def __init__(
        self,
        capability: AiiDACapability,
        project_catalog: AiiDAProjectCatalog | None = None,
    ) -> None:
        self._capability = capability
        self._project_catalog = project_catalog

    @asynccontextmanager
    async def _project_scope(self, project_id: str | None):
        if self._project_catalog is None:
            yield
            return
        ensure_runtime = getattr(self._project_catalog, "ensure_runtime", None)
        if ensure_runtime is not None:
            await ensure_runtime(project_id)
        context = self._project_catalog.context_for(project_id)
        token = set_worker_request_context(context)
        try:
            yield
        finally:
            reset_worker_request_context(token)

    async def projects(self) -> dict[str, Any]:
        if self._project_catalog is None:
            return {"projects": [], "selected_project_id": None}
        projects = self._project_catalog.list_projects()
        return {
            "projects": projects,
            "selected_project_id": self._project_catalog.selected_project_id(),
        }

    async def select_project(self, project_id: str) -> dict[str, Any]:
        if self._project_catalog is None:
            raise ValueError("Project selection is unavailable for this MCP server")
        selected = self._project_catalog.select_project(project_id)
        ensure_runtime = getattr(self._project_catalog, "ensure_runtime", None)
        runtime = await ensure_runtime(project_id) if ensure_runtime is not None else None
        if runtime is None:
            return selected
        return {**selected, "runtime": runtime}

    async def status(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return _jsonable(await self._capability.get_status())

    async def resources(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.get_resources()

    async def profiles(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.get_profiles()

    async def system_info(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.get_system_info()

    async def recent_processes(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.list_recent_processes(
                limit=max(1, min(int(limit), 200)),
            )

    async def inspect_process(
        self,
        *,
        identifier: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        cleaned = str(identifier or "").strip()
        if not cleaned:
            raise ValueError("Process identifier is required")
        async with self._project_scope(project_id):
            return await self._capability.inspect_process(cleaned)

    async def process_logs(self, *, pk: int, project_id: str | None = None) -> dict[str, Any]:
        normalized_pk = int(pk)
        if normalized_pk <= 0:
            raise ValueError("Process PK must be positive")
        async with self._project_scope(project_id):
            return await self._capability.get_process_logs(normalized_pk)

    async def recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.list_recent_nodes(
                limit=max(1, min(int(limit), 500)),
                node_type=str(node_type or "").strip() or None,
            )

    async def submission_plugins(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.list_submission_plugins()

    async def workflow_catalog(self, project_id: str | None = None) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.get_workflow_catalog()

    async def input_candidates(
        self,
        *,
        workchain: str,
        port_path: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._project_scope(project_id):
            return await self._capability.resolve_input_candidates(
                workchain,
                port_path,
                limit=limit,
            )

    async def submission_spec(
        self,
        *,
        workchain: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        cleaned = str(workchain or "").strip()
        if not cleaned:
            raise ValueError("WorkChain entry point is required")
        async with self._project_scope(project_id):
            return await self._capability.get_submission_spec(cleaned)

    async def build_submission_preview(
        self,
        *,
        request: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(request, dict) or not request:
            raise ValueError("Structured submission request is required")
        async with self._project_scope(project_id):
            return await self._capability.build_submission_draft(request)

    async def validate_submission_preview(
        self,
        *,
        draft: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(draft, dict) or not draft:
            raise ValueError("Submission draft is required")
        async with self._project_scope(project_id):
            return await self._capability.validate_submission_draft(draft)


def build_aiida_mcp_server(
    capability: AiiDACapability = aiida_capability,
    project_catalog: AiiDAProjectCatalog | None = None,
) -> FastMCP:
    """Build an MCP server exposing safe AiiDA inspection and preview tools."""

    facade = AiiDAMCPFacade(capability, project_catalog=project_catalog)
    server = FastMCP(
        "aris-aiida",
        instructions=(
            "Use structured AiiDA tools for inspection and submission preview "
            "preparation. This server never launches a submission; execution "
            "approval remains in the ARIS application."
        ),
    )

    @server.tool(
        name="aiida_list_projects",
        description="List ARIS projects and their AiiDA runtime configuration.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_list_projects() -> dict[str, Any]:
        return await facade.projects()

    @server.tool(
        name="aiida_select_project",
        description=(
            "Select the ARIS project for subsequent AiiDA operations. "
            "Prefer passing project_id explicitly to data tools when possible."
        ),
        annotations=_PREVIEW_ANNOTATIONS,
    )
    async def aiida_select_project(project_id: str) -> dict[str, Any]:
        return await facade.select_project(project_id)

    @server.tool(
        name="aiida_status",
        description="Read the current AiiDA worker and profile status.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_status(project_id: str | None = None) -> dict[str, Any]:
        return await facade.status(project_id=project_id)

    @server.tool(
        name="aiida_system_info",
        description="Read deterministic AiiDA system information.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_system_info(project_id: str | None = None) -> dict[str, Any]:
        return await facade.system_info(project_id=project_id)

    @server.tool(
        name="aiida_resources",
        description="Read configured AiiDA computers, codes, and WorkChains.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_resources(project_id: str | None = None) -> dict[str, Any]:
        return await facade.resources(project_id=project_id)

    @server.tool(
        name="aiida_profiles",
        description="Read available AiiDA profiles and the current profile.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_profiles(project_id: str | None = None) -> dict[str, Any]:
        return await facade.profiles(project_id=project_id)

    @server.tool(
        name="aiida_recent_processes",
        description="List recent AiiDA processes.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_recent_processes(
        limit: int = 20,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.recent_processes(limit=limit, project_id=project_id)

    @server.tool(
        name="aiida_inspect_process",
        description="Inspect one AiiDA process by PK or UUID.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_inspect_process(
        identifier: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.inspect_process(identifier=identifier, project_id=project_id)

    @server.tool(
        name="aiida_process_logs",
        description="Read logs for one AiiDA process PK.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_process_logs(pk: int, project_id: str | None = None) -> dict[str, Any]:
        return await facade.process_logs(pk=pk, project_id=project_id)

    @server.tool(
        name="aiida_recent_nodes",
        description="List recent AiiDA nodes with an optional node type.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_recent_nodes(
        limit: int = 50,
        node_type: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.recent_nodes(
            limit=limit,
            node_type=node_type,
            project_id=project_id,
        )

    @server.tool(
        name="aiida_submission_plugins",
        description="List installed submission-capable AiiDA WorkChains.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_submission_plugins(project_id: str | None = None) -> dict[str, Any]:
        return await facade.submission_plugins(project_id=project_id)

    @server.tool(
        name="aiida_workflow_catalog",
        description=(
            "List registered AiiDA WorkChains with package, description, protocols, "
            "builder strategy, and required inputs for workflow selection."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_workflow_catalog(project_id: str | None = None) -> dict[str, Any]:
        return await facade.workflow_catalog(project_id=project_id)

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
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.input_candidates(
            workchain=workchain,
            port_path=port_path,
            limit=limit,
            project_id=project_id,
        )

    @server.tool(
        name="aiida_submission_spec",
        description="Read the structured input specification for a WorkChain.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def aiida_submission_spec(
        workchain: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.submission_spec(workchain=workchain, project_id=project_id)

    @server.tool(
        name="aiida_build_submission_preview",
        description=(
            "Build a structured submission preview without launching it."
        ),
        annotations=_PREVIEW_ANNOTATIONS,
    )
    async def aiida_build_submission_preview(
        request: SubmissionPreviewRequest,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.build_submission_preview(
            request=request.model_dump(mode="json"),
            project_id=project_id,
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
        project_id: str | None = None,
    ) -> dict[str, Any]:
        return await facade.validate_submission_preview(draft=draft, project_id=project_id)

    @server.tool(
        name="render_aiida_explorer",
        description=(
            "Render the AiiDA Explorer widget for a final list of processes. "
            "Call aiida_recent_processes first and pass its process records."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
        app={
            "resourceUri": AIIDA_EXPLORER_RESOURCE_URI,
            "visibility": ["model", "app"],
        },
    )
    async def render_aiida_explorer(
        processes: list[dict[str, Any]],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Return model-visible data that the AiiDA Explorer widget renders."""

        payload: dict[str, Any] = {"processes": processes}
        cleaned_project_id = str(project_id or "").strip()
        if cleaned_project_id:
            payload["project_id"] = cleaned_project_id
        return payload

    @server.tool(
        name="render_aiida_workspace",
        description=(
            "Render the interactive AiiDA Workspace for browsing projects, "
            "resources, nodes, processes, workflows, and submission previews."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
        app={
            "resourceUri": AIIDA_WORKSPACE_RESOURCE_URI,
            "visibility": ["model", "app"],
        },
    )
    async def render_aiida_workspace(project_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        cleaned_project_id = str(project_id or "").strip()
        if cleaned_project_id:
            payload["project_id"] = cleaned_project_id
        return payload

    @server.resource(
        AIIDA_EXPLORER_RESOURCE_URI,
        name="AiiDA Explorer UI",
        description="Interactive AiiDA process explorer widget.",
        mime_type="text/html;profile=mcp-app",
    )
    async def aiida_explorer_resource() -> str:
        return AIIDA_EXPLORER_HTML

    @server.resource(
        AIIDA_WORKSPACE_RESOURCE_URI,
        name="AiiDA Workspace UI",
        description="Interactive project-scoped AiiDA workspace widget.",
        mime_type="text/html;profile=mcp-app",
    )
    async def aiida_workspace_resource() -> str:
        return AIIDA_WORKSPACE_HTML

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
