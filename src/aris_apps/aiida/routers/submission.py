from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from statistics import median
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from ag_ui.core import RunErrorEvent, RunStartedEvent
from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as ApiPath, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from google import genai
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from src.aris_core.config import settings
from ..config import aiida_engine_settings
from src.aris_core.logging import get_log_buffer_snapshot, log_event
from src.aris_core.policy import AuthorizationDecision
from src.aris_core.schema.approval import (
    build_submission_approval_request,
    resolve_submission_approval,
)
from src.aris_core.schema.ui_event import (
    build_ag_ui_sse_event,
    build_ag_ui_state_snapshot,
)
from .frontend import _build_active_submission_group_labels

from ..chat import (
    activate_chat_session,
    build_chat_project_worker_context,
    cancel_chat_turn,
    create_chat_project,
    update_chat_project,
    create_chat_session,
    delete_chat_items,
    describe_chat_project_file,
    get_active_chat_project_id,
    get_active_chat_session_id,
    get_chat_history,
    get_chat_session_detail,
    get_chat_session_batch_progress,
    get_chat_session_workspace_path,
    get_chat_snapshot,
    list_chat_projects,
    list_chat_project_workspace_files,
    list_chat_session_workspace_files,
    list_chat_sessions,
    normalize_context_node_ids,
    serialize_chat_history,
    start_chat_turn,
    update_chat_session,
    write_chat_project_file,
)
from ..authorization import local_authorization_snapshot, require_permission
from ..capabilities import aiida_capability
from ..client import (
    WorkerRPCError,
    WorkerOfflineError,
    aiida_worker_client,
    import_worker_data,
    reset_worker_request_context,
    optional_worker_call,
    worker_call,
    set_worker_request_context,
)
from ..presenters.node_view import (
    attach_tree_links as _attach_tree_links,
    enrich_process_detail_payload as _enrich_process_detail_payload,
    extract_folder_preview as _extract_folder_preview,
    serialize_groups as _serialize_groups,
    serialize_processes as _serialize_processes,
    extract_node_hover_metadata as _extract_node_hover_metadata,
    _coerce_chat_metadata,
)
from ..presenters.workflow_view import (
    extract_submitted_pk as _extract_submitted_pk,
    enrich_submission_draft_payload,
    format_single_submission_response,
    format_worker_batch_submission_response,
)
from ..service import (
    add_nodes_to_group,
    create_group,
    delete_group,
    export_group_archive,
    get_context_nodes,
    get_recent_nodes,
    list_groups,
    rename_group,
    soft_delete_node,
    hub,
    parse_infrastructure_via_ai as _parse_infrastructure_via_ai,
)
from ..specializations import build_active_specializations_payload
from ..infrastructure_manager import infrastructure_manager
from ..schemas import (
    EnvironmentInspectRequest,
    FrontendChatRequest,
    FrontendStopChatRequest,
    FrontendChatDeleteRequest,
    FrontendChatProjectFileExecuteRequest,
    FrontendChatProjectFileExecuteResponse,
    FrontendChatProjectFileReadResponse,
    FrontendChatProjectFileWriteRequest,
    FrontendChatProjectFileWriteResponse,
    FrontendChatProjectCreateRequest,
    FrontendChatProjectUpdateRequest,
    FrontendChatSessionCreateRequest,
    FrontendChatSessionTitleUpdateRequest,
    FrontendChatSessionUpdateRequest,
    SubmissionApprovalCancelRequest,
    SubmissionDraftRequest,
    SubmissionReviewRequest,
    SystemCountsResponse,
    WorkerStatusResponse,
    WorkerSystemInfoResponse,
    WorkerResourcesResponse,
    WorkerProfilesResponse,
    WorkerSwitchProfileRequest,
    WorkerSwitchProfileResponse,
    FrontendGroupCreateRequest,
    FrontendGroupRenameRequest,
    FrontendGroupAssignNodesRequest,
    FrontendNodeSoftDeleteRequest,
    NodeHoverMetadataResponse,
    NodeScriptResponse,
    InfrastructureComputer,
    InfrastructureCapabilitiesResponse,
    InfrastructureExportResponse,
    ComputeHealthEstimateResponse,
    ComputeHealthQueueSnapshot,
    ComputeHealthResponse,
    ParseInfrastructureRequest,
    ProcessDiagnosticsExcerpt,
    ProcessDiagnosticsResponse,
    UserInfoResponse,
    ProfileSetupRequest,
    CodeSetupRequest,
    CodeDetailedResponse,
)

FRONTEND_TAG = "AiiDA-Frontend-API"
WORKER_PROXY_TAG = "AiiDA-Worker-Proxy"

router = APIRouter()
DEFAULT_MODELS = [settings.DEFAULT_MODEL]
ARCHIVE_EXTENSIONS = {".aiida", ".zip"}
QUEUE_CONGESTION_THRESHOLD = 1000
ESTIMATE_HISTORY_LIMIT = 240
ESTIMATE_MATCH_LIMIT = 12
DIAGNOSTIC_STDOUT_TAIL_LIMIT = 100
WORKER_JSON_MARKER = "__ARIS_JSON__:"
COMPUTE_HEALTH_REFERENCE_TIMEOUT_SECONDS = 3.0
COMPUTE_HEALTH_INFRA_TIMEOUT_SECONDS = 2.5
COMPUTE_HEALTH_SCHEDULER_TIMEOUT_SECONDS = 12.0
STDOUT_CANDIDATE_FILENAMES = (
    "aiida.out",
    "stdout",
    "stdout.txt",
    "_scheduler-stdout.txt",
    "scheduler.stdout",
    "scheduler-stdout.txt",
)
STDERR_CANDIDATE_FILENAMES = (
    "scheduler.stderr",
    "_scheduler-stderr.txt",
    "stderr",
    "stderr.txt",
)
PENDING_SUBMISSION_KEY = "aiida_pending_submission"


