from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from loguru import logger

from src.aris_core.config import settings
from src.aris_core.logging import log_event

from .client import aiida_worker_client
from .frontend_bridge import get_context_nodes
from aris_apps.aiida.config import aiida_engine_settings

SPECIALIZATIONS_ROOT = Path(aiida_engine_settings.specializations_root)


def _normalize_text_list(values: Sequence[Any] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized


def _normalize_query_values(values: Sequence[Any] | None) -> list[str]:
    exploded: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if parts:
            exploded.extend(parts)
        else:
            exploded.append(text)
    return _normalize_text_list(exploded)


def _normalize_query_ints(values: Sequence[Any] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        for part in str(value or "").split(","):
            text = part.strip()
            if not text:
                continue
            try:
                parsed = int(text)
            except ValueError:
                continue
            if parsed <= 0 or parsed in seen:
                continue
            seen.add(parsed)
            normalized.append(parsed)
    return normalized


def _normalize_name(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _matches_exact_token(values: set[str], candidates: Sequence[str] | None) -> bool:
    if not values:
        return False
    normalized_values = {value.strip().lower() for value in values if value.strip()}
    if not normalized_values:
        return False
    for candidate in candidates or []:
        text = str(candidate or "").strip().lower()
        if text and text in normalized_values:
            return True
    return False


def _matches_prefix(values: set[str], prefixes: Sequence[str] | None) -> bool:
    if not values:
        return False
    for raw_prefix in prefixes or []:
        prefix = str(raw_prefix or "").strip().lower()
        if not prefix:
            continue
        for value in values:
            if value == prefix or value.startswith(prefix):
                return True
    return False


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(log_event("aiida.specializations.manifest.load_failed", path=str(path), error=str(exc)))
        return None

    if not isinstance(raw, Mapping):
        return None

    name = str(raw.get("name") or path.parent.name).strip().lower()
    label = str(raw.get("label") or name).strip() or name
    actions_raw = raw.get("actions")
    actions: list[dict[str, Any]] = []
    if isinstance(actions_raw, list):
        for index, item in enumerate(actions_raw):
            if not isinstance(item, Mapping):
                continue
            action_id = str(item.get("id") or f"{name}-{index}").strip() or f"{name}-{index}"
            label_text = str(item.get("label") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if not label_text or not prompt:
                continue
            placements = _normalize_query_values(item.get("placements") if isinstance(item.get("placements"), list) else [])
            action = {
                "id": action_id,
                "label": label_text,
                "prompt": prompt,
                "description": str(item.get("description") or "").strip() or None,
                "icon": str(item.get("icon") or "").strip() or None,
                "command": str(item.get("command") or "").strip() or None,
                "section": str(item.get("section") or label).strip() or label,
                "placements": placements or ["toolbar", "slash"],
                "order": int(item.get("order", index)),
                "requires_context_nodes": bool(item.get("requires_context_nodes", False)),
                "requires_context_node_types": _normalize_query_values(item.get("requires_context_node_types")),
                "requires_project_tags": _normalize_query_values(item.get("requires_project_tags")),
                "requires_resource_plugins": _normalize_query_values(item.get("requires_resource_plugins")),
                "requires_worker_plugin_prefixes": _normalize_query_values(item.get("requires_worker_plugin_prefixes")),
            }
            actions.append(action)

    return {
        "name": name,
        "label": label,
        "description": str(raw.get("description") or "").strip() or None,
        "accent": str(raw.get("accent") or "neutral").strip().lower() or "neutral",
        "activation": raw.get("activation") if isinstance(raw.get("activation"), Mapping) else {},
        "actions": sorted(actions, key=lambda item: (int(item.get("order", 0)), str(item.get("label") or ""))),
        "path": str(path),
    }


def _load_all_manifests() -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    if not SPECIALIZATIONS_ROOT.is_dir():
        return manifests

    for path in sorted(SPECIALIZATIONS_ROOT.glob("*/actions.yaml")):
        manifest = _load_manifest(path)
        if manifest:
            manifests.append(manifest)
    return manifests


def _evaluate_rule(rule: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bool, list[str]]:
    mode = str(rule.get("mode") or "").strip().lower()
    if mode == "always":
        return True, ["always"]

    any_of = rule.get("any_of")
    if isinstance(any_of, list):
        for item in any_of:
            if not isinstance(item, Mapping):
                continue
            matched, reasons = _evaluate_rule(item, context)
            if matched:
                return True, reasons
        return False, []

    all_of = rule.get("all_of")
    if isinstance(all_of, list):
        reasons: list[str] = []
        for item in all_of:
            if not isinstance(item, Mapping):
                return False, []
            matched, nested_reasons = _evaluate_rule(item, context)
            if not matched:
                return False, []
            reasons.extend(nested_reasons)
        return True, reasons
    if isinstance(all_of, Mapping):
        return _evaluate_rule(all_of, context)

    context_node_types = set(context.get("context_node_types", []))
    project_tags = set(context.get("project_tags", []))
    resource_plugins = set(context.get("resource_plugins", []))
    worker_plugins = set(context.get("worker_plugins", []))

    checks: list[tuple[bool, str]] = []

    if "context_node_types" in rule:
        checks.append((
            _matches_exact_token(context_node_types, _normalize_query_values(rule.get("context_node_types"))),
            "context_node_types",
        ))
    if "project_tags" in rule:
        checks.append((
            _matches_exact_token(project_tags, _normalize_query_values(rule.get("project_tags"))),
            "project_tags",
        ))
    if "resource_plugins" in rule:
        checks.append((
            _matches_prefix(resource_plugins, _normalize_query_values(rule.get("resource_plugins"))),
            "resource_plugins",
        ))
    if "worker_plugin_prefixes" in rule:
        checks.append((
            _matches_prefix(worker_plugins, _normalize_query_values(rule.get("worker_plugin_prefixes"))),
            "worker_plugin_prefixes",
        ))

    if not checks:
        return False, []

    return all(matched for matched, _ in checks), [reason for matched, reason in checks if matched]


def _evaluate_action_enablement(action: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bool, str | None]:
    context_node_types = set(context.get("context_node_types", []))
    project_tags = set(context.get("project_tags", []))
    resource_plugins = set(context.get("resource_plugins", []))
    worker_plugins = set(context.get("worker_plugins", []))
    worker_plugins_available = bool(context.get("worker_plugins_available", False))
    context_node_ids = context.get("context_node_ids", [])

    if action.get("requires_context_nodes") and not context_node_ids:
        return False, "Select context nodes to use this action."
    required_types = _normalize_query_values(action.get("requires_context_node_types"))
    if required_types and not _matches_exact_token(context_node_types, required_types):
        return False, f"Requires context node types: {', '.join(required_types)}."
    required_tags = _normalize_query_values(action.get("requires_project_tags"))
    if required_tags and not _matches_exact_token(project_tags, required_tags):
        return False, f"Requires project tags: {', '.join(required_tags)}."
    required_resource_plugins = _normalize_query_values(action.get("requires_resource_plugins"))
    if required_resource_plugins and not _matches_prefix(resource_plugins, required_resource_plugins):
        return False, "Attach a matching plugin or code resource first."
    required_worker_plugins = _normalize_query_values(action.get("requires_worker_plugin_prefixes"))
    if required_worker_plugins and worker_plugins_available and not _matches_prefix(worker_plugins, required_worker_plugins):
        return False, "The current worker does not expose the required plugin."
    return True, None


def _build_action_payload(manifest: Mapping[str, Any], action: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    enabled, disabled_reason = _evaluate_action_enablement(action, context)
    command = str(action.get("command") or "").strip() or None
    if command and not command.startswith("/"):
        command = f"/{command.lstrip('/')}"
    return {
        "id": str(action.get("id") or "").strip(),
        "label": str(action.get("label") or "").strip(),
        "prompt": str(action.get("prompt") or "").strip(),
        "description": action.get("description"),
        "icon": action.get("icon"),
        "command": command,
        "section": str(action.get("section") or manifest.get("label") or "").strip() or str(manifest.get("label") or ""),
        "placements": list(action.get("placements") or []),
        "specialization": str(manifest.get("name") or "").strip(),
        "specialization_label": str(manifest.get("label") or "").strip(),
        "accent": str(manifest.get("accent") or "neutral").strip(),
        "variant": "general" if str(manifest.get("name") or "").strip() == "general" else "specialized",
        "enabled": enabled,
        "disabled_reason": disabled_reason,
    }


async def build_active_specializations_payload(
    *,
    context_node_ids: Sequence[Any] | None = None,
    project_tags: Sequence[Any] | None = None,
    resource_plugins: Sequence[Any] | None = None,
    selected_environment: str | None = None,
    auto_switch: bool = True,
) -> dict[str, Any]:
    normalized_node_ids = _normalize_query_ints(context_node_ids)
    normalized_project_tags = [value.lower() for value in _normalize_query_values(project_tags)]
    normalized_resource_plugins = [value.lower() for value in _normalize_query_values(resource_plugins)]
    normalized_selected_environment = _normalize_name(selected_environment)
    auto_switch_enabled = bool(auto_switch)

    context_nodes = get_context_nodes(normalized_node_ids)
    context_node_types = sorted(
        {
            str(item.get("node_type") or "").strip()
            for item in context_nodes
            if isinstance(item, Mapping) and str(item.get("node_type") or "").strip()
        }
    )

    worker_plugins: list[str] = []
    worker_plugins_available = False
    try:
        worker_plugins = [plugin.lower() for plugin in await aiida_worker_client.get_plugins(force_refresh=False)]
        worker_plugins_available = True
        if not worker_plugins:
            worker_plugins = [plugin.lower() for plugin in await aiida_worker_client.get_plugins(force_refresh=True)]
    except Exception as exc:  # noqa: BLE001
        logger.warning(log_event("aiida.specializations.plugins.fetch_failed", error=str(exc)))
        worker_plugins = []
        worker_plugins_available = False

    context_payload = {
        "context_node_ids": normalized_node_ids,
        "context_node_types": context_node_types,
        "project_tags": normalized_project_tags,
        "resource_plugins": normalized_resource_plugins,
        "worker_plugins": worker_plugins,
        "worker_plugins_available": worker_plugins_available,
    }

    manifests = _load_all_manifests()
    manifest_names = {_normalize_name(item.get("name")) for item in manifests}
    selected_environment_name = (
        normalized_selected_environment if normalized_selected_environment in manifest_names else None
    )
    active_specializations: list[dict[str, Any]] = []
    inactive_specializations: list[dict[str, Any]] = []
    chip_actions: list[dict[str, Any]] = []
    slash_sections: dict[str, list[dict[str, Any]]] = {}
    resolved_environment = "general"

    for manifest in manifests:
        activation = manifest.get("activation") if isinstance(manifest.get("activation"), Mapping) else {}
        manifest_name = _normalize_name(manifest.get("name")) or ""
        is_active, reasons = _evaluate_rule(activation, context_payload)
        if not auto_switch_enabled and manifest_name != "general":
            is_active = manifest_name == selected_environment_name
            reasons = ["manual_selection"] if is_active else []
        summary = {
            "name": str(manifest.get("name") or "").strip(),
            "label": str(manifest.get("label") or "").strip(),
            "description": manifest.get("description"),
            "accent": str(manifest.get("accent") or "neutral").strip(),
            "variant": "general" if manifest_name == "general" else "specialized",
            "active": is_active,
            "reasons": reasons,
        }
        if is_active:
            active_specializations.append(summary)
            if manifest_name and manifest_name != "general" and resolved_environment == "general":
                resolved_environment = manifest_name
            for action in manifest.get("actions", []):
                if not isinstance(action, Mapping):
                    continue
                payload = _build_action_payload(manifest, action, context_payload)
                placements = set(payload.get("placements") or [])
                if "toolbar" in placements:
                    chip_actions.append(payload)
                if "slash" in placements:
                    section = str(payload.get("section") or "Commands").strip() or "Commands"
                    slash_sections.setdefault(section, []).append(payload)
        else:
            inactive_specializations.append(summary)

    if not auto_switch_enabled and selected_environment_name:
        resolved_environment = selected_environment_name

    chip_actions.sort(
        key=lambda item: (
            0 if item.get("variant") == "general" else 1,
            0 if item.get("enabled") else 1,
            str(item.get("specialization_label") or ""),
            str(item.get("label") or ""),
        )
    )

    slash_menu = [
        {
            "id": section.lower().replace(" ", "-"),
            "label": section,
            "items": sorted(
                items,
                key=lambda item: (
                    0 if item.get("variant") == "general" else 1,
                    0 if item.get("enabled") else 1,
                    str(item.get("label") or ""),
                ),
            ),
        }
        for section, items in sorted(slash_sections.items(), key=lambda item: item[0].lower())
    ]

    return {
        "chips": chip_actions,
        "slash_menu": slash_menu,
        "active_specializations": active_specializations,
        "inactive_specializations": inactive_specializations,
        "environment": {
            "selected": selected_environment_name,
            "resolved": resolved_environment,
            "auto_switch": auto_switch_enabled,
        },
        "context": {
            "context_node_ids": normalized_node_ids,
            "context_node_types": context_node_types,
            "project_tags": normalized_project_tags,
            "resource_plugins": normalized_resource_plugins,
            "worker_plugins": worker_plugins,
            "worker_plugins_available": worker_plugins_available,
        },
    }


__all__ = ["build_active_specializations_payload"]
