"""Application-facing AiiDA capability boundary."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.aris_apps.aiida.client import AiiDAWorkerClient, WorkerSnapshot, aiida_worker_client


@runtime_checkable
class AiiDACapability(Protocol):
    """Deterministic AiiDA operations consumed by the ARIS application."""

    @property
    def transport_endpoint(self) -> str: ...

    async def get_status(self) -> WorkerSnapshot: ...

    async def get_plugins(self) -> list[str]: ...

    async def get_resources(self) -> dict[str, Any]: ...

    async def get_profiles(self) -> dict[str, Any]: ...

    async def switch_profile(self, profile: str) -> dict[str, Any]: ...

    async def get_system_info(self) -> dict[str, Any]: ...

    async def list_recent_processes(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]: ...

    async def inspect_process(self, identifier: str) -> dict[str, Any]: ...

    async def get_process_logs(self, pk: int) -> dict[str, Any]: ...

    async def list_recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]: ...

    async def list_submission_plugins(self) -> dict[str, Any]: ...

    async def import_structure(
        self,
        artifact: dict[str, Any],
        *,
        label: str | None = None,
        description: str | None = None,
        deduplicate: bool = True,
    ) -> dict[str, Any]: ...

    async def get_workflow_catalog(self) -> dict[str, Any]: ...

    async def resolve_input_candidates(
        self,
        workchain: str,
        port_path: str,
        *,
        limit: int = 50,
    ) -> dict[str, Any]: ...

    async def get_submission_spec(
        self,
        workchain: str,
    ) -> dict[str, Any]: ...

    async def build_submission_draft(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def validate_submission_draft(
        self,
        draft: dict[str, Any],
    ) -> dict[str, Any]: ...


class ManagedAiiDACapability:
    """Adapter backed by ARIS' managed aiida-worker subprocess."""

    def __init__(self, client: AiiDAWorkerClient) -> None:
        self._client = client

    @property
    def transport_endpoint(self) -> str:
        return self._client.transport_endpoint

    async def get_status(self) -> WorkerSnapshot:
        return await self._client.get_status()

    async def get_plugins(self) -> list[str]:
        return await self._client.get_plugins()

    async def get_resources(self) -> dict[str, Any]:
        return await self._client.get_resources()

    async def get_profiles(self) -> dict[str, Any]:
        return await self._client.get_profiles()

    async def switch_profile(self, profile: str) -> dict[str, Any]:
        return await self._client.switch_profile(profile)

    async def get_system_info(self) -> dict[str, Any]:
        return await self._client.get_system_info()

    async def list_recent_processes(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        payload = await self._client.call("process.recent", {"limit": int(limit)})
        return payload if isinstance(payload, dict) else {"processes": []}

    async def inspect_process(self, identifier: str) -> dict[str, Any]:
        cleaned = str(identifier or "").strip()
        if not cleaned:
            raise ValueError("Process identifier is required")
        payload = await self._client.call("process.detail", {"identifier": cleaned})
        return payload if isinstance(payload, dict) else {}

    async def get_process_logs(self, pk: int) -> dict[str, Any]:
        payload = await self._client.call("process.logs", {"identifier": int(pk)})
        return payload if isinstance(payload, dict) else {"logs": []}

    async def list_recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": int(limit)}
        cleaned_node_type = str(node_type or "").strip()
        if cleaned_node_type:
            params["node_type"] = cleaned_node_type
        payload = await self._client.call("node.recent", params)
        return payload if isinstance(payload, dict) else {"nodes": []}

    async def list_submission_plugins(self) -> dict[str, Any]:
        payload = await self._client.call("resource.plugins")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"plugins": [str(item) for item in payload if str(item).strip()]}
        return {"plugins": []}

    async def import_structure(
        self,
        artifact: dict[str, Any],
        *,
        label: str | None = None,
        description: str | None = None,
        deduplicate: bool = True,
    ) -> dict[str, Any]:
        payload = await self._client.call(
            "structure.import",
            {
                "artifact": dict(artifact),
                "label": str(label).strip() if label else None,
                "description": str(description).strip() if description else None,
                "deduplicate": bool(deduplicate),
            },
            timeout=30.0,
        )
        return payload if isinstance(payload, dict) else {}

    async def get_workflow_catalog(self) -> dict[str, Any]:
        payload = await self._client.call("workflow.catalog", timeout=30.0)
        return payload if isinstance(payload, dict) else {"workflows": [], "count": 0}

    async def resolve_input_candidates(
        self,
        workchain: str,
        port_path: str,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        payload = await self._client.call(
            "workflow.input_candidates",
            {
                "entry_point": str(workchain).strip(),
                "port_path": str(port_path).strip(),
                "limit": max(1, min(int(limit), 200)),
            },
            timeout=15.0,
        )
        return payload if isinstance(payload, dict) else {"candidates": []}

    async def get_submission_spec(
        self,
        workchain: str,
    ) -> dict[str, Any]:
        cleaned = str(workchain or "").strip()
        if not cleaned:
            raise ValueError("WorkChain entry point is required")
        payload = await self._client.call("submission.spec", {"entry_point": cleaned}, timeout=15.0)
        return payload if isinstance(payload, dict) else {}

    async def build_submission_draft(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(request)
        normalized["entry_point"] = str(
            normalized.pop("workchain", None) or normalized.get("entry_point") or ""
        ).strip()
        if normalized.get("builder_strategy") == "protocol":
            intent_data = dict(normalized.get("protocol_kwargs") or {})
            if normalized.get("code"):
                intent_data["code"] = normalized["code"]
            if normalized.get("structure_pk"):
                intent_data["structure_pk"] = normalized["structure_pk"]
            normalized["intent_data"] = intent_data
        payload = await self._client.call("submission.builder_draft", normalized, timeout=30.0)
        return payload if isinstance(payload, dict) else {}

    async def validate_submission_draft(
        self,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._client.call("submission.validate", dict(draft), timeout=30.0)
        return payload if isinstance(payload, dict) else {}


aiida_capability: AiiDACapability = ManagedAiiDACapability(aiida_worker_client)


__all__ = ["AiiDACapability", "ManagedAiiDACapability", "aiida_capability"]