def _get_quick_prompts() -> list[dict[str, str]]:
    """Load quick prompts from external settings file."""
    try:
        settings_path = aiida_engine_settings.settings_file
        if not os.path.exists(settings_path):
            return []
        with open(settings_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            prompts = data.get("quick_prompts", [])
            return prompts if isinstance(prompts, list) else []
    except Exception as error:
        logger.warning(log_event("aiida.settings.load_failed", error=str(error)))
        return []


def _normalize_text_query_values(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        text = str(raw_value or "").strip()
        if not text:
            continue
        for part in text.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(candidate)
    return normalized




def _get_node_hover_metadata(pk: int) -> NodeHoverMetadataResponse:
    if not hub.current_profile:
        hub.start()

    try:
        nodes = get_context_nodes([pk])
    except Exception as error:  # noqa: BLE001
        logger.warning(log_event("aiida.frontend.node_metadata.failed", pk=pk, error=str(error)))
        return NodeHoverMetadataResponse(pk=pk)

    matched: dict[str, Any] | None = None
    for entry in nodes:
        if not isinstance(entry, dict):
            continue
        try:
            entry_pk = int(str(entry.get("pk", "")).strip())
        except (TypeError, ValueError):
            entry_pk = None
        if entry_pk == pk:
            matched = entry
            break
        if matched is None:
            matched = entry

    if not matched:
        return NodeHoverMetadataResponse(pk=pk)

    return _extract_node_hover_metadata(matched, pk)




def _sanitize_upload_name(filename: str) -> str:
    safe = Path(filename).name.replace(" ", "_")
    return "".join(ch for ch in safe if ch.isalnum() or ch in {"-", "_", "."}) or "archive.aiida"


def _clear_pending_submission_memory(state: Any) -> None:
    memory = getattr(state, "memory", None)
    if memory is None:
        return
    setter = getattr(memory, "set_kv", None)
    if not callable(setter):
        return
    try:
        setter(PENDING_SUBMISSION_KEY, None)
    except Exception as error:  # noqa: BLE001
        logger.warning(log_event("aiida.frontend.pending_submission.clear_failed", error=str(error)))


def _get_frontend_groups() -> list[dict[str, Any]]:
    if not hub.current_profile:
        hub.start()
    return list_groups()


async def _get_frontend_groups_async() -> list[dict[str, Any]]:
    payload = await aiida_worker_client.call("group.list")
    return payload.get("items", []) if isinstance(payload, dict) else []


def _get_frontend_nodes(
    limit: int = 15,
    group_label: str | None = None,
    node_type: str | None = None,
    *,
    root_only: bool = True,
) -> list[dict[str, Any]]:
    if not hub.current_profile:
        hub.start()
    return get_recent_nodes(limit=limit, group_label=group_label, node_type=node_type, root_only=root_only)






def _coerce_text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_float_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_lookup_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _extract_preview_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    candidate = payload.get("preview_info")
    if isinstance(candidate, dict):
        return candidate
    return {}


def _normalize_process_state_value(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("_", " ")


def _is_failed_process_state(value: Any) -> bool:
    return _normalize_process_state_value(value) in {"failed", "excepted", "killed", "error"}


def _split_output_lines(text: Any) -> list[str]:
    if text is None:
        return []
    if isinstance(text, list):
        return [str(item) for item in text]
    return str(text).splitlines()


def _tail_text_lines(text: Any, limit: int) -> str | None:
    lines = [line.rstrip("\n") for line in _split_output_lines(text)]
    if not lines:
        return None
    return "\n".join(lines[-limit:])


def _format_duration_compact(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    total_seconds = int(round(max(0.0, float(seconds))))
    if total_seconds < 60:
        return f"~{total_seconds} sec"
    if total_seconds < 3600:
        minutes = max(1, int(round(total_seconds / 60)))
        return f"~{minutes} mins"
    hours = total_seconds / 3600
    if hours < 10:
        return f"~{hours:.1f} hrs"
    return f"~{int(round(hours))} hrs"


def _format_estimate_display(seconds: float | None, num_machines: int | None = None) -> str | None:
    duration_label = _format_duration_compact(seconds)
    if not duration_label:
        return None
    if num_machines and num_machines > 0:
        node_label = "node" if num_machines == 1 else "nodes"
        return f"{duration_label} on {num_machines} {node_label}"
    return duration_label


def _find_named_value(payload: Any, *candidate_keys: str, max_depth: int = 5) -> Any:
    normalized_targets = {_normalize_lookup_key(key) for key in candidate_keys if key}
    if not normalized_targets:
        return None

    queue: list[tuple[Any, int]] = [(payload, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        if isinstance(current, dict):
            for key, value in current.items():
                if _normalize_lookup_key(str(key)) in normalized_targets:
                    return value
                queue.append((value, depth + 1))
        elif isinstance(current, list):
            for item in current:
                queue.append((item, depth + 1))
    return None


def _extract_duration_seconds(payload: dict[str, Any] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    preview = _extract_preview_mapping(payload)
    for container in (preview, payload, payload.get("summary") if isinstance(payload.get("summary"), dict) else None):
        if not isinstance(container, dict):
            continue
        for key in (
            "execution_time_seconds",
            "wall_time_seconds",
            "duration_seconds",
            "runtime_seconds",
            "elapsed_seconds",
            "duration",
            "elapsed",
        ):
            value = _coerce_float_value(container.get(key))
            if value is not None and value >= 0:
                return value
    return None


def _extract_computer_label(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    preview = _extract_preview_mapping(payload)
    for container in (
        preview,
        payload.get("summary") if isinstance(payload.get("summary"), dict) else None,
        payload,
    ):
        if not isinstance(container, dict):
            continue
        for key in ("computer_label", "computer_name", "computer", "machine_label", "hostname", "host"):
            value = container.get(key)
            if isinstance(value, dict):
                label = _coerce_text_value(value.get("label") or value.get("name") or value.get("computer_label"))
            else:
                label = _coerce_text_value(value)
            if label:
                return label
    nested = _find_named_value(payload, "computer_label", "computer_name", "machine_label", "hostname")
    return _coerce_text_value(nested)


def _extract_process_features(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    preview = _extract_preview_mapping(payload)
    return {
        "pk": _coerce_int_value(summary.get("pk") if isinstance(summary, dict) else payload.get("pk")),
        "process_label": _coerce_text_value(
            (summary.get("process_label") if isinstance(summary, dict) else None) or payload.get("process_label")
        ),
        "node_type": _coerce_text_value(
            (summary.get("node_type") if isinstance(summary, dict) else None)
            or (summary.get("type") if isinstance(summary, dict) else None)
            or payload.get("node_type")
            or payload.get("type")
        ),
        "computer_label": _extract_computer_label(payload),
        "atom_count": _coerce_int_value(_find_named_value(preview or payload, "atom_count", "num_atoms", "natoms", "sites_count")),
        "ecutwfc": _coerce_float_value(_find_named_value(payload, "ecutwfc")),
        "ecutrho": _coerce_float_value(_find_named_value(payload, "ecutrho")),
        "kpoints_distance": _coerce_float_value(
            _find_named_value(payload, "kpoints_distance", "kpoint_distance", "bands_kpoints_distance")
        ),
        "num_kpoints": _coerce_int_value(_find_named_value(preview or payload, "num_kpoints", "kpoints_count")),
        "num_bands": _coerce_int_value(_find_named_value(preview or payload, "num_bands", "nbands", "number_of_bands")),
        "num_machines": _coerce_int_value(
            _find_named_value(payload, "num_machines", "nodes", "num_nodes", "metadata_options_resources_num_machines")
        ),
        "runtime_seconds": _extract_duration_seconds(payload),
    }


def _string_similarity(left: str | None, right: str | None) -> float:
    left_text = _coerce_text_value(left)
    right_text = _coerce_text_value(right)
    if not left_text or not right_text:
        return 0.0
    normalized_left = left_text.lower()
    normalized_right = right_text.lower()
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.7
    left_tokens = {token for token in re.split(r"[\W_]+", normalized_left) if token}
    right_tokens = {token for token in re.split(r"[\W_]+", normalized_right) if token}
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    return len(intersection) / max(len(left_tokens), len(right_tokens))


def _numeric_similarity(reference: int | float | None, candidate: int | float | None) -> float:
    if reference is None or candidate is None:
        return 0.0
    denominator = max(abs(float(reference)), 1.0)
    relative_error = abs(float(candidate) - float(reference)) / denominator
    return max(0.0, 1.0 - relative_error)


def _score_runtime_match(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    score = 0.0
    score += 3.0 * _string_similarity(reference.get("computer_label"), candidate.get("computer_label"))
    score += 3.0 * _string_similarity(reference.get("process_label"), candidate.get("process_label"))
    score += 2.0 * _string_similarity(reference.get("node_type"), candidate.get("node_type"))
    score += 2.5 * _numeric_similarity(reference.get("atom_count"), candidate.get("atom_count"))
    score += 1.5 * _numeric_similarity(reference.get("ecutwfc"), candidate.get("ecutwfc"))
    score += 1.0 * _numeric_similarity(reference.get("ecutrho"), candidate.get("ecutrho"))
    score += 1.5 * _numeric_similarity(reference.get("kpoints_distance"), candidate.get("kpoints_distance"))
    score += 1.0 * _numeric_similarity(reference.get("num_kpoints"), candidate.get("num_kpoints"))
    score += 1.0 * _numeric_similarity(reference.get("num_bands"), candidate.get("num_bands"))
    score += 1.0 * _numeric_similarity(reference.get("num_machines"), candidate.get("num_machines"))
    return score


def _estimate_runtime_from_history(
    reference_features: dict[str, Any],
    *,
    computer_label: str | None = None,
    reference_process_pk: int | None = None,
) -> ComputeHealthEstimateResponse:
    if not reference_features:
        return ComputeHealthEstimateResponse()

    try:
        recent_nodes = _get_frontend_nodes(limit=ESTIMATE_HISTORY_LIMIT, root_only=False)
    except Exception as error:  # noqa: BLE001
        logger.warning(log_event("aiida.frontend.compute_health.history_failed", error=str(error)))
        return ComputeHealthEstimateResponse()

    scored_matches: list[tuple[float, float, dict[str, Any]]] = []
    for candidate in recent_nodes:
        if not isinstance(candidate, dict):
            continue
        candidate_pk = _coerce_int_value(candidate.get("pk"))
        if reference_process_pk is not None and candidate_pk == reference_process_pk:
            continue
        candidate_features = _extract_process_features(candidate)
        runtime_seconds = _coerce_float_value(candidate_features.get("runtime_seconds"))
        if runtime_seconds is None or runtime_seconds <= 0:
            continue
        if _is_failed_process_state(candidate.get("process_state") or candidate.get("state")):
            continue
        if computer_label:
            candidate_computer = _coerce_text_value(candidate_features.get("computer_label"))
            if candidate_computer and candidate_computer != computer_label:
                continue
        score = _score_runtime_match(reference_features, candidate_features)
        if score < 2.0:
            continue
        scored_matches.append((score, runtime_seconds, candidate_features))

    if not scored_matches:
        return ComputeHealthEstimateResponse()

    scored_matches.sort(key=lambda item: item[0], reverse=True)
    top_matches = scored_matches[:ESTIMATE_MATCH_LIMIT]
    weighted_runtime = sum(score * runtime for score, runtime, _ in top_matches) / sum(score for score, _, _ in top_matches)
    num_machine_votes = [
        _coerce_int_value(features.get("num_machines"))
        for _, _, features in top_matches
        if _coerce_int_value(features.get("num_machines"))
    ]
    reference_num_machines = _coerce_int_value(reference_features.get("num_machines"))
    resolved_num_machines = reference_num_machines
    if resolved_num_machines is None and num_machine_votes:
        try:
            resolved_num_machines = int(round(median(num_machine_votes)))
        except Exception:  # noqa: BLE001
            resolved_num_machines = num_machine_votes[0]
    matched_process_label = _coerce_text_value(reference_features.get("process_label")) or _coerce_text_value(
        top_matches[0][2].get("process_label")
    )
    return ComputeHealthEstimateResponse(
        available=True,
        duration_seconds=weighted_runtime,
        display=_format_estimate_display(weighted_runtime, resolved_num_machines),
        num_machines=resolved_num_machines,
        sample_size=len(top_matches),
        basis="Historical runs matched by computer, workflow, and task scale",
        matched_process_label=matched_process_label,
    )


def _parse_worker_json_output(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    output_text = _coerce_text_value(payload.get("output"))
    if not output_text:
        return None
    for line in reversed(output_text.splitlines()):
        cleaned_line = line.strip()
        if not cleaned_line.startswith(WORKER_JSON_MARKER):
            continue
        raw_json = cleaned_line[len(WORKER_JSON_MARKER):].strip()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None






async def _resolve_compute_health_computer_label(
    *,
    explicit_computer_label: str | None = None,
    reference_features: dict[str, Any] | None = None,
) -> str | None:
    if explicit_computer_label:
        return explicit_computer_label
    reference_label = _coerce_text_value((reference_features or {}).get("computer_label"))
    if reference_label:
        return reference_label
    try:
        computers = await asyncio.wait_for(
            aiida_worker_client.inspect_infrastructure_v2(),
            timeout=COMPUTE_HEALTH_INFRA_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(log_event("aiida.frontend.compute_health.infrastructure_timeout"))
        return None
    except Exception as error:  # noqa: BLE001
        logger.warning(log_event("aiida.frontend.compute_health.infrastructure_failed", error=str(error)))
        return None
    if not isinstance(computers, list):
        return None
    enabled = [item for item in computers if isinstance(item, dict) and bool(item.get("is_enabled"))]
    for item in [*enabled, *computers]:
        if isinstance(item, dict):
            label = _coerce_text_value(item.get("label"))
            if label:
                return label
    return None


def _build_scheduler_probe_script(computer_label: str | None) -> str:
    target_literal = json.dumps(computer_label)
    return f"""
import json

payload = {{
    "available": False,
    "computer_label": {target_literal},
    "scheduler_type": None,
    "queue": {{"running": 0, "pending": 0, "queued": 0, "total": 0}},
}}

def _state_name(job):
    raw_state = getattr(job, "job_state", None)
    if raw_state is None:
        return ""
    value = getattr(raw_state, "value", raw_state)
    return str(value).strip().lower()

def _computer_is_ready(computer, user):
    try:
        return bool(computer.is_user_configured(user))
    except Exception:
        return False

try:
    from aiida import load_profile
    from aiida.orm import Computer, QueryBuilder, User, load_computer

    selected = None
    load_profile()
    default_user = User.collection.get_default()
    qb = QueryBuilder()
    qb.append(Computer, project=["label"])
    computer_rows = qb.all()
    if payload["computer_label"]:
        try:
            candidate = load_computer(payload["computer_label"])
            if _computer_is_ready(candidate, default_user):
                selected = candidate
            else:
                payload["error"] = (
                    f"Computer '{{candidate.label}}' is not configured for the current AiiDA user"
                )
        except Exception:
            payload["error"] = f"Unknown computer: {{payload['computer_label']}}"
    if selected is None and not payload["computer_label"]:
        configured_labels = []
        for row in computer_rows:
            if not row:
                continue
            try:
                candidate = load_computer(row[0])
            except Exception:
                continue
            if _computer_is_ready(candidate, default_user):
                configured_labels.append(candidate.label)
        fallback_labels = configured_labels or [row[0] for row in computer_rows if row]
        if fallback_labels:
            selected = load_computer(fallback_labels[0])
    if selected is None:
        if "error" not in payload:
            payload["error"] = "No configured AiiDA computer available"
    else:
        payload["computer_label"] = selected.label
        payload["scheduler_type"] = selected.scheduler_type
        with selected.get_transport() as transport:
            scheduler = selected.get_scheduler()
            scheduler.set_transport(transport)
            jobs = scheduler.get_jobs(as_dict=True) or {{}}
        running = 0
        pending = 0
        queued = 0
        job_iterable = jobs.values() if isinstance(jobs, dict) else (jobs or [])
        for job in job_iterable:
            state_name = _state_name(job)
            if any(token in state_name for token in ("run", "active", "exec")):
                running += 1
            elif any(token in state_name for token in ("hold", "suspend")):
                queued += 1
            elif any(token in state_name for token in ("pend", "wait", "queue")):
                pending += 1
            else:
                queued += 1
        payload["available"] = True
        payload["queue"] = {{
            "running": running,
            "pending": pending,
            "queued": queued,
            "total": running + pending + queued,
        }}
except Exception as exc:
    payload["error"] = f"{{type(exc).__name__}}: {{exc}}"

print("{WORKER_JSON_MARKER}" + json.dumps(payload, ensure_ascii=False))
""".strip()






def _normalize_link_mapping(raw: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw, dict):
        result: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = value
        return result
    return {}


def _select_process_output_link(
    detail: dict[str, Any],
    *,
    preferred_labels: tuple[str, ...] = (),
    node_types: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    label_targets = {label.lower() for label in preferred_labels}
    type_targets = {node_type.lower() for node_type in node_types}
    for block_name in ("direct_outputs", "outputs"):
        links = _normalize_link_mapping(detail.get(block_name))
        for port_name, link in links.items():
            link_label = _coerce_text_value(link.get("link_label") or port_name)
            node_type = _coerce_text_value(link.get("node_type"))
            if label_targets and link_label and link_label.lower() in label_targets:
                return link
            if type_targets and node_type and node_type.lower() in type_targets:
                return link
    return None


def _pick_candidate_filename(files: list[str], *, stderr: bool = False) -> str | None:
    normalized_files = [str(item).strip() for item in files if str(item).strip()]
    if not normalized_files:
        return None
    preferred = STDERR_CANDIDATE_FILENAMES if stderr else STDOUT_CANDIDATE_FILENAMES
    lowered = {item.lower(): item for item in normalized_files}
    for candidate in preferred:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    ranked = sorted(
        normalized_files,
        key=lambda name: (
            0 if ("stderr" in name.lower()) == stderr else 1,
            0 if ("stdout" in name.lower() or name.lower().endswith(".out")) and not stderr else 1,
            len(name),
        ),
    )
    return ranked[0] if ranked else None


async def _fetch_repository_excerpt(node_pk: int) -> ProcessDiagnosticsExcerpt:
    listing = await optional_worker_call("data.repository_files", {"pk": node_pk, "source": "folder"})
    files = []
    if isinstance(listing, dict):
        raw_files = listing.get("files")
        if isinstance(raw_files, list):
            files = [str(item.get("name") if isinstance(item, dict) else item).strip() for item in raw_files]
    filename = _pick_candidate_filename(files)
    if not filename:
        return ProcessDiagnosticsExcerpt(source="repository")
    content = await optional_worker_call(
        "data.repository_file",
        {"pk": node_pk, "filename": filename, "source": "folder"},
        timeout=20.0,
    )
    text = None
    if isinstance(content, dict):
        text = _tail_text_lines(content.get("content"), DIAGNOSTIC_STDOUT_TAIL_LIMIT)
    return ProcessDiagnosticsExcerpt(
        source="repository",
        filename=filename,
        line_count=len(_split_output_lines(text)),
        text=text,
    )


async def _fetch_remote_excerpt(node_pk: int) -> ProcessDiagnosticsExcerpt:
    listing = await optional_worker_call("data.remote_files", {"pk": node_pk})
    files = []
    if isinstance(listing, dict):
        raw_files = listing.get("files")
        if isinstance(raw_files, list):
            files = [str(item.get("name") if isinstance(item, dict) else item).strip() for item in raw_files]
    filename = _pick_candidate_filename(files)
    if not filename:
        return ProcessDiagnosticsExcerpt(source="remote")
    content = await optional_worker_call(
        "data.remote_file",
        {"pk": node_pk, "filename": filename},
        timeout=20.0,
    )
    text = None
    if isinstance(content, dict):
        text = _tail_text_lines(content.get("content"), DIAGNOSTIC_STDOUT_TAIL_LIMIT)
    return ProcessDiagnosticsExcerpt(
        source="remote",
        filename=filename,
        line_count=len(_split_output_lines(text)),
        text=text,
    )


def _build_log_excerpt(logs_payload: dict[str, Any] | None) -> ProcessDiagnosticsExcerpt:
    if not isinstance(logs_payload, dict):
        return ProcessDiagnosticsExcerpt(source="logs")
    lines = []
    raw_lines = logs_payload.get("lines")
    if isinstance(raw_lines, list):
        lines = [str(item) for item in raw_lines]
    if not lines:
        raw_reports = logs_payload.get("reports")
        if isinstance(raw_reports, list):
            lines = [str(item) for item in raw_reports]
    if not lines:
        text = _tail_text_lines(logs_payload.get("text"), DIAGNOSTIC_STDOUT_TAIL_LIMIT)
    else:
        text = "\n".join(lines[-DIAGNOSTIC_STDOUT_TAIL_LIMIT:])
    return ProcessDiagnosticsExcerpt(
        source="logs",
        line_count=len(_split_output_lines(text)),
        text=text,
    )








async def _ensure_named_groups(labels: list[str]) -> dict[str, str]:
    ensured: dict[str, str] = {}
    for raw_label in labels:
        cleaned_label = str(raw_label or "").strip()
        if not cleaned_label:
            continue
        await _ensure_submission_group(cleaned_label)
        ensured[cleaned_label] = cleaned_label
    return ensured






def _chat_delete_response(state: Any, deleted: dict[str, Any]) -> dict[str, Any]:
    snapshot = _chat_sessions_payload(state)
    return {
        **snapshot,
        "chat": get_chat_snapshot(state),
        "deleted_project_ids": deleted.get("deleted_project_ids") if isinstance(deleted, dict) else [],
        "deleted_session_ids": deleted.get("deleted_session_ids") if isinstance(deleted, dict) else [],
    }


def _build_submission_worker_context(state: Any) -> dict[str, str] | None:
    session_id = get_active_chat_session_id(state)
    if not session_id:
        return None

    active_project_id = get_active_chat_project_id(state)
    project_context = build_chat_project_worker_context(state, active_project_id or "")
    if project_context is None:
        return None
    return {**project_context, "session_id": session_id}


async def _ensure_submission_group(label: str) -> dict[str, Any] | None:
    cleaned_label = str(label or "").strip()
    if not cleaned_label:
        return None

    existing = next((group for group in list_groups() if str(group.get("label") or "").strip() == cleaned_label), None)
    if existing:
        return existing

    try:
        response = create_group(cleaned_label)
    except WorkerRPCError as exc:
        if int(exc.status_code or 0) != 409:
            raise
        response = {"item": next((group for group in list_groups() if str(group.get("label") or "").strip() == cleaned_label), None)}

    group_payload = response.get("item") if isinstance(response, dict) else None
    if isinstance(group_payload, dict):
        return group_payload

    return next((group for group in list_groups() if str(group.get("label") or "").strip() == cleaned_label), None)


async def _auto_assign_submission_groups(
    state: Any,
    submitted_pks: list[int],
) -> dict[str, str] | None:
    normalized_pks = sorted({int(pk) for pk in submitted_pks if isinstance(pk, int) and pk > 0})
    if not normalized_pks:
        return None

    labels = _build_active_submission_group_labels(state)
    if not labels:
        return None

    for label in (labels["project"], labels["session"]):
        group = await _ensure_submission_group(label)
        group_pk = int(group.get("pk") or 0) if isinstance(group, dict) else 0
        if group_pk <= 0:
            continue
        add_nodes_to_group(group_pk, normalized_pks)

    return labels


def _raise_worker_http_error(exc: Exception) -> None:
    if isinstance(exc, WorkerOfflineError):
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    if isinstance(exc, WorkerRPCError):
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc
    raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def _normalize_model_name(name: str) -> str:
    if name.startswith("models/"):
        return name.split("/", 1)[1]
    return name


def _fetch_genai_models() -> list[str]:
    api_key = settings.GEMINI_API_KEY
    if api_key == "your-key-here":
        api_key = None

    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": settings.GEMINI_API_VERSION})
    discovered: list[str] = []
    for model in client.models.list():
        model_name = _normalize_model_name(getattr(model, "name", "") or "")
        if not model_name.startswith("gemini"):
            continue

        supported_actions = getattr(model, "supported_actions", None) or []
        if supported_actions and "generateContent" not in supported_actions:
            continue

        discovered.append(model_name)

    return list(dict.fromkeys(discovered))






@router.get("/status", response_model=WorkerStatusResponse, tags=[WORKER_PROXY_TAG])
async def get_worker_status() -> WorkerStatusResponse:
    try:
        snapshot = await aiida_capability.get_status()
        return WorkerStatusResponse(
            status=snapshot.status,
            url=aiida_capability.transport_endpoint,
            environment=snapshot.environment,
            transport="stdio",
            worker_mode=snapshot.mode,
            profile=snapshot.profile,
            daemon_status=snapshot.daemon_status,
            resources=SystemCountsResponse(
                computers=snapshot.resources.computers,
                codes=snapshot.resources.codes,
                workchains=snapshot.resources.workchains,
            ),
            plugins=list(snapshot.plugins),
        )
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.status.failed", error=error_message))
        return WorkerStatusResponse(
            status="offline",
            url=aiida_capability.transport_endpoint,
            environment="Managed AiiDA runtime",
            transport="stdio",
            worker_mode=None,
            profile="unknown",
            daemon_status=False,
            resources=SystemCountsResponse(),
            plugins=[],
        )


@router.get("/plugins", response_model=list[str], tags=[WORKER_PROXY_TAG])
async def get_bridge_plugins() -> list[str]:
    try:
        return await aiida_capability.get_plugins()
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.plugins.failed", error=error_message))
        return []


@router.get("/system", response_model=WorkerSystemInfoResponse, tags=[WORKER_PROXY_TAG])
async def get_bridge_system_info() -> WorkerSystemInfoResponse:
    try:
        snapshot = await aiida_capability.get_status()
        return WorkerSystemInfoResponse(
            profile=snapshot.profile,
            counts=SystemCountsResponse(
                computers=snapshot.resources.computers,
                codes=snapshot.resources.codes,
                workchains=snapshot.resources.workchains,
            ),
            daemon_status=snapshot.daemon_status,
        )
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.system.failed", error=error_message))
        return WorkerSystemInfoResponse()


@router.get("/resources", response_model=WorkerResourcesResponse, tags=[WORKER_PROXY_TAG])
async def get_bridge_resources() -> WorkerResourcesResponse:
    try:
        payload = await aiida_capability.get_resources()
        return WorkerResourcesResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.resources.failed", error=error_message))
        return WorkerResourcesResponse()


@router.get("/profiles", response_model=WorkerProfilesResponse, tags=[WORKER_PROXY_TAG])
async def get_bridge_profiles() -> WorkerProfilesResponse:
    try:
        payload = await aiida_capability.get_profiles()
        return WorkerProfilesResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.profiles.failed", error=error_message))
        return WorkerProfilesResponse()


@router.post("/profiles/switch", response_model=WorkerSwitchProfileResponse, tags=[WORKER_PROXY_TAG])
async def switch_bridge_profile(
    payload: WorkerSwitchProfileRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/profiles/current", "switch")
    ),
) -> WorkerSwitchProfileResponse:
    try:
        raw = await aiida_capability.switch_profile(payload.profile)
        return WorkerSwitchProfileResponse.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.profile_switch.failed", error=error_message))
        return WorkerSwitchProfileResponse(status="error", current_profile=None)


@router.get("/management/infrastructure", response_model=list[InfrastructureComputer], tags=[WORKER_PROXY_TAG])
async def get_management_infrastructure():
    """Proxy to fetch hierarchical infrastructure (Computers -> Codes)."""
    try:
        return await aiida_worker_client.inspect_infrastructure_v2()
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        logger.warning(log_event("aiida.worker.infrastructure.unsupported", error=error_message))
        return []




@router.post("/management/infrastructure/setup", tags=[WORKER_PROXY_TAG])
async def setup_management_infrastructure(
    payload: dict[str, Any],
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/infrastructure/computers", "configure")
    ),
):
    """Proxy to setup a new computer, authentication, and code."""
    try:
        return await aiida_worker_client.setup_infrastructure(payload)
    except Exception as exc:
        _raise_worker_http_error(exc)








@router.get("/management/profiles/current-user-info", response_model=UserInfoResponse, tags=[WORKER_PROXY_TAG])
async def get_current_user_info():
    """Proxy to fetch current user information from the worker."""
    try:
        return await aiida_worker_client.get_current_user_info()
    except Exception as exc:
        _raise_worker_http_error(exc)


@router.post("/management/profiles/setup", tags=[WORKER_PROXY_TAG])
async def setup_profile(
    payload: ProfileSetupRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/profiles", "configure")
    ),
):
    """Proxy to setup a new AiiDA profile on the worker."""
    try:
        return await aiida_worker_client.setup_profile(payload.model_dump())
    except Exception as exc:
        _raise_worker_http_error(exc)


async def _submit_bridge_workchain_impl(
    request: Request,
    payload: SubmissionDraftRequest,
    *,
    require_batch_list: bool = False,
):
    if not payload.draft:
        raise HTTPException(status_code=422, detail="Submission draft is required")

    draft_payload = payload.draft
    if require_batch_list and not isinstance(draft_payload, list):
        raise HTTPException(status_code=422, detail="Batch submission draft list is required")
    expected_scope: Literal["single", "batch"] = "batch" if isinstance(draft_payload, list) else "single"
    try:
        approval_audit = resolve_submission_approval(
            payload.approval,
            draft_payload,
            expected_scope=expected_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    worker_request_context = _build_submission_worker_context(request.app.state)
    worker_payload: dict[str, Any]
    if (
        isinstance(draft_payload, dict)
        and isinstance(draft_payload.get("inputs"), dict)
        and str(draft_payload.get("entry_point") or "").strip()
    ):
        worker_payload = {
            "entry_point": str(draft_payload.get("entry_point")).strip(),
            "inputs": dict(draft_payload.get("inputs") or {}),
        }
    else:
        worker_payload = {"draft": draft_payload}
    if payload.interpreter_info is not None:
        worker_payload["interpreter_info"] = payload.interpreter_info.model_dump()
    worker_metadata = dict(payload.metadata or {})
    worker_metadata["aris_approval"] = approval_audit.model_dump(mode="json")
    if worker_metadata:
        worker_payload["metadata"] = worker_metadata
    if isinstance(draft_payload, list):
        if len(draft_payload) == 0:
            raise HTTPException(status_code=422, detail="Submission draft list cannot be empty")
        try:
            raw = await worker_call("submission.submit", params=worker_payload, context=worker_request_context)
        except Exception as exc:
            _raise_worker_http_error(exc)

        batch_response = format_worker_batch_submission_response(raw)
        submitted_pks = [
            int(pk)
            for pk in batch_response.get("submitted_pks", [])
            if isinstance(pk, int) and pk > 0
        ]
        if submitted_pks:
            _clear_pending_submission_memory(request.app.state)
        try:
            auto_groups = await _auto_assign_submission_groups(request.app.state, submitted_pks)
        except Exception as exc:  # noqa: BLE001
            logger.warning(log_event("aiida.frontend.submission.auto_group_failed", error=str(exc), submitted_pks=submitted_pks))
        else:
            if auto_groups:
                batch_response["auto_groups"] = auto_groups
        batch_response["approval"] = approval_audit.model_dump(mode="json")
        return batch_response

    try:
        raw = await worker_call("submission.submit", params=worker_payload, context=worker_request_context)
        response = format_single_submission_response(raw)
        _clear_pending_submission_memory(request.app.state)
        try:
            auto_groups = await _auto_assign_submission_groups(request.app.state, response.get("submitted_pks", []))
        except Exception as exc:  # noqa: BLE001
            logger.warning(log_event("aiida.frontend.submission.auto_group_failed", error=str(exc), response=response))
        else:
            if auto_groups:
                response["auto_groups"] = auto_groups
        response["approval"] = approval_audit.model_dump(mode="json")
        return response
    except WorkerOfflineError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except WorkerRPCError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc


@router.post("/submission/submit", tags=[WORKER_PROXY_TAG])
async def submit_bridge_workchain(
    request: Request,
    payload: SubmissionDraftRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/submissions/current", "execute")
    ),
):
    return await _submit_bridge_workchain_impl(request, payload)


@router.post("/submission/review", tags=[WORKER_PROXY_TAG])
async def review_bridge_workchain(
    payload: SubmissionReviewRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/submissions/current", "execute")
    ),
):
    drafts = payload.draft if isinstance(payload.draft, list) else [payload.draft]
    validation_items: list[dict[str, Any]] = []
    for draft in drafts:
        try:
            result = await worker_call("submission.validate", {"draft": draft})
        except Exception as exc:  # noqa: BLE001
            _raise_worker_http_error(exc)
        validation_items.append(result if isinstance(result, dict) else {"status": "validated"})
    scope: Literal["single", "batch"] = "batch" if isinstance(payload.draft, list) else "single"
    return {
        "validation": validation_items if scope == "batch" else validation_items[0],
        "approval_request": build_submission_approval_request(
            payload.draft,
            scope=scope,
        ).model_dump(mode="json"),
    }


@router.post("/submission/submit_batch", tags=[WORKER_PROXY_TAG])
async def submit_bridge_workchain_batch(
    request: Request,
    payload: SubmissionDraftRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/submissions/current", "execute")
    ),
):
    return await _submit_bridge_workchain_impl(request, payload, require_batch_list=True)


@router.post("/frontend/environment/inspect", tags=[FRONTEND_TAG])
async def frontend_environment_inspect(payload: EnvironmentInspectRequest):
    python_path = str(payload.python_path or "").strip() or None
    workspace_path = str(payload.workspace_path or "").strip() or None

    if payload.use_worker_default or not python_path:
        try:
            raw = await aiida_worker_client.inspect_default_environment(force_refresh=False)
        except Exception as exc:
            _raise_worker_http_error(exc)

        if not isinstance(raw, dict):
            raise HTTPException(status_code=502, detail={"error": "Worker returned invalid default environment payload"})

        raw["mode"] = "worker-default"
        raw["source"] = "worker-default-environment"
        raw["python_path"] = raw.get("python_interpreter_path")
        raw["workspace_path"] = workspace_path
        return raw

    try:
        raw = await worker_call(
            "environment.inspect",
            {
                "python_interpreter_path": python_path,
                "force_refresh": False,
            },
        )
    except Exception as exc:
        _raise_worker_http_error(exc)

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"error": "Worker returned invalid environment inspection payload"})

    raw["mode"] = "project"
    raw["source"] = "environment-inspect"
    raw["python_path"] = python_path
    raw["workspace_path"] = workspace_path
    return raw







@router.get("/data/remote/{pk}/files/{filename:path}", tags=[WORKER_PROXY_TAG])
async def worker_remote_file_content(pk: int, filename: str):
    try:
        return await worker_call("data.remote_file", {"pk": int(pk), "filename": filename})
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)




@router.get("/data/repository/{pk}/files/{filename:path}", tags=[WORKER_PROXY_TAG])
async def worker_repository_file_content(
    pk: int,
    filename: str,
    source: str = Query(default="folder"),
):
    try:
        return await worker_call(
            "data.repository_file",
            {"pk": int(pk), "filename": filename, "source": source},
        )
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)


@router.get("/process/{identifier}", tags=[WORKER_PROXY_TAG])
async def worker_process_detail(identifier: str):
    try:
        payload = await worker_call("process.detail", {"identifier": identifier})
        if isinstance(payload, dict):
            return await _enrich_process_detail_payload(payload)
        return {"data": payload}
    except WorkerOfflineError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except WorkerRPCError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc


@router.get("/process/{identifier}/logs", tags=[WORKER_PROXY_TAG])
async def worker_process_logs(identifier: str):
    try:
        payload = await worker_call("process.logs", {"identifier": identifier})
        return payload if isinstance(payload, dict) else {"data": payload}
    except WorkerOfflineError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except WorkerRPCError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc


@router.get("/process/{identifier}/workgraph", tags=[WORKER_PROXY_TAG])
async def worker_process_workgraph(identifier: str):
    try:
        payload = await worker_call("process.workgraph", {"identifier": identifier})
        return payload if isinstance(payload, dict) else {"data": payload}
    except WorkerOfflineError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except WorkerRPCError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc


@router.post("/data/import/{data_type}", tags=[WORKER_PROXY_TAG])
async def proxy_import_data(
    data_type: str,
    source_type: str = Form(...),
    label: str | None = Form(None),
    description: str | None = Form(None),
    raw_text: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    """Proxy data import to aiida-worker."""
    file_content = None
    filename = None
    if file:
        file_content = await file.read()
        filename = file.filename

    try:
        return await import_worker_data(
            data_type=data_type,
            source_type=source_type,
            label=label,
            description=description,
            raw_text=raw_text,
            filename=filename,
            file_content=file_content,
        )
    except Exception as exc:
        _raise_worker_http_error(exc)


@router.get("/frontend/bootstrap", tags=[FRONTEND_TAG])
async def frontend_bootstrap(request: Request):
    state = request.app.state
    try:
        processes = await _get_frontend_nodes_async(limit=15)
    except Exception as error:  # noqa: BLE001
        logger.exception(log_event("aiida.frontend.bootstrap.processes.failed", error=str(error)))
        processes = []

    try:
        groups = await _get_frontend_groups_async()
    except Exception as error:  # noqa: BLE001
        logger.exception(log_event("aiida.frontend.bootstrap.groups.failed", error=str(error)))
        groups = []

    available_models = _get_available_models(state)
    selected_model = _get_selected_model(state, available_models)
    log_version, log_lines = get_log_buffer_snapshot(limit=240)
    chat_snapshot = get_chat_snapshot(state)

    return {
        "processes": _serialize_processes(processes),
        "groups": _serialize_groups(groups),
        "chat": chat_snapshot,
        "logs": {
            "version": log_version,
            "lines": log_lines[-160:],
        },
        "models": available_models,
        "selected_model": selected_model,
        "quick_prompts": _get_quick_prompts(),
        "authorization": local_authorization_snapshot().model_dump(mode="json"),
    }




@router.get("/frontend/groups", tags=[FRONTEND_TAG])
async def frontend_groups():
    try:
        items = _get_frontend_groups()
    except Exception as error:  # noqa: BLE001
        logger.exception(log_event("aiida.frontend.groups.failed", error=str(error)))
        items = []
    return {"items": _serialize_groups(items)}


@router.websocket("/frontend/groups/ws")
async def frontend_groups_ws(websocket: WebSocket):
    await websocket.accept()
    stream_id = id(websocket)
    last_digest = ""
    heartbeat_ts = time.monotonic()
    logger.info(log_event("aiida.frontend.groups_ws.connected", stream_id=stream_id))

    try:
        while True:
            try:
                groups = _serialize_groups(await _get_frontend_groups_async())
                digest = hashlib.sha1(json.dumps(groups, sort_keys=True).encode("utf-8")).hexdigest()
                now = time.monotonic()
                should_push = (digest != last_digest) or ((now - heartbeat_ts) >= 15)
                if should_push:
                    await websocket.send_json({"event": "groups", "data": {"items": groups}})
                    last_digest = digest
                    heartbeat_ts = now
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    log_event("aiida.frontend.groups_ws.failed", stream_id=stream_id, error=str(error))
                )
                try:
                    await websocket.send_json({"event": "groups", "data": {"items": []}})
                except Exception:
                    pass

            await asyncio.sleep(2.5)
    except (WebSocketDisconnect, RuntimeError):
        logger.info(log_event("aiida.frontend.groups_ws.disconnected", stream_id=stream_id))


@router.post("/frontend/groups/create", tags=[FRONTEND_TAG])
async def frontend_create_group(payload: FrontendGroupCreateRequest):
    if not hub.current_profile:
        hub.start()
    try:
        response = create_group(payload.label)
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)
    return {"item": _serialize_groups([response])[0] if isinstance(response, dict) else None}


@router.put("/frontend/groups/{pk}/label", tags=[FRONTEND_TAG])
async def frontend_rename_group(pk: int, payload: FrontendGroupRenameRequest):
    if not hub.current_profile:
        hub.start()
    try:
        response = rename_group(pk, payload.label)
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)
    return {"item": _serialize_groups([response])[0] if isinstance(response, dict) else None}


@router.delete("/frontend/groups/{pk}", tags=[FRONTEND_TAG])
async def frontend_delete_group(
    pk: int,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/groups/item", "delete")
    ),
):
    if not hub.current_profile:
        hub.start()
    try:
        response = delete_group(pk)
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)
    return response if isinstance(response, dict) else {"status": "deleted", "pk": int(pk)}


