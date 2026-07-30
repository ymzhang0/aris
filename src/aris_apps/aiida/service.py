"""Canonical AiiDA service facade.

Aggregates worker-backed hub state, bridge client accessors, and AI-driven infrastructure parsing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException
from google import genai
from loguru import logger
import yaml

from src.aris_core.config import settings
from src.aris_core.logging import log_event

from .client import (
    AiiDAWorkerClient,
    WorkerRPCError,
    WorkerConnectionState,
    WorkerOfflineError,
    WorkerResourceCounts,
    WorkerSnapshot,
    aiida_worker_client,
)
from .frontend_bridge import (
    add_nodes_to_group,
    create_group,
    delete_group,
    export_group_archive,
    get_context_nodes,
    get_recent_nodes,
    list_groups,
    rename_group,
    soft_delete_node,
)
from .hub import AiiDAHub, hub
from .infrastructure_manager import infrastructure_manager


_SYNC_SSH_TRANSPORT = "core.ssh"
_ASYNC_SSH_TRANSPORT = "core.ssh_async"
_TRANSPORT_ALIASES = {
    "local": "core.local",
    "core.local": "core.local",
    "ssh": _SYNC_SSH_TRANSPORT,
    "core.ssh": _SYNC_SSH_TRANSPORT,
    "ssh_async": _ASYNC_SSH_TRANSPORT,
    "core.ssh_async": _ASYNC_SSH_TRANSPORT,
    "asyncssh": _ASYNC_SSH_TRANSPORT,
}
_SYNC_SSH_ONLY_FIELDS = (
    "username",
    "port",
    "look_for_keys",
    "key_filename",
    "timeout",
    "allow_agent",
    "proxy_command",
    "proxy_jump",
    "compress",
    "gss_auth",
    "gss_kex",
    "gss_deleg_creds",
    "gss_host",
    "load_system_host_keys",
    "key_policy",
)


def _default_infrastructure_capabilities() -> dict[str, Any]:
    return {
        "aiida_core_version": "unknown",
        "available_transports": ["core.local", _SYNC_SSH_TRANSPORT],
        "recommended_transport": _SYNC_SSH_TRANSPORT,
        "supports_async_ssh": False,
        "transport_auth_fields": {
            "core.local": ["use_login_shell", "safe_interval"],
            _SYNC_SSH_TRANSPORT: [
                "username",
                "port",
                "look_for_keys",
                "key_filename",
                "timeout",
                "allow_agent",
                "proxy_jump",
                "proxy_command",
                "compress",
                "gss_auth",
                "gss_kex",
                "gss_deleg_creds",
                "gss_host",
                "load_system_host_keys",
                "key_policy",
                "use_login_shell",
                "safe_interval",
            ],
            _ASYNC_SSH_TRANSPORT: [
                "host",
                "max_io_allowed",
                "authentication_script",
                "backend",
                "use_login_shell",
                "safe_interval",
            ],
        },
    }


async def _get_infrastructure_capabilities() -> dict[str, Any]:
    try:
        payload = await aiida_worker_client.get_infrastructure_capabilities()
    except Exception as error:  # noqa: BLE001
        logger.warning(log_event("aiida.service.infrastructure_capabilities.fallback", error=str(error)))
        return _default_infrastructure_capabilities()

    fallback = _default_infrastructure_capabilities()
    if not isinstance(payload, dict):
        return fallback

    available_transports = [
        str(item).strip()
        for item in payload.get("available_transports", fallback["available_transports"])
        if str(item).strip()
    ]
    transport_auth_fields = payload.get("transport_auth_fields")
    if not isinstance(transport_auth_fields, dict):
        transport_auth_fields = fallback["transport_auth_fields"]

    return {
        "aiida_core_version": str(payload.get("aiida_core_version") or fallback["aiida_core_version"]),
        "available_transports": available_transports or fallback["available_transports"],
        "recommended_transport": str(payload.get("recommended_transport") or fallback["recommended_transport"]),
        "supports_async_ssh": bool(payload.get("supports_async_ssh", False)),
        "transport_auth_fields": {
            str(key): [str(field) for field in value]
            for key, value in transport_auth_fields.items()
            if isinstance(value, list)
        } or fallback["transport_auth_fields"],
    }


def _normalize_transport_type(raw_value: Any, capabilities: dict[str, Any]) -> str:
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return str(capabilities.get("recommended_transport") or _SYNC_SSH_TRANSPORT)
    return _TRANSPORT_ALIASES.get(normalized, str(raw_value or "").strip())


def _coerce_string(value: Any) -> str:
    return str(value).strip() if value not in (None, False) else ""


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool | None = None) -> bool | None:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _has_configured_value(value: Any) -> bool:
    return value is not None and value != ""


def _coerce_mpirun_command(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return _coerce_string(value)


def _looks_like_yaml_mapping(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("{") or stripped.startswith("["):
        return True
    return bool(re.search(r"(?m)^\s*[A-Za-z_][A-Za-z0-9_-]*\s*:", stripped))


def _looks_like_computer_payload(payload: dict[str, Any]) -> bool:
    keys = {str(key) for key in payload.keys()}
    return bool(
        keys
        & {
            "hostname",
            "transport",
            "transport_type",
            "scheduler",
            "scheduler_type",
            "work_dir",
            "workdir",
            "computer_label",
            "mpiprocs_per_machine",
            "auth",
        }
    )


def _looks_like_code_payload(payload: dict[str, Any]) -> bool:
    keys = {str(key) for key in payload.keys()}
    return bool(keys & {"default_calc_job_plugin", "filepath_executable", "remote_abspath", "with_mpi"})


def _normalize_code_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": _coerce_string(raw_payload.get("label")),
        "description": _coerce_string(raw_payload.get("description")),
        "default_calc_job_plugin": _coerce_string(raw_payload.get("default_calc_job_plugin")),
        "remote_abspath": _coerce_string(raw_payload.get("remote_abspath") or raw_payload.get("filepath_executable")),
        "prepend_text": _coerce_string(raw_payload.get("prepend_text")),
        "append_text": _coerce_string(raw_payload.get("append_text")),
    }


def _normalize_computer_payload(
    raw_payload: dict[str, Any],
    capabilities: dict[str, Any],
    ssh_host_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth_payload = raw_payload.get("auth") if isinstance(raw_payload.get("auth"), dict) else {}
    ssh_host_details = ssh_host_details or {}
    transport_type = _normalize_transport_type(
        raw_payload.get("transport_type") or raw_payload.get("transport"),
        capabilities,
    )

    host_alias = _coerce_string(auth_payload.get("host") or raw_payload.get("host") or ssh_host_details.get("alias"))
    hostname = _coerce_string(raw_payload.get("hostname") or ssh_host_details.get("hostname") or host_alias)
    user = _coerce_string(auth_payload.get("user") or raw_payload.get("user"))
    raw_username = _coerce_string(auth_payload.get("username") or raw_payload.get("username"))
    raw_port = _coerce_int(auth_payload.get("port") or raw_payload.get("port"))
    raw_key_filename = _coerce_string(auth_payload.get("key_filename") or raw_payload.get("key_filename"))
    raw_timeout = _coerce_int(
        auth_payload.get("timeout")
        or auth_payload.get("connection_timeout")
        or raw_payload.get("timeout")
        or raw_payload.get("connection_timeout")
    )
    raw_look_for_keys = _coerce_bool(
        auth_payload.get("look_for_keys") if auth_payload else raw_payload.get("look_for_keys"),
    )
    raw_allow_agent = _coerce_bool(
        auth_payload.get("allow_agent") if auth_payload else raw_payload.get("allow_agent"),
    )
    raw_proxy_command = _coerce_string(auth_payload.get("proxy_command") or raw_payload.get("proxy_command"))
    raw_proxy_jump = _coerce_string(auth_payload.get("proxy_jump") or raw_payload.get("proxy_jump"))
    raw_compress = _coerce_bool(
        auth_payload.get("compress") if auth_payload else raw_payload.get("compress"),
    )
    raw_gss_auth = _coerce_bool(
        auth_payload.get("gss_auth") if auth_payload else raw_payload.get("gss_auth"),
    )
    raw_gss_kex = _coerce_bool(
        auth_payload.get("gss_kex") if auth_payload else raw_payload.get("gss_kex"),
    )
    raw_gss_deleg_creds = _coerce_bool(
        auth_payload.get("gss_deleg_creds") if auth_payload else raw_payload.get("gss_deleg_creds"),
    )
    raw_gss_host = _coerce_string(auth_payload.get("gss_host") or raw_payload.get("gss_host"))
    raw_load_system_host_keys = _coerce_bool(
        auth_payload.get("load_system_host_keys") if auth_payload else raw_payload.get("load_system_host_keys"),
    )
    raw_key_policy = _coerce_string(auth_payload.get("key_policy") or raw_payload.get("key_policy"))
    username = raw_username or _coerce_string(ssh_host_details.get("username"))
    port = raw_port if raw_port is not None else _coerce_int(ssh_host_details.get("port"))
    key_filename = raw_key_filename or _coerce_string(ssh_host_details.get("identity_file"))
    proxy_command = raw_proxy_command or _coerce_string(ssh_host_details.get("proxy_command"))
    proxy_jump = raw_proxy_jump or _coerce_string(ssh_host_details.get("proxy_jump"))
    label = _coerce_string(raw_payload.get("label") or raw_payload.get("computer_label") or ssh_host_details.get("alias"))
    if not label:
        label = hostname or host_alias or "computer"

    computer = {
        "label": label,
        "hostname": hostname or host_alias,
        "user": user,
        "username": raw_username if transport_type == _ASYNC_SSH_TRANSPORT else username,
        "description": _coerce_string(raw_payload.get("description") or raw_payload.get("computer_description")),
        "transport_type": transport_type,
        "scheduler_type": _coerce_string(raw_payload.get("scheduler_type") or raw_payload.get("scheduler")) or "core.direct",
        "shebang": _coerce_string(raw_payload.get("shebang")) or "#!/bin/bash",
        "work_dir": _coerce_string(raw_payload.get("work_dir") or raw_payload.get("workdir")) or "/tmp/aiida",
        "mpiprocs_per_machine": _coerce_int(raw_payload.get("mpiprocs_per_machine")) or 1,
        "mpirun_command": _coerce_mpirun_command(raw_payload.get("mpirun_command")) or "mpirun -np {tot_num_mpiprocs}",
        "default_memory_per_machine": _coerce_int(raw_payload.get("default_memory_per_machine")),
        "use_double_quotes": bool(_coerce_bool(raw_payload.get("use_double_quotes"), False)),
        "prepend_text": _coerce_string(raw_payload.get("prepend_text")),
        "append_text": _coerce_string(raw_payload.get("append_text")),
        "port": raw_port if transport_type == _ASYNC_SSH_TRANSPORT else port,
        "look_for_keys": raw_look_for_keys,
        "key_filename": raw_key_filename if transport_type == _ASYNC_SSH_TRANSPORT else key_filename,
        "timeout": raw_timeout,
        "allow_agent": raw_allow_agent,
        "proxy_command": raw_proxy_command if transport_type == _ASYNC_SSH_TRANSPORT else proxy_command,
        "proxy_jump": raw_proxy_jump if transport_type == _ASYNC_SSH_TRANSPORT else proxy_jump,
        "compress": raw_compress,
        "gss_auth": raw_gss_auth,
        "gss_kex": raw_gss_kex,
        "gss_deleg_creds": raw_gss_deleg_creds,
        "gss_host": raw_gss_host,
        "load_system_host_keys": raw_load_system_host_keys,
        "key_policy": raw_key_policy,
        "safe_interval": _coerce_float(auth_payload.get("safe_interval") if auth_payload else raw_payload.get("safe_interval")),
        "use_login_shell": _coerce_bool(
            auth_payload.get("use_login_shell") if auth_payload else raw_payload.get("use_login_shell"),
            True,
        ),
        "host": host_alias if transport_type == _ASYNC_SSH_TRANSPORT else "",
        "max_io_allowed": _coerce_int(auth_payload.get("max_io_allowed") or raw_payload.get("max_io_allowed")),
        "authentication_script": _coerce_string(
            auth_payload.get("authentication_script")
            or auth_payload.get("script_before")
            or raw_payload.get("authentication_script")
            or raw_payload.get("script_before")
        ),
        "backend": _coerce_string(auth_payload.get("backend") or raw_payload.get("backend")),
    }

    if transport_type == _ASYNC_SSH_TRANSPORT and not computer["host"]:
        computer["host"] = computer["hostname"]

    return computer


def _validate_computer_payload(computer: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    available_transports = {str(item) for item in capabilities.get("available_transports", [])}
    transport_type = str(computer.get("transport_type") or "")
    if transport_type not in available_transports:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Transport `{transport_type}` is not supported by aiida-core "
                f"{capabilities.get('aiida_core_version')}. Available transports: "
                f"{', '.join(sorted(available_transports)) or 'none'}."
            ),
        )

    if transport_type == _ASYNC_SSH_TRANSPORT:
        unsupported = [field for field in _SYNC_SSH_ONLY_FIELDS if _has_configured_value(computer.get(field))]
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Transport `core.ssh_async` uses SSH-config based authentication. "
                    f"Remove core.ssh-only fields: {', '.join(unsupported)}. "
                    "Use `host`, `max_io_allowed`, `authentication_script`, `backend`, "
                    "`use_login_shell`, and `safe_interval` instead."
                ),
            )
        if not _coerce_string(computer.get("host")):
            computer["host"] = _coerce_string(computer.get("hostname"))

    if not _coerce_string(computer.get("hostname")):
        raise HTTPException(status_code=422, detail="Computer configuration is missing `hostname`.")

    if not _coerce_string(computer.get("label")):
        computer["label"] = _coerce_string(computer.get("hostname") or computer.get("host")) or "computer"

    return computer


def _merge_presets_if_available(parsed: dict[str, Any]) -> dict[str, Any]:
    if not parsed.get("computer"):
        parsed["preset_matched"] = False
        parsed["preset_domain"] = ""
        return parsed

    merge_result = infrastructure_manager.merge_preset(parsed["computer"])
    parsed["computer"] = merge_result.get("config", parsed["computer"])
    parsed["preset_matched"] = merge_result.get("matched", False)
    parsed["preset_domain"] = merge_result.get("domain_pattern", "") if parsed["preset_matched"] else ""
    return parsed


def _normalize_structured_infrastructure_payload(
    raw_payload: dict[str, Any],
    capabilities: dict[str, Any],
    ssh_host_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    computer_raw: dict[str, Any] | None = None
    code_raw: dict[str, Any] | None = None

    if isinstance(raw_payload.get("computer"), dict) or isinstance(raw_payload.get("code"), dict):
        if isinstance(raw_payload.get("computer"), dict):
            computer_raw = raw_payload["computer"]
        if isinstance(raw_payload.get("code"), dict):
            code_raw = raw_payload["code"]
    else:
        if _looks_like_computer_payload(raw_payload):
            computer_raw = raw_payload
        elif _looks_like_code_payload(raw_payload):
            code_raw = raw_payload
        else:
            raise HTTPException(
                status_code=422,
                detail="YAML is valid but does not look like an AiiDA computer or code configuration.",
            )

    parsed: dict[str, Any] = {"type": "computer"}
    if computer_raw is not None:
        parsed["computer"] = _normalize_computer_payload(computer_raw, capabilities, ssh_host_details)
    if code_raw is not None:
        parsed["code"] = _normalize_code_payload(code_raw)

    parsed["type"] = "both" if parsed.get("computer") and parsed.get("code") else ("code" if parsed.get("code") else "computer")
    parsed = _merge_presets_if_available(parsed)
    if parsed.get("computer"):
        parsed["computer"] = _normalize_computer_payload(parsed["computer"], capabilities, ssh_host_details)
        parsed["computer"] = _validate_computer_payload(parsed["computer"], capabilities)

    return parsed


def _parse_structured_infrastructure_text(
    text: str,
    capabilities: dict[str, Any],
    ssh_host_details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _looks_like_yaml_mapping(text):
        return None

    try:
        raw_payload = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise HTTPException(status_code=422, detail=f"Invalid infrastructure YAML: {error}") from error

    if not isinstance(raw_payload, dict):
        raise HTTPException(status_code=422, detail="Infrastructure YAML must be a top-level mapping.")

    return _normalize_structured_infrastructure_payload(raw_payload, capabilities, ssh_host_details)


def _build_ssh_host_parse_result(ssh_host_details: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    transport_type = _normalize_transport_type(None, capabilities)
    parsed = {
        "type": "computer",
        "computer": _normalize_computer_payload(
            {
                "label": ssh_host_details.get("alias"),
                "hostname": ssh_host_details.get("hostname") or ssh_host_details.get("alias"),
                "transport_type": transport_type,
                "scheduler_type": "core.direct",
            },
            capabilities,
            ssh_host_details,
        ),
    }
    parsed = _merge_presets_if_available(parsed)
    parsed["computer"] = _normalize_computer_payload(parsed["computer"], capabilities, ssh_host_details)
    parsed["computer"] = _validate_computer_payload(parsed["computer"], capabilities)
    return parsed


def _build_ai_infrastructure_prompt(text: str, capabilities: dict[str, Any]) -> str:
    available_transports = ", ".join(capabilities.get("available_transports", [])) or _SYNC_SSH_TRANSPORT
    async_rule = (
        "If the installed aiida-core supports `core.ssh_async`, you may use it only for SSH-config based, "
        "password-less hosts and then you must use `host`, `max_io_allowed`, `authentication_script`, "
        "`backend`, `use_login_shell`, and `safe_interval`. Do not emit `username`, `port`, `look_for_keys`, "
        "`key_filename`, `timeout`, `allow_agent`, `proxy_command`, `proxy_jump`, `compress`, `gss_auth`, "
        "`gss_kex`, `gss_deleg_creds`, `gss_host`, `load_system_host_keys`, or `key_policy` for `core.ssh_async`."
        if capabilities.get("supports_async_ssh")
        else "Do not emit `core.ssh_async`; it is not supported by this aiida-core installation."
    )
    return f"""
    You are an AiiDA infrastructure expert. Parse the following text into structured JSON for configuring an AiiDA Computer or Code.

    The active aiida-core version is {capabilities.get("aiida_core_version", "unknown")}.
    The allowed transport types are: {available_transports}.
    The recommended SSH transport is: {capabilities.get("recommended_transport", _SYNC_SSH_TRANSPORT)}.
    {async_rule}

    Input Text:
    {text}

    Output format:
    {{
      "type": "computer" | "code" | "both",
      "computer": {{
        "label": "string",
        "hostname": "string",
        "user": "user@example.com",
        "username": "string",
        "description": "string",
        "transport_type": "allowed transport",
        "scheduler_type": "core.direct" | "core.slurm" | "core.pbspro" | "core.lsf",
        "shebang": "#!/bin/bash",
        "work_dir": "string",
        "mpiprocs_per_machine": number,
        "mpirun_command": "string",
        "default_memory_per_machine": number,
        "use_double_quotes": boolean,
        "prepend_text": "string",
        "append_text": "string",
        "port": number,
        "look_for_keys": boolean,
        "key_filename": "string",
        "timeout": number,
        "allow_agent": boolean,
        "proxy_command": "string",
        "proxy_jump": "string",
        "compress": boolean,
        "gss_auth": boolean,
        "gss_kex": boolean,
        "gss_deleg_creds": boolean,
        "gss_host": "string",
        "load_system_host_keys": boolean,
        "key_policy": "RejectPolicy" | "WarningPolicy" | "AutoAddPolicy",
        "host": "string",
        "max_io_allowed": number,
        "authentication_script": "string",
        "backend": "asyncssh" | "openssh",
        "use_login_shell": boolean,
        "safe_interval": number
      }},
      "code": {{
        "label": "string",
        "description": "string",
        "default_calc_job_plugin": "string",
        "remote_abspath": "string",
        "prepend_text": "string",
        "append_text": "string"
      }}
    }}

    Return ONLY raw JSON. No markdown blocks, no explanations. Omit unknown keys.
    """


async def parse_infrastructure_via_ai(text: str, ssh_host_details: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Parse raw text into AiiDA Computer/Code configuration.
    Structured YAML is handled locally first; free-form text falls back to Gemini.
    """
    cleaned_text = str(text or "").strip()
    capabilities = await _get_infrastructure_capabilities()

    if not cleaned_text and ssh_host_details:
        return _build_ssh_host_parse_result(ssh_host_details, capabilities)

    if ssh_host_details and cleaned_text.lower().startswith("configure computer for ssh host"):
        return _build_ssh_host_parse_result(ssh_host_details, capabilities)

    structured = _parse_structured_infrastructure_text(cleaned_text, capabilities, ssh_host_details)
    if structured is not None:
        return structured

    api_key = settings.GEMINI_API_KEY
    if api_key == "your-key-here":
        raise HTTPException(status_code=400, detail="Gemini API key not configured")

    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": settings.GEMINI_API_VERSION},
    )
    prompt = _build_ai_infrastructure_prompt(cleaned_text, capabilities)

    try:
        response = client.models.generate_content(
            model=settings.DEFAULT_MODEL,
            contents=prompt,
        )
        raw_text = response.text.strip()
        # Basic cleanup if model includes markdown code blocks
        if raw_text.startswith("```"):
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            else:
                raw_text = raw_text.split("```")[1].strip()

        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=422, detail="AI returned an invalid infrastructure payload.")

        normalized = _normalize_structured_infrastructure_payload(parsed, capabilities, ssh_host_details)
        return normalized
    except HTTPException:
        raise
    except Exception as error:
        logger.exception(log_event("aiida.service.parse_infrastructure.failed", error=str(error)))
        raise HTTPException(status_code=500, detail=f"AI Parsing failed: {str(error)}") from error


__all__ = [
    "AiiDAWorkerClient",
    "WorkerConnectionState",
    "WorkerResourceCounts",
    "WorkerSnapshot",
    "aiida_worker_client",
    "AiiDAHub",
    "hub",
    "add_nodes_to_group",
    "create_group",
    "delete_group",
    "export_group_archive",
    "get_context_nodes",
    "get_recent_nodes",
    "list_groups",
    "rename_group",
    "soft_delete_node",
    "parse_infrastructure_via_ai",
]
