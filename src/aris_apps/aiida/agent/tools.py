"""AiiDA worker proxy tools used by the ARIS AiiDA agent.

Thin-client rule: all domain operations are delegated to aiida-worker HTTP APIs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from loguru import logger

from src.aris_apps.aiida.client import (
    OFFLINE_WORKER_MESSAGE,
    BridgeAPIError,
    BridgeOfflineError,
    aiida_worker_client,
    format_bridge_error,
)
from src.aris_core.logging import log_event

_SCRIPT_ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "scripts"
_SCRIPT_ID_DATE_FMT = "%Y%m%d"
_SCRIPT_ID_PREFIX = "script_"
_SCRIPT_PK_TOKEN_PATTERN = re.compile(r"\b(?:pk|node|process)\s*#?\s*(\d+)\b", re.IGNORECASE)
_SCRIPT_PK_HASH_PATTERN = re.compile(r"#(\d+)\b")
_MODULE_NOT_FOUND_PATTERN = re.compile(
    r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            parsed = int(cleaned)
            return parsed if parsed > 0 else None
    return None


def _normalize_nodes_involved(nodes_involved: Any) -> list[int]:
    if nodes_involved is None:
        return []
    if isinstance(nodes_involved, str):
        candidates: list[Any] = [part.strip() for part in nodes_involved.split(",")]
    elif isinstance(nodes_involved, (list, tuple, set)):
        candidates = list(nodes_involved)
    else:
        candidates = [nodes_involved]

    deduped: list[int] = []
    seen: set[int] = set()
    for value in candidates:
        parsed = _coerce_positive_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        deduped.append(parsed)
    return deduped


def _extract_missing_module_name(error_text: str) -> str | None:
    match = _MODULE_NOT_FOUND_PATTERN.search(str(error_text or ""))
    if match:
        return match.group(1).strip() or None
    return None


def _summarize_worker_error(error_text: str) -> str:
    raw = str(error_text or "").strip()
    if not raw:
        return "Worker script execution failed"

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return "Worker script execution failed"

    if any("traceback" in line.lower() for line in lines):
        for line in reversed(lines):
            lowered = line.lower()
            if lowered.startswith("traceback"):
                continue
            if line.startswith("File "):
                continue
            return line[:220]
        return lines[-1][:220]
    return lines[-1][:220]


def _ensure_script_archive_dir() -> Path | None:
    try:
        _SCRIPT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            log_event(
                "aiida.worker.script_archive.prepare_failed",
                error=str(exc)[:220],
                archive_dir=str(_SCRIPT_ARCHIVE_DIR),
            )
        )
        return None
    return _SCRIPT_ARCHIVE_DIR


def _build_next_script_id(archive_dir: Path, turn_id: int | None = None) -> str:
    date_fragment = datetime.now(timezone.utc).strftime(_SCRIPT_ID_DATE_FMT)
    normalized_turn = _coerce_positive_int(turn_id) or 1
    base = f"{_SCRIPT_ID_PREFIX}{date_fragment}_turn{normalized_turn}"
    version = 1
    while True:
        candidate = f"{base}_v{version}"
        if not (archive_dir / f"{candidate}.py").exists() and not (archive_dir / f"{candidate}.json").exists():
            return candidate
        version += 1


def _write_script_metadata(metadata_path: Path, payload: dict[str, Any]) -> None:
    metadata_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _archive_script_pending(
    script: str,
    *,
    intent: str | None = None,
    nodes_involved: list[int] | None = None,
    turn_id: int | None = None,
) -> tuple[str, Path, dict[str, Any]] | None:
    archive_dir = _ensure_script_archive_dir()
    if archive_dir is None:
        return None

    script_id = _build_next_script_id(archive_dir, turn_id=turn_id)
    script_path = archive_dir / f"{script_id}.py"
    metadata_path = archive_dir / f"{script_id}.json"
    normalized_nodes = _normalize_nodes_involved(nodes_involved)
    metadata: dict[str, Any] = {
        "script_id": script_id,
        "timestamp": _utc_timestamp(),
        "intent": str(intent).strip() if isinstance(intent, str) and intent.strip() else "ad-hoc worker script",
        "nodes_involved": normalized_nodes,
        "status": "pending",
        "error_message": None,
        "missing_module": None,
        "created_pks": [],
        "turn_index": _coerce_positive_int(turn_id),
    }

    try:
        script_path.write_text(script, encoding="utf-8")
        _write_script_metadata(metadata_path, metadata)
    except OSError as exc:
        logger.warning(
            log_event(
                "aiida.worker.script_archive.write_failed",
                error=str(exc)[:220],
                script_id=script_id,
            )
        )
        return None

    logger.info(
        log_event(
            "aiida.worker.script_archive.pending_saved",
            script_id=script_id,
            nodes=len(normalized_nodes),
            intent=metadata["intent"][:120],
        )
    )
    return script_id, metadata_path, metadata


def _extract_created_pks(payload: Any, output_text: str = "") -> list[int]:
    found: set[int] = set()
    scalar_pk_keys = {
        "pk",
        "node_pk",
        "process_pk",
        "workflow_pk",
        "submitted_pk",
        "created_pk",
    }
    list_pk_keys = {
        "pks",
        "node_pks",
        "process_pks",
        "workflow_pks",
        "submitted_pks",
        "created_pks",
        "new_pks",
    }

    def _collect(value: Any, key_hint: str | None = None) -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                lowered = str(nested_key).strip().lower()
                if lowered in scalar_pk_keys:
                    parsed = _coerce_positive_int(nested_value)
                    if parsed is not None:
                        found.add(parsed)
                elif lowered in list_pk_keys and isinstance(nested_value, list):
                    for item in nested_value:
                        parsed = _coerce_positive_int(item)
                        if parsed is not None:
                            found.add(parsed)
                _collect(nested_value, key_hint=lowered)
            return

        if isinstance(value, list):
            for item in value:
                _collect(item, key_hint=key_hint)
            return

        if key_hint in scalar_pk_keys | list_pk_keys:
            parsed = _coerce_positive_int(value)
            if parsed is not None:
                found.add(parsed)

    _collect(payload)

    text = str(output_text or "")
    for pattern in (_SCRIPT_PK_TOKEN_PATTERN, _SCRIPT_PK_HASH_PATTERN):
        for match in pattern.finditer(text):
            parsed = _coerce_positive_int(match.group(1))
            if parsed is not None:
                found.add(parsed)

    return sorted(found)


def _archive_script_finalize(
    archive_entry: tuple[str, Path, dict[str, Any]] | None,
    *,
    status: str,
    error_message: str | None = None,
    created_pks: list[int] | None = None,
    missing_module: str | None = None,
) -> None:
    if archive_entry is None:
        return

    script_id, metadata_path, metadata = archive_entry
    metadata["status"] = status
    metadata["updated_at"] = _utc_timestamp()
    metadata["error_message"] = (error_message or None)
    metadata["missing_module"] = (missing_module or None)
    metadata["created_pks"] = sorted(set(_normalize_nodes_involved(created_pks)))
    try:
        _write_script_metadata(metadata_path, metadata)
    except OSError as exc:
        logger.warning(
            log_event(
                "aiida.worker.script_archive.finalize_failed",
                script_id=script_id,
                error=str(exc)[:220],
            )
        )
        return

    logger.info(
        log_event(
            "aiida.worker.script_archive.finalized",
            script_id=script_id,
            status=status,
            created_pks=len(metadata["created_pks"]),
        )
    )


async def request_json(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any:
    """Tool-side worker JSON helper backed by unified singleton client."""
    retry_budget = 2 if method.upper() == "GET" else 0
    return await aiida_worker_client.request_json(
        method,
        path,
        params=params,
        json=json,
        context=context,
        timeout=timeout,
        retries=retry_budget,
    )


def request_json_sync(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> Any:
    """Sync JSON helper for startup-time bridge calls."""
    retry_budget = 2 if retries is None and method.upper() == "GET" else retries
    return aiida_worker_client.request_json_sync(
        method,
        path,
        params=params,
        json=json,
        context=context,
        timeout=timeout,
        retries=retry_budget,
    )


async def list_system_profiles() -> dict[str, Any] | str:
    """List configured profiles from the worker (`GET /management/profiles`)."""
    try:
        payload = await request_json("GET", "/management/profiles")
        return payload if isinstance(payload, dict) else {"profiles": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def list_local_archives(path: str = ".") -> list[str] | dict[str, Any] | str:
    """List local `.aiida`/`.zip` archives visible to worker (`GET /management/archives/local`)."""
    try:
        payload = await request_json("GET", "/management/archives/local", params={"path": path})
        if isinstance(payload, dict):
            archives = payload.get("archives")
            return archives if isinstance(archives, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def switch_profile(profile: str) -> dict[str, Any] | str:
    """Switch active profile in worker (`POST /management/profiles/switch`)."""
    try:
        payload = await request_json("POST", "/management/profiles/switch", json={"profile": profile})
        return payload if isinstance(payload, dict) else {"status": "switched", "result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def load_archive_profile(filepath: str) -> dict[str, Any] | str:
    """Load an archive-backed profile in worker (`POST /management/profiles/load-archive`)."""
    try:
        payload = await request_json("POST", "/management/profiles/load-archive", json={"path": filepath})
        return payload if isinstance(payload, dict) else {"status": "loaded", "result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_unified_source_map(target: str | None = None) -> dict[str, Any] | str:
    """Build profile/archive group map from worker (`GET /management/source-map`)."""
    params = {"target": target} if target else None
    try:
        payload = await request_json("GET", "/management/source-map", params=params)
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_statistics(profile_name: str | None = None) -> dict[str, Any] | str:
    """Get consolidated infra/db statistics from worker (`GET /management/statistics`)."""
    if profile_name:
        switched = await switch_profile(profile_name)
        if isinstance(switched, str):
            return switched
        if isinstance(switched, dict) and switched.get("error"):
            return switched

    try:
        payload = await request_json("GET", "/management/statistics")
        return payload if isinstance(payload, dict) else {"statistics": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def list_groups(search_string: str | None = None) -> list[dict[str, Any]] | dict[str, Any] | str:
    """List groups from worker (`GET /management/groups`) with optional filter."""
    params = {"search": search_string} if search_string else None
    try:
        payload = await request_json("GET", "/management/groups", params=params)
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_database_summary() -> dict[str, Any] | str:
    """Get compact DB health summary (`GET /management/database/summary`)."""
    try:
        payload = await request_json("GET", "/management/database/summary")
        return payload if isinstance(payload, dict) else {"summary": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_recent_processes(limit: int = 5) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Fetch recent processes (`GET /management/recent-processes`)."""
    try:
        payload = await request_json("GET", "/management/recent-processes", params={"limit": int(limit)})
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def list_group_labels(search_string: str | None = None) -> list[str] | dict[str, Any] | str:
    """List group labels for dropdowns (`GET /management/groups/labels`)."""
    params = {"search": search_string} if search_string else None
    try:
        payload = await request_json("GET", "/management/groups/labels", params=params)
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_recent_nodes(
    limit: int = 15,
    group_label: str | None = None,
    node_type: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Fetch recent nodes (`GET /management/recent-nodes`) with optional filters."""
    params: dict[str, Any] = {"limit": int(limit)}
    if group_label:
        params["group_label"] = group_label
    if node_type:
        params["node_type"] = node_type

    try:
        payload = await request_json("GET", "/management/recent-nodes", params=params)
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def inspect_group(group_name: str, limit: int = 20) -> dict[str, Any] | str:
    """Inspect one group (`GET /management/groups/{group_name}`) with node attributes/extras."""
    try:
        payload = await request_json(
            "GET",
            f"/management/groups/{group_name}",
            params={"limit": int(limit)},
        )
        return payload if isinstance(payload, dict) else {"group": group_name, "result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def fetch_group_nodes(group_name: str, limit: int = 100) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Return up to `limit` serialized nodes in a group."""
    result = await inspect_group(group_name, limit=limit)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        nodes = result.get("nodes")
        return nodes if isinstance(nodes, list) else result
    return result


async def fetch_group_processes(
    group_label: str,
    limit: int = 20,
    exclude_import: bool = True,  # noqa: ARG001
) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Fetch recent process-like nodes constrained to a group (`GET /management/recent-nodes`)."""
    try:
        payload = await request_json(
            "GET",
            "/management/recent-nodes",
            params={"limit": int(limit), "group_label": group_label, "node_type": "WorkChainNode"},
        )
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def create_group(group_label: str) -> dict[str, Any] | str:
    """Create-group helper placeholder (not yet exposed by worker API)."""
    return {
        "error": "Group creation is not exposed by the current AiiDA Worker API.",
        "group_label": group_label,
    }


async def inspect_process(identifier: str) -> dict[str, Any] | str:
    """Inspect any ProcessNode by PK/UUID (`GET /process/{identifier}`)."""
    try:
        payload = await request_json("GET", f"/process/{identifier}")
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_process_log(pk: int) -> dict[str, Any] | str:
    """Fetch merged reports/stderr for one process (`GET /process/{pk}/logs`)."""
    try:
        payload = await request_json("GET", f"/process/{int(pk)}/logs")
        return payload if isinstance(payload, dict) else {"logs": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def fetch_recent_processes(limit: int = 15) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Fetch recent processes for quick status snapshots."""
    try:
        payload = await request_json("GET", "/management/recent-processes", params={"limit": int(limit)})
        if isinstance(payload, dict):
            items = payload.get("items")
            return items if isinstance(items, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


def _normalize_plugins_payload(payload: Any) -> list[str]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("plugins"), list):
            values = payload["plugins"]
        elif isinstance(payload.get("items"), list):
            values = payload["items"]
        else:
            values = []
    else:
        values = []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return sorted(normalized)


async def list_remote_plugins() -> list[str] | str:
    """Source of truth for available WorkChains (`GET /plugins`)."""
    try:
        payload = await request_json("GET", "/plugins")
        return _normalize_plugins_payload(payload)
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_remote_workchain_spec(entry_point: str) -> dict[str, Any] | str:
    """Fetch WorkChain input spec (`GET /submission/spec/{entry_point}`)."""
    cleaned = (entry_point or "").strip()
    if not cleaned:
        return "Please provide a valid WorkChain entry point name."

    try:
        payload = await request_json("GET", f"/submission/spec/{quote(cleaned, safe='')}")
        return payload if isinstance(payload, dict) else {"spec": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def inspect_lab_infrastructure() -> dict[str, Any] | str:
    """Inspect worker profile/daemon/computers/codes before submission."""
    try:
        return await aiida_worker_client.inspect_infrastructure()
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def inspect_workchain_spec(entry_point_name: str):
    """Inspect WorkChain spec via bridge (`GET /submission/spec/{entry_point}`)."""
    return await get_remote_workchain_spec(entry_point_name)


async def draft_workchain_builder(
    workchain_label: str,
    structure_pk: int,
    code_label: str,
    protocol: str = "moderate",
    overrides: dict[str, Any] | None = None,
    protocol_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    """Request builder draft creation (`POST /submission/draft-builder`)."""
    intent_data: dict[str, Any] = {
        "structure_pk": int(structure_pk),
        "code": code_label,
    }
    if protocol_kwargs:
        intent_data.update(protocol_kwargs)
    body = {
        "entry_point": workchain_label,
        "protocol": protocol,
        "intent_data": intent_data,
        "overrides": overrides or {},
    }

    try:
        payload = await request_json("POST", "/submission/draft-builder", json=body)
        return payload if isinstance(payload, dict) else {"draft": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def submit_workchain_builder(
    draft_data: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | str:
    """Submit one or many previously drafted builders (`POST /submission/submit`)."""
    try:
        payload = await request_json("POST", "/submission/submit", json={"draft": draft_data})
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def validate_workchain_builder(draft_data: dict[str, Any]) -> dict[str, Any] | str:
    """Validate a previously drafted builder (`POST /submission/validate`)."""
    try:
        payload = await request_json("POST", "/submission/validate", json={"draft": draft_data})
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def validate_job(draft_data: dict[str, Any]) -> dict[str, Any] | str:
    """Consistent validation interface for agents."""
    return await validate_workchain_builder(draft_data)


async def submit_job(
    draft_data: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | str:
    """Consistent submission interface for agents (single or batch)."""
    return await submit_workchain_builder(draft_data)


async def submit_workflow(
    draft_data: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | str:
    """Consistent submission interface for agents (single or batch)."""
    return await submit_job(draft_data)


async def run_python_code(
    script: str,
    *,
    intent: str | None = None,
    nodes_involved: list[int] | None = None,
    turn_id: int | None = None,
) -> str | dict[str, Any]:
    """Execute ad-hoc Python/AiiDA logic on worker (`POST /management/run-python`)."""
    _ = intent
    _ = nodes_involved
    _ = turn_id
    try:
        # Custom worker scripts can be substantially slower than regular bridge calls.
        payload = await request_json(
            "POST",
            "/management/run-python",
            json={"script_content": script},
            timeout=180.0,
        )
        if isinstance(payload, dict):
            if payload.get("success"):
                output_text = str(payload.get("output") or "Code executed successfully (No output).")
                created_pks = _extract_created_pks(payload, output_text)
                logger.info(
                    log_event(
                        "aiida.worker.run_python.completed",
                        success=True,
                        output_chars=len(output_text),
                        created_pks=",".join(str(pk) for pk in created_pks) or None,
                    )
                )
                return output_text
            output_text = str(payload.get("output") or "")
            error_text = str(payload.get("error") or "Worker script execution failed")
            missing_module = _extract_missing_module_name(error_text)
            created_pks = _extract_created_pks(payload, output_text)
            error_for_log = _summarize_worker_error(error_text)
            logger.warning(
                log_event(
                    "aiida.worker.run_python.completed",
                    success=False,
                    error=error_for_log,
                    output_chars=len(output_text),
                    created_pks=",".join(str(pk) for pk in created_pks) or None,
                    missing_module=missing_module,
                )
            )
            response: dict[str, Any] = {
                "error": error_text,
                "output": output_text,
            }
            if missing_module:
                response["missing_module"] = missing_module
                response["hint"] = (
                    "Worker environment is missing this Python module. "
                    "Avoid importing it in custom scripts or install it in aiida-worker."
                )
            return response
        payload_text = str(payload)
        created_pks = _extract_created_pks(payload, payload_text)
        return payload_text
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


def _normalize_skill_registry_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            normalized_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                normalized_items.append(
                    {
                        "name": name,
                        "description": item.get("description"),
                        "entrypoint": item.get("entrypoint"),
                        "updated_at": item.get("updated_at"),
                        "path": item.get("path"),
                    }
                )
            return {"count": len(normalized_items), "items": normalized_items}
    return {"count": 0, "items": []}


async def list_registered_skills() -> dict[str, Any] | str:
    """List persistent worker-side specialized scripts (`GET /registry/list`)."""
    try:
        payload = await request_json("GET", "/registry/list")
        return _normalize_skill_registry_payload(payload)
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


def list_registered_skills_sync() -> dict[str, Any]:
    """Synchronous variant for startup-time skill discovery."""
    try:
        payload = request_json_sync("GET", "/registry/list", timeout=6.0, retries=1)
        return _normalize_skill_registry_payload(payload)
    except BridgeAPIError as exc:
        if int(exc.status_code or 0) == 404:
            return {"count": 0, "items": []}
        logger.warning(log_event("aiida.worker.registry.list.failed", error=str(exc)[:220]))
        return {"count": 0, "items": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning(log_event("aiida.worker.registry.list.failed", error=str(exc)[:220]))
        return {"count": 0, "items": []}


async def register_specialized_skill(
    skill_name: str,
    script: str,
    *,
    description: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any] | str:
    """Persist a specialized skill script on worker (`POST /registry/register`)."""
    body = {
        "script_name": str(skill_name or "").strip(),
        "script": script,
        "description": description,
        "overwrite": bool(overwrite),
    }
    try:
        payload = await request_json("POST", "/registry/register", json=body, timeout=30.0)
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def execute_specialized_skill(skill_name: str, args: Mapping[str, Any] | None = None) -> dict[str, Any] | str:
    """Execute one registered worker-side skill (`POST /execute/{skill_name}`)."""
    cleaned = str(skill_name or "").strip()
    if not cleaned:
        return {"error": "Skill name is required."}
    try:
        payload = await request_json(
            "POST",
            f"/execute/{quote(cleaned, safe='')}",
            json={"params": dict(args or {})},
            timeout=180.0,
        )
        return payload if isinstance(payload, dict) else {"result": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_bands_plot_data(pk: int) -> dict[str, Any] | str:
    """Retrieve plot-ready bands payload from worker (`GET /data/bands/{pk}`)."""
    try:
        payload = await request_json("GET", f"/data/bands/{int(pk)}")
        return payload if isinstance(payload, dict) else {"data": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def list_remote_files(pk: int | str) -> list[str] | dict[str, Any] | str:
    """List files in a RemoteData node (`GET /data/remote/{pk}/files`)."""
    try:
        payload = await request_json("GET", f"/data/remote/{pk}/files")
        if isinstance(payload, dict):
            files = payload.get("files")
            return files if isinstance(files, list) else payload
        return payload
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_remote_file_content(pk: int | str, filename: str) -> str | dict[str, Any]:
    """Read one file from RemoteData (`GET /data/remote/{pk}/files/{filename}`)."""
    try:
        payload = await request_json("GET", f"/data/remote/{pk}/files/{filename}")
        if isinstance(payload, dict):
            content = payload.get("content")
            return str(content) if isinstance(content, str) else payload
        return str(payload)
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_node_file_content(pk: int | str, filename: str, source: str = "folder") -> str | dict[str, Any]:
    """Read text content from node storage (`GET /data/repository/{pk}/files/{filename}`)."""
    try:
        payload = await request_json(
            "GET",
            f"/data/repository/{pk}/files/{filename}",
            params={"source": source},
        )
        if isinstance(payload, dict):
            content = payload.get("content")
            return str(content) if isinstance(content, str) else payload
        return str(payload)
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


async def get_node_summary(node_pk: int) -> dict[str, Any] | str:
    """Return a structured node summary from worker bridge for reasoning/UI use."""
    try:
        payload = await request_json("GET", f"/management/nodes/{int(node_pk)}")
        return payload if isinstance(payload, dict) else {"data": payload}
    except BridgeOfflineError:
        return OFFLINE_WORKER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        return format_bridge_error(exc)


__all__ = [
    "list_system_profiles",
    "list_local_archives",
    "switch_profile",
    "load_archive_profile",
    "get_statistics",
    "list_groups",
    "get_unified_source_map",
    "get_database_summary",
    "get_recent_processes",
    "list_group_labels",
    "get_recent_nodes",
    "inspect_group",
    "fetch_group_nodes",
    "fetch_group_processes",
    "create_group",
    "inspect_process",
    "get_process_log",
    "fetch_recent_processes",
    "inspect_workchain_spec",
    "list_remote_plugins",
    "get_remote_workchain_spec",
    "inspect_lab_infrastructure",
    "draft_workchain_builder",
    "validate_workchain_builder",
    "validate_job",
    "submit_workchain_builder",
    "submit_job",
    "submit_workflow",
    "run_python_code",
    "list_registered_skills",
    "list_registered_skills_sync",
    "register_specialized_skill",
    "execute_specialized_skill",
    "get_bands_plot_data",
    "list_remote_files",
    "get_remote_file_content",
    "get_node_file_content",
    "get_node_summary",
]