@router.post("/frontend/groups/{pk}/nodes", tags=[FRONTEND_TAG])
async def frontend_add_nodes_to_group(pk: int, payload: FrontendGroupAssignNodesRequest):
    if not hub.current_profile:
        hub.start()
    try:
        response = add_nodes_to_group(pk, payload.node_pks)
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)
    if not isinstance(response, dict):
        return {"group": None, "added": [], "missing": []}
    group_payload = response.get("group")
    response_payload = dict(response)
    response_payload["group"] = _serialize_groups([group_payload])[0] if isinstance(group_payload, dict) else None
    return response_payload




@router.post("/frontend/archives/upload", tags=[FRONTEND_TAG])
async def frontend_upload_archive(file: UploadFile = File(...)):
    filename = file.filename or "archive.aiida"
    extension = Path(filename).suffix.lower()
    if extension not in ARCHIVE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported archive format")

    upload_root = Path(tempfile.gettempdir()) / "aris-aiida-uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    target_name = f"{int(time.time() * 1000)}-{_sanitize_upload_name(filename)}"
    target_path = upload_root / target_name

    payload = await file.read()
    target_path.write_bytes(payload)
    await file.close()

    profile_name = hub.import_archive(target_path)
    return {
        "status": "uploaded",
        "profile_name": profile_name,
        "stored_path": str(target_path),
    }








@router.get(
    "/frontend/processes/{identifier}/diagnostics",
    response_model=ProcessDiagnosticsResponse,
    tags=[FRONTEND_TAG],
)
async def frontend_process_diagnostics(identifier: str):
    try:
        return await _build_process_diagnostics(identifier)
    except WorkerOfflineError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except WorkerRPCError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {"error": exc.message, "details": exc.payload}
        raise HTTPException(status_code=max(400, int(exc.status_code or 502)), detail=detail) from exc


@router.get("/frontend/ssh-hosts", tags=[FRONTEND_TAG])
async def frontend_ssh_hosts():
    try:
        hosts = await aiida_worker_client.get_ssh_config()
        return {"items": hosts}
    except Exception as error:
        logger.exception(log_event("aiida.frontend.ssh_hosts.failed", error=str(error)))
        raise HTTPException(status_code=500, detail="Failed to fetch SSH hosts")

@router.post("/frontend/infrastructure/setup-code", tags=[FRONTEND_TAG])
async def frontend_setup_code(
    payload: CodeSetupRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/infrastructure/codes", "configure")
    ),
):
    """Proxy code setup to AIIDA worker."""
    logger.info(log_event("aiida.frontend.setup_code.request", computer=payload.computer_label, label=payload.label))
    try:
        response = await aiida_worker_client.setup_code(payload)
        logger.info(log_event("aiida.frontend.setup_code.success", pk=response.get("pk")))
        return response
    except Exception as exc:
        error_payload = exc.payload if isinstance(exc, WorkerRPCError) else None
        logger.error(log_event("aiida.frontend.setup_code.failed", error=str(exc), detail=error_payload))
        _raise_worker_http_error(exc)

@router.get("/frontend/infrastructure/computer/{computer_label}/codes", response_model=list[CodeDetailedResponse], tags=[FRONTEND_TAG])
async def frontend_get_computer_codes(computer_label: str):
    """Proxy fetching detailed computer codes to AIIDA worker."""
    try:
        response = await aiida_worker_client.get_computer_codes(computer_label)
        return response
    except Exception as exc:
        _raise_worker_http_error(exc)


@router.post("/frontend/parse-infrastructure", tags=[FRONTEND_TAG])
async def parse_infrastructure_via_ai(payload: ParseInfrastructureRequest):
    """Proxy to AiiDA service for AI infrastructure parsing."""
    try:
        parsed = await _parse_infrastructure_via_ai(payload.text, payload.ssh_host_details)
        return {"status": "success", "data": parsed}
    except Exception as error:
        logger.exception(log_event("aiida.frontend.parse_infrastructure.failed", error=str(error)))
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"AI Parsing failed: {str(error)}")






@router.post("/frontend/nodes/{pk}/soft-delete", tags=[FRONTEND_TAG])
async def frontend_node_soft_delete(
    pk: int = ApiPath(..., ge=1),
    payload: FrontendNodeSoftDeleteRequest | None = None,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/nodes/item", "delete")
    ),
):
    if not hub.current_profile:
        hub.start()
    deleted = bool(payload.deleted) if isinstance(payload, FrontendNodeSoftDeleteRequest) else True
    try:
        response = soft_delete_node(pk, deleted=deleted)
    except Exception as exc:  # noqa: BLE001
        _raise_worker_http_error(exc)
    return response if isinstance(response, dict) else {"pk": int(pk), "soft_deleted": deleted}


@router.websocket("/frontend/processes/ws")
async def frontend_processes_ws(
    websocket: WebSocket,
    limit: int = Query(default=15, ge=1, le=100),
    group_label: str | None = Query(default=None),
    node_type: str | None = Query(default=None),
    root_only: bool = Query(default=True),
):
    try:
        await _get_frontend_nodes_async(
            limit=1,
            group_label=group_label,
            node_type=node_type,
            root_only=root_only,
        )
    except ValueError as error:
        await websocket.close(code=1003, reason=str(error))
        return

    await websocket.accept()
    stream_id = id(websocket)
    last_digest = ""
    heartbeat_ts = time.monotonic()
    logger.info(log_event("aiida.frontend.process_ws.connected", stream_id=stream_id))

    try:
        while True:
            try:
                processes = _serialize_processes(
                    await _get_frontend_nodes_async(
                        limit=limit,
                        group_label=group_label,
                        node_type=node_type,
                        root_only=root_only,
                    )
                )
                digest = hashlib.sha1(json.dumps(processes, sort_keys=True).encode("utf-8")).hexdigest()
                now = time.monotonic()
                should_push = (digest != last_digest) or ((now - heartbeat_ts) >= 15)
                if should_push:
                    await websocket.send_json({"event": "processes", "data": {"items": processes}})
                    last_digest = digest
                    heartbeat_ts = now
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    log_event("aiida.frontend.process_ws.failed", stream_id=stream_id, error=str(error))
                )
                try:
                    await websocket.send_json({"event": "processes", "data": {"items": []}})
                except Exception:
                    pass

            await asyncio.sleep(3.0)
    except (WebSocketDisconnect, RuntimeError):
        logger.info(log_event("aiida.frontend.process_ws.disconnected", stream_id=stream_id))


@router.websocket("/frontend/infrastructure/ws")
async def frontend_infrastructure_ws(websocket: WebSocket):
    await websocket.accept()
    stream_id = id(websocket)
    last_digest = ""
    heartbeat_ts = time.monotonic()
    logger.info(log_event("aiida.frontend.infrastructure_ws.connected", stream_id=stream_id))

    try:
        while True:
            try:
                infrastructure = await aiida_worker_client.inspect_infrastructure_v2()
                digest = hashlib.sha1(json.dumps(infrastructure, sort_keys=True).encode("utf-8")).hexdigest()
                now = time.monotonic()
                should_push = (digest != last_digest) or ((now - heartbeat_ts) >= 15)
                if should_push:
                    await websocket.send_json({"event": "infrastructure", "data": {"items": infrastructure}})
                    last_digest = digest
                    heartbeat_ts = now
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    log_event("aiida.frontend.infrastructure_ws.failed", stream_id=stream_id, error=str(error))
                )
                try:
                    await websocket.send_json({"event": "error", "data": {"error": str(error)}})
                except Exception:
                    pass

            await asyncio.sleep(5.0)
    except (WebSocketDisconnect, RuntimeError):
        logger.info(log_event("aiida.frontend.infrastructure_ws.disconnected", stream_id=stream_id))


@router.get("/frontend/logs", tags=[FRONTEND_TAG])
async def frontend_logs(limit: int = Query(default=240, ge=20, le=1000)):
    version, lines = get_log_buffer_snapshot(limit=limit)
    return {"version": version, "lines": lines}


@router.websocket("/frontend/logs/ws")
async def frontend_logs_ws(websocket: WebSocket, limit: int = Query(default=240, ge=20, le=1000)):
    await websocket.accept()
    stream_id = id(websocket)
    last_version = -1
    heartbeat_ts = time.monotonic()
    logger.info(log_event("aiida.frontend.log_ws.connected", stream_id=stream_id))

    try:
        while True:
            try:
                version, lines = get_log_buffer_snapshot(limit=limit)
                now = time.monotonic()
                should_push = (version != last_version) or ((now - heartbeat_ts) >= 8.0)
                if should_push:
                    await websocket.send_json({"event": "logs", "data": {"version": version, "lines": lines}})
                    last_version = version
                    heartbeat_ts = now
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    log_event("aiida.frontend.log_ws.failed", stream_id=stream_id, error=str(error))
                )
                try:
                    await websocket.send_json({"event": "logs", "data": {"version": -1, "lines": []}})
                except Exception:
                    pass

            await asyncio.sleep(1.5)
    except (WebSocketDisconnect, RuntimeError):
        logger.info(log_event("aiida.frontend.log_ws.disconnected", stream_id=stream_id))


@router.post("/frontend/submission/pending/cancel", tags=[FRONTEND_TAG])
async def frontend_cancel_pending_submission(
    request: Request,
    payload: SubmissionApprovalCancelRequest,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/submissions/current", "cancel")
    ),
):
    approval = payload.approval
    if approval.decision != "rejected" or approval.scope != "pending":
        raise HTTPException(
            status_code=409,
            detail="Pending submission cancellation requires a rejected pending approval decision",
        )
    logger.info(
        log_event(
            "aiida.frontend.submission.cancelled",
            approval_id=approval.approval_id,
            actor_type=approval.actor_type,
        )
    )
    _clear_pending_submission_memory(request.app.state)
    return {
        "status": "cancelled",
        "approval": approval.model_dump(mode="json"),
    }


@router.get("/frontend/chat/sessions", tags=[FRONTEND_TAG])
async def frontend_chat_sessions(request: Request, response: Response):
    state = request.app.state
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return _chat_sessions_payload(state)




@router.get("/frontend/chat/projects", tags=[FRONTEND_TAG])
async def frontend_chat_projects(request: Request):
    state = request.app.state
    return {
        "active_project_id": get_active_chat_project_id(state),
        "items": list_chat_projects(state),
    }


@router.post("/frontend/chat/projects/browse-directory", tags=[FRONTEND_TAG])
async def frontend_browse_chat_project_directory(request: Request):
    """Open a native MacOS folder picker dialog and return the selected path."""
    import subprocess
    try:
        script = '''
        tell application (path to frontmost application as text)
            set folderPath to choose folder with prompt "Select Project Folder"
            POSIX path of folderPath
        end tell
        '''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            return {"path": result.stdout.strip(), "success": True}
        return {"path": None, "success": False, "error": "User cancelled or error occurred."}
    except Exception as e:
        return {"path": None, "success": False, "error": str(e)}




@router.patch("/frontend/chat/projects/{project_id}", tags=[FRONTEND_TAG])
async def frontend_update_chat_project(
    request: Request, project_id: str, payload: FrontendChatProjectUpdateRequest
):
    state = request.app.state
    try:
        project = update_chat_project(
            state,
            project_id=project_id,
            python_interpreter_path=payload.python_interpreter_path,
            aiida_profile=payload.aiida_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return {
        "project": project,
        "active_project_id": get_active_chat_project_id(state),
        "projects": list_chat_projects(state),
    }






@router.delete("/frontend/chat/sessions/{session_id}", tags=[FRONTEND_TAG])
async def frontend_delete_chat_session(
    request: Request,
    session_id: str,
    _authorization: AuthorizationDecision = Depends(
        require_permission("/aris/chat/sessions", "delete")
    ),
):
    state = request.app.state
    
    # Collect group labels before deleting the chat session
    target_labels = []
    for s in list_chat_sessions(state):
        if s.get("id") == session_id and s.get("session_group_label"):
            target_labels.append(s["session_group_label"])
            
    deleted = delete_chat_items(state, session_ids=[session_id])
    if session_id not in set(deleted.get("deleted_session_ids") or []):
        raise HTTPException(status_code=404, detail="Chat session not found")
        
    for target in target_labels:
        for group in list_groups():
            gl = str(group.get("label") or "")
            if gl == target or gl.startswith(f"{target}/"):
                try:
                    delete_group(int(group["pk"]))
                except Exception:
                    pass
                    
    return _chat_delete_response(state, deleted)




@router.post("/frontend/chat/sessions/{session_id}/activate", tags=[FRONTEND_TAG])
async def frontend_activate_chat_session(request: Request, session_id: str):
    state = request.app.state
    session = activate_chat_session(state, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {
        "session": session,
        "chat": get_chat_snapshot(state),
        "active_session_id": get_active_chat_session_id(state),
        "active_project_id": get_active_chat_project_id(state),
        "projects": list_chat_projects(state),
        "version": int(getattr(state, "chat_sessions_version", 0)),
    }


@router.patch("/frontend/chat/sessions/{session_id}", tags=[FRONTEND_TAG])
async def frontend_update_chat_session(
    request: Request,
    session_id: str,
    payload: FrontendChatSessionUpdateRequest,
):
    state = request.app.state
    update_kwargs: dict[str, Any] = {}
    if "title" in payload.model_fields_set:
        update_kwargs["title"] = payload.title
    if "tags" in payload.model_fields_set:
        update_kwargs["tags"] = payload.tags
    if "snapshot" in payload.model_fields_set:
        update_kwargs["snapshot"] = payload.snapshot
    session = update_chat_session(state, session_id, **update_kwargs)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {
        "session": session,
        "chat": get_chat_snapshot(state),
        "active_session_id": get_active_chat_session_id(state),
        "active_project_id": get_active_chat_project_id(state),
        "projects": list_chat_projects(state),
        "version": int(getattr(state, "chat_sessions_version", 0)),
    }


@router.put("/frontend/chat/sessions/{session_id}/title", tags=[FRONTEND_TAG])
async def frontend_update_chat_session_title(
    request: Request,
    session_id: str,
    payload: FrontendChatSessionTitleUpdateRequest,
):
    state = request.app.state
    session = update_chat_session(state, session_id, title=payload.title)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {
        "session": session,
        "chat": get_chat_snapshot(state),
        "active_session_id": get_active_chat_session_id(state),
        "active_project_id": get_active_chat_project_id(state),
        "projects": list_chat_projects(state),
        "version": int(getattr(state, "chat_sessions_version", 0)),
    }


@router.get("/frontend/chat/sessions/{session_id}/workspace", tags=[FRONTEND_TAG])
async def frontend_chat_session_workspace(
    request: Request,
    session_id: str,
    relative_path: str | None = Query(default=None),
):
    state = request.app.state
    try:
        payload = list_chat_session_workspace_files(state, session_id, relative_path=relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return payload




