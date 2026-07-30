from __future__ import annotations

from contextlib import suppress
from typing import Any


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def extract_submitted_pk(payload: Any) -> int | None:
    if isinstance(payload, bool) or payload is None:
        return None
    if isinstance(payload, (int, str)):
        return _coerce_int(payload)
    if isinstance(payload, list):
        for item in payload:
            candidate = extract_submitted_pk(item)
            if candidate is not None:
                return candidate
        return None

    if not isinstance(payload, dict):
        return None

    primary_keys = (
        "process_pk",
        "submitted_pk",
        "workflow_pk",
        "process_id",
        "process_node_pk",
        "pk",
        "id",
    )
    for key in primary_keys:
        candidate = _coerce_int(payload.get(key))
        if candidate is not None:
            return candidate

    array_keys = ("submitted_pks", "process_pks", "workflow_pks", "pks")
    for key in array_keys:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            candidate = _coerce_int(item)
            if candidate is not None:
                return candidate

    for key in ("submission", "result", "data"):
        if key not in payload:
            continue
        candidate = extract_submitted_pk(payload.get(key))
        if candidate is not None:
            return candidate

    return None


def format_single_submission_response(raw: Any) -> dict[str, Any]:
    response = raw if isinstance(raw, dict) else {"result": raw}
    submitted_pk = extract_submitted_pk(response)
    response["submitted_pks"] = [submitted_pk] if submitted_pk is not None else []
    response["process_pks"] = [submitted_pk] if submitted_pk is not None else []
    return response


def format_batch_submission_response(
    submitted_pks: list[int],
    responses: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "SUBMITTED_BATCH",
        "submitted_pks": submitted_pks,
        "process_pks": submitted_pks,
        "responses": responses,
        "failures": failures,
    }


def format_worker_batch_submission_response(raw: Any) -> dict[str, Any]:
    response = raw if isinstance(raw, dict) else {"result": raw}

    submitted_pks: list[int] = []
    for candidate in response.get("submitted_pks", []):
        parsed = _coerce_int(candidate)
        if parsed is not None:
            submitted_pks.append(parsed)

    responses = _as_dict_list(response.get("responses"))
    failures = _as_dict_list(response.get("failures"))

    if not submitted_pks:
        for item in responses:
            candidate = extract_submitted_pk(item.get("response", item))
            if candidate is not None:
                submitted_pks.append(candidate)

    formatted = format_batch_submission_response(submitted_pks, responses, failures)
    if "status" in response and response.get("status") not in (None, ""):
        formatted["status"] = str(response.get("status"))
    for key in ("total", "submitted_count", "failed_count", "batch_context", "auto_groups"):
        if key in response:
            formatted[key] = response.get(key)
    return formatted


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            items.append(entry)
    return items


def _normalize_key(value: Any) -> str:
    return str(value).strip().lower()


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _find_first_named_value(payload: Any, candidate_keys: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = _normalize_key(key)
            if lowered in candidate_keys and not _is_empty_value(value):
                return value
            nested = _find_first_named_value(value, candidate_keys)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for entry in payload:
            nested = _find_first_named_value(entry, candidate_keys)
            if nested is not None:
                return nested
    return None


def _looks_like_code_key(key: Any) -> bool:
    lowered = _normalize_key(key)
    return lowered in {"code", "code_label", "codes"} or lowered.endswith("_code")


def _flatten_input_ports(payload: Any, *, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    flattened = out if isinstance(out, dict) else {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_node_metadata_envelope(value):
                flattened[path] = _coerce_node_envelope_value(value)
                continue
            if isinstance(value, dict):
                _flatten_input_ports(value, prefix=path, out=flattened)
                continue
            flattened[path] = value
        return flattened

    if prefix:
        flattened[prefix] = payload
    return flattened


def _is_node_metadata_envelope(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    lowered_keys = {str(key).strip().lower() for key in value.keys() if str(key).strip()}
    if not lowered_keys:
        return False
    if {"pk", "uuid"} & lowered_keys:
        return True
    if "type" in lowered_keys and "value" in lowered_keys:
        return True
    return bool({"node_type", "full_type"} & lowered_keys)


def _coerce_node_envelope_value(value: dict[str, Any]) -> Any:
    for candidate_key in ("value", "payload", "label", "name", "full_label", "code", "family"):
        if candidate_key not in value:
            continue
        candidate = value.get(candidate_key)
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return candidate
    return value


def _merge_builder_inputs_into_inputs(inputs: dict[str, Any], builder_inputs: dict[str, Any]) -> dict[str, Any]:
    for key, builder_value in list(builder_inputs.items()):
        current_value = inputs.get(key, None)
        if isinstance(current_value, dict) and isinstance(builder_value, dict):
            if _is_node_metadata_envelope(current_value) and not _is_node_metadata_envelope(builder_value):
                inputs[key] = builder_value
                continue
            _merge_builder_inputs_into_inputs(current_value, builder_value)
            continue
        if key not in inputs or current_value is None or _is_node_metadata_envelope(current_value):
            inputs[key] = builder_value
    return inputs


def _build_all_inputs(
    inputs: dict[str, Any],
    recommended_inputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    flattened = _flatten_input_ports(inputs)
    recommended_set = {_normalize_key(key) for key in recommended_inputs.keys() if _normalize_key(key)}
    all_inputs: dict[str, dict[str, Any]] = {}

    for path, value in flattened.items():
        normalized_path = _normalize_key(path)
        leaf = normalized_path.rsplit(".", 1)[-1]
        is_recommended = normalized_path in recommended_set or leaf in recommended_set
        all_inputs[path] = {
            "value": value,
            "is_recommended": is_recommended,
            "ui_type": _infer_ui_type(path, value),
        }

    return all_inputs


_INPUT_GROUP_ORDER = (
    "computational_details",
    "brillouin_zone",
    "system_environment",
    "physics_protocol",
)

_INPUT_GROUP_TITLE = {
    "computational_details": "Computational Details",
    "brillouin_zone": "Brillouin Zone",
    "system_environment": "System Environment",
    "physics_protocol": "Physics Protocol",
}


def _format_label(value: str) -> str:
    return value.replace("_", " ").replace(".", " ").strip().title()


def _looks_like_mesh_path(path: str) -> bool:
    lowered = _normalize_key(path)
    if "kpoint" not in lowered and "kpoints" not in lowered:
        return False
    return lowered.endswith(".mesh") or ".mesh." in lowered or lowered.endswith("_mesh")


def _is_mesh_triplet(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    for item in value:
        if isinstance(item, bool):
            return False
        if not isinstance(item, (int, float)):
            return False
    return True


def _infer_ui_type(path: str, value: Any) -> str:
    if _looks_like_mesh_path(path) or _is_mesh_triplet(value):
        return "mesh"
    if isinstance(value, bool):
        return "toggle"
    if isinstance(value, (dict, list)):
        return "dict"
    return "scalar"


def _classify_port_group(path: str) -> str:
    lowered = _normalize_key(path)
    leaf = lowered.rsplit(".", 1)[-1]

    if (
        "metadata.options" in lowered
        or ".resources." in lowered
        or leaf in {"resources", "metadata_options", "max_wallclock_seconds", "queue_name", "account"}
    ):
        return "system_environment"
    if "kpoint" in lowered or "kpoints" in lowered or leaf in {"mesh", "kpoints_distance", "kpoint_distance"}:
        return "brillouin_zone"
    if any(
        token in lowered
        for token in (
            "relax_type",
            "protocol",
            "pseudo_family",
            "pseudopotential",
            "electronic_type",
            "spin_type",
        )
    ):
        return "physics_protocol"
    if ".parameters" in lowered or lowered.startswith("parameters"):
        return "computational_details"
    return "computational_details"


def _derive_port_path(path: str, group_id: str) -> str:
    segments = [segment for segment in str(path).split(".") if segment]
    lowered = [segment.lower() for segment in segments]

    if group_id == "system_environment":
        for index in range(len(segments) - 1):
            if lowered[index] == "metadata" and lowered[index + 1] == "options":
                base = segments[: index + 2]
                if index + 2 < len(segments) and lowered[index + 2] == "resources":
                    base.append(segments[index + 2])
                return ".".join(base)
        for index, segment in enumerate(lowered):
            if segment in {"resources", "queue_name", "max_wallclock_seconds", "account"}:
                return ".".join(segments[: index + 1])

    if group_id == "computational_details":
        for index, segment in enumerate(lowered):
            if segment == "parameters":
                return ".".join(segments[: index + 1])

    if group_id == "brillouin_zone":
        for index, segment in enumerate(lowered):
            if "kpoint" in segment:
                return ".".join(segments[: index + 1])
        for index, segment in enumerate(lowered):
            if segment == "mesh":
                return ".".join(segments[: index + 1])

    if group_id == "physics_protocol":
        for index, segment in enumerate(lowered):
            if segment in {"relax_type", "protocol", "pseudo_family", "pseudo_family_label"}:
                return ".".join(segments[: index + 1])

    if len(segments) <= 1:
        return path
    return ".".join(segments[:-1])


def _editor_hint(path: str, ui_type: str) -> str | None:
    lowered = _normalize_key(path)
    if ui_type == "mesh":
        return "mesh"
    if "metadata.options.resources" in lowered:
        return "resource_grid"
    if ui_type == "dict":
        return "property_grid"
    return None


def _build_input_groups(all_inputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_ports: dict[tuple[str, str], dict[str, Any]] = {}

    for path, raw_entry in all_inputs.items():
        entry = _as_dict(raw_entry) or {"value": raw_entry}
        value = entry.get("value")
        is_recommended = bool(entry.get("is_recommended"))
        ui_type = str(entry.get("ui_type") or _infer_ui_type(path, value))
        group_id = _classify_port_group(path)
        port_path = _derive_port_path(path, group_id)
        port_key = (group_id, port_path)
        port = grouped_ports.get(port_key)
        if port is None:
            port = {
                "path": port_path,
                "label": _format_label(port_path.split(".")[-1] if "." in port_path else port_path),
                "ui_type": "dict",
                "editor_hint": None,
                "is_recommended": False,
                "properties": [],
            }
            grouped_ports[port_key] = port

        property_key = path[len(port_path) :].lstrip(".") if path.startswith(f"{port_path}.") else path
        property_label = _format_label(property_key.split(".")[-1] if property_key else path.split(".")[-1])
        port["properties"].append(
            {
                "path": path,
                "key": property_key or path,
                "label": property_label,
                "value": value,
                "ui_type": ui_type,
                "editor_hint": _editor_hint(path, ui_type),
                "is_recommended": is_recommended,
            }
        )
        if is_recommended:
            port["is_recommended"] = True
        if ui_type == "mesh":
            port["ui_type"] = "mesh"
        elif len(port["properties"]) == 1:
            port["ui_type"] = ui_type
        else:
            port["ui_type"] = "dict"
        port["editor_hint"] = _editor_hint(port_path, str(port["ui_type"]))

    grouped_payload: list[dict[str, Any]] = []
    for group_id in _INPUT_GROUP_ORDER:
        ports = [
            value
            for (entry_group_id, _), value in grouped_ports.items()
            if entry_group_id == group_id and value.get("properties")
        ]
        if not ports:
            continue
        for port in ports:
            properties = port.get("properties")
            if isinstance(properties, list):
                properties.sort(key=lambda item: str(item.get("key") or ""))
        ports.sort(key=lambda port_entry: str(port_entry.get("path") or ""))
        grouped_payload.append(
            {
                "id": group_id,
                "title": _INPUT_GROUP_TITLE[group_id],
                "ports": ports,
            }
        )
    return grouped_payload


def _extract_symmetry(payload: Any) -> str | None:
    symmetry = _find_first_named_value(
        payload,
        {
            "symmetry",
            "symmetry_label",
            "spacegroup",
            "space_group",
            "space_group_symbol",
            "international_symbol",
            "crystal_system",
            "spglib",
        },
    )
    if isinstance(symmetry, dict):
        for key in (
            "international_symbol",
            "space_group_symbol",
            "spacegroup",
            "symbol",
            "crystal_system",
            "label",
            "name",
            "hall_symbol",
        ):
            value = symmetry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        number = _coerce_int(symmetry.get("number"))
        if number is not None:
            return f"Space group {number}"
        return None

    if isinstance(symmetry, str) and symmetry.strip():
        return symmetry.strip()
    number = _coerce_int(symmetry)
    if number is not None:
        return f"Space group {number}"
    return None


def _extract_estimated_runtime(payload: Any) -> Any:
    return _find_first_named_value(
        payload,
        {
            "estimated_runtime",
            "estimated_runtime_seconds",
            "runtime_estimate",
            "runtime_prediction",
            "runtime_seconds",
            "time_estimate",
            "time_estimate_seconds",
            "predicted_runtime_seconds",
            "max_wallclock_seconds",
        },
    )


def _extract_num_atoms(payload: Any) -> int | None:
    value = _find_first_named_value(
        payload,
        {
            "num_atoms",
            "natoms",
            "number_of_atoms",
            "sites",
            "nsites",
            "sites_count",
        },
    )
    return _coerce_int(value)


def _extract_structure_metadata_entries(submission_draft: dict[str, Any]) -> list[dict[str, Any]]:
    meta = _as_dict(submission_draft.get("meta")) or {}
    candidates: list[dict[str, Any]] = []

    meta_draft = meta.get("draft")
    if isinstance(meta_draft, dict):
        candidates.append(meta_draft)
    elif isinstance(meta_draft, list):
        candidates.extend(_as_dict_list(meta_draft))

    inputs = _as_dict(submission_draft.get("inputs")) or {}
    for key in ("jobs", "tasks", "submissions", "drafts"):
        candidates.extend(_as_dict_list(inputs.get(key)))

    if not candidates:
        candidates.append(inputs)

    entries: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for index, candidate in enumerate(candidates):
        structure_value = _find_first_named_value(
            candidate,
            {"structure_pk", "structure_id", "structure", "pk"},
        )
        structure_record = _as_dict(structure_value)
        pk = (
            _coerce_int(structure_record.get("pk") if isinstance(structure_record, dict) else None)
            or _coerce_int(structure_record.get("structure_pk") if isinstance(structure_record, dict) else None)
            or _coerce_int(structure_value)
        )
        formula_value = _find_first_named_value(
            candidate,
            {"formula", "structure_label", "label", "name", "structure_name"},
        )
        formula = str(formula_value).strip() if isinstance(formula_value, str) and formula_value.strip() else None
        if formula is None and pk is not None:
            formula = f"Structure #{pk}"
        if formula is None:
            formula = f"Task {index + 1}"

        symmetry = _extract_symmetry(candidate)
        num_atoms = _extract_num_atoms(candidate)
        estimated_runtime = _extract_estimated_runtime(candidate)

        dedupe_key = (pk, formula)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        entries.append(
            {
                "pk": pk,
                "formula": formula,
                "symmetry": symmetry,
                "num_atoms": num_atoms,
                "estimated_runtime": estimated_runtime,
            }
        )

    return entries


def _extract_messages(payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    raw_messages: list[str] = []
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = item.get("message") or item.get("error") or item.get("detail") or item.get("reason")
                    raw_messages.append(str(text if text is not None else item))
                else:
                    raw_messages.append(str(item))
            continue
        if isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, list):
                    raw_messages.extend(str(entry) for entry in nested)
                else:
                    raw_messages.append(str(nested))
            continue
        raw_messages.append(str(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for message in raw_messages:
        cleaned = message.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _build_validation_summary(
    validation: dict[str, Any] | None,
    existing_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(validation, dict) and not isinstance(existing_summary, dict):
        return None

    summary_seed = dict(existing_summary) if isinstance(existing_summary, dict) else {}
    validation_payload = validation if isinstance(validation, dict) else {}
    errors = summary_seed.get("errors")
    warnings = summary_seed.get("warnings")
    if not isinstance(errors, list):
        errors = _extract_messages(
            validation_payload,
            ("error", "errors", "validation_errors", "blocking_errors", "missing_inputs", "missing"),
        )
    else:
        errors = [str(item).strip() for item in errors if str(item).strip()]

    if not isinstance(warnings, list):
        warnings = _extract_messages(
            validation_payload,
            ("warnings", "validation_warnings", "non_blocking_warnings"),
        )
    else:
        warnings = [str(item).strip() for item in warnings if str(item).strip()]

    status_raw = summary_seed.get("status", validation_payload.get("status"))
    status = str(status_raw).strip() if status_raw is not None else ""
    status_upper = status.upper()
    is_valid_field = summary_seed.get("is_valid", validation_payload.get("is_valid"))
    if isinstance(is_valid_field, bool):
        is_valid = is_valid_field
    elif status_upper in {"VALID", "VALIDATION_OK", "OK", "SUCCESS", "PASSED"}:
        is_valid = True
    elif status_upper in {"INVALID", "VALIDATION_FAILED", "FAILED", "ERROR"}:
        is_valid = False
    else:
        is_valid = len(errors) == 0

    normalized_status = status or ("VALIDATION_OK" if is_valid else "VALIDATION_FAILED")
    blocking_error_count_raw = summary_seed.get("blocking_error_count")
    warning_count_raw = summary_seed.get("warning_count")
    try:
        blocking_error_count = int(blocking_error_count_raw) if blocking_error_count_raw is not None else len(errors)
    except (TypeError, ValueError):
        blocking_error_count = len(errors)
    try:
        warning_count = int(warning_count_raw) if warning_count_raw is not None else len(warnings)
    except (TypeError, ValueError):
        warning_count = len(warnings)

    summary_lines = [
        f"Status: {normalized_status}",
        f"Valid: {'yes' if is_valid else 'no'}",
        f"Blocking errors: {blocking_error_count}",
        f"Warnings: {warning_count}",
    ]
    if errors:
        summary_lines.append(f"Top error: {errors[0]}")
    if warnings:
        summary_lines.append(f"Top warning: {warnings[0]}")

    preserved = {
        str(key): value
        for key, value in summary_seed.items()
        if str(key) not in {"status", "is_valid", "blocking_error_count", "warning_count", "errors", "warnings", "summary_text"}
    }

    return {
        **preserved,
        "status": normalized_status,
        "is_valid": is_valid,
        "blocking_error_count": max(0, blocking_error_count),
        "warning_count": max(0, warning_count),
        "errors": errors,
        "warnings": warnings,
        "summary_text": str(summary_seed.get("summary_text") or "\n".join(summary_lines)),
    }


def _extract_candidate_entry_points(payload: dict[str, Any]) -> list[str]:
    meta = _as_dict(payload.get("meta")) or {}
    entry_points: list[str] = []
    for candidate in (
        meta.get("workchain"),
        meta.get("workchain_entry_point"),
        meta.get("entry_point"),
        payload.get("workchain"),
        payload.get("workchain_entry_point"),
        payload.get("entry_point"),
        payload.get("process_label"),
    ):
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip()
        if cleaned and cleaned not in entry_points:
            entry_points.append(cleaned)
    return entry_points


def _expand_entry_point_candidates(entry_points: list[str]) -> list[str]:
    expanded: list[str] = []

    def append(value: str | None) -> None:
        if not isinstance(value, str):
            return
        cleaned = value.strip()
        if not cleaned or cleaned in expanded:
            return
        expanded.append(cleaned)

    for entry_point in entry_points:
        append(entry_point)
        normalized = entry_point.strip()
        if ":" in normalized:
            append(normalized.split(":", 1)[1])
        stripped = normalized.replace("aiida.workflows:", "").strip()
        if stripped and stripped != normalized:
            append(stripped)

    return expanded


def _extract_declared_code_plugin(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("plugin", "default_plugin", "default_calc_job_plugin", "input_plugin"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None
    plugin = getattr(value, "default_calc_job_plugin", None)
    if isinstance(plugin, str) and plugin.strip():
        return plugin.strip()
    return None


def _infer_code_plugin_from_entry_point(entry_point: Any) -> str | None:
    if not isinstance(entry_point, str):
        return None
    cleaned = entry_point.strip()
    if not cleaned:
        return None
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()
    segments = [segment.strip() for segment in cleaned.split(".") if segment.strip()]
    if len(segments) < 3:
        return None
    return ".".join(segments[:2])


def _resolve_required_code_plugin(
    entry_points: list[str],
    inputs: dict[str, Any],
    port_spec: dict[str, Any] | None,
) -> str | None:
    candidates: list[str] = []
    seen: set[str] = set()
    flattened = _flatten_input_ports(inputs)
    if isinstance(port_spec, dict):
        code_paths = port_spec.get("code_paths")
        if isinstance(code_paths, list):
            for path in code_paths:
                if not isinstance(path, str):
                    continue
                plugin = _extract_declared_code_plugin(flattened.get(path))
                normalized = _normalize_key(plugin)
                if plugin and normalized not in seen:
                    seen.add(normalized)
                    candidates.append(plugin)

    for path, value in flattened.items():
        leaf = _normalize_key(path.rsplit(".", 1)[-1])
        if not _looks_like_code_key(leaf):
            continue
        plugin = _extract_declared_code_plugin(value)
        normalized = _normalize_key(plugin)
        if plugin and normalized not in seen:
            seen.add(normalized)
            candidates.append(plugin)
    if candidates:
        return candidates[0]

    for entry_point in [*entry_points, port_spec.get("entry_point") if isinstance(port_spec, dict) else None]:
        plugin = _infer_code_plugin_from_entry_point(entry_point)
        normalized = _normalize_key(plugin)
        if plugin and normalized not in seen:
            seen.add(normalized)
            candidates.append(plugin)

    if candidates:
        return candidates[0]
    return None


def _build_port_spec_from_inputs(entry_points: list[str], inputs: dict[str, Any]) -> dict[str, Any] | None:
    flattened = _flatten_input_ports(inputs)
    namespace_paths: set[str] = set()
    code_paths: set[str] = set()

    for path in flattened.keys():
        segments = [segment for segment in str(path).split(".") if segment]
        for index in range(1, len(segments)):
            namespace_paths.add(".".join(segments[:index]))
        leaf = segments[-1].lower() if segments else ""
        if leaf == "code" or leaf.endswith("_code"):
            code_paths.add(path)

    lowered_entry_points = [_normalize_key(entry_point) for entry_point in entry_points]
    if any(path.startswith("metadata.") for path in flattened.keys()):
        namespace_paths.update({"metadata", "metadata.options", "metadata.options.resources"})

    if not namespace_paths and not code_paths:
        return None

    ports = [
        {
            "path": code_path,
            "kind": "code",
            "required": False,
            "valid_types": [],
        }
        for code_path in sorted(code_paths)
    ]
    return {
        "entry_point": entry_points[0] if entry_points else None,
        "namespaces": sorted(namespace_paths),
        "ports": ports,
        "code_paths": sorted(code_paths),
    }


def _is_plugin_compatible(plugin: str | None, required_plugin: str | None) -> bool:
    if not required_plugin:
        return False
    if not isinstance(plugin, str):
        return False
    normalized_plugin = plugin.strip().lower()
    normalized_required = required_plugin.strip().lower()
    if not normalized_plugin or not normalized_required:
        return False
    return normalized_plugin == normalized_required or normalized_plugin.startswith(f"{normalized_required}.")


def _sort_available_codes(
    items: list[dict[str, Any]],
    required_plugin: str | None,
) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        if not required_plugin:
            return (0, str(item.get("label") or ""))
        if item.get("is_compatible") is True:
            return (0, str(item.get("label") or ""))
        plugin_value = item.get("plugin")
        if isinstance(plugin_value, str) and plugin_value.strip():
            return (2, str(item.get("label") or ""))
        return (1, str(item.get("label") or ""))

    return sorted(items, key=sort_key)


def _query_available_codes(required_plugin: str | None) -> list[dict[str, Any]]:
    try:
        from src.aris_apps.aiida.client import aiida_worker_client
    except Exception:
        return []

    try:
        payload = aiida_worker_client.call_sync("resource.summary", timeout=0.8)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, list):
        return []

    available_codes: list[dict[str, Any]] = []
    seen_values: set[str] = set()
    for raw_code in raw_codes:
        if isinstance(raw_code, str):
            value_text = raw_code.strip()
            if not value_text or value_text in seen_values:
                continue
            seen_values.add(value_text)
            available_codes.append(
                {
                    "value": value_text,
                    "label": value_text,
                    "code_label": value_text.split("@", 1)[0].strip() or value_text,
                    "computer_label": value_text.split("@", 1)[1].strip() if "@" in value_text else None,
                    "plugin": None,
                    "pk": None,
                    "is_compatible": False,
                }
            )
            continue

        if not isinstance(raw_code, dict):
            continue

        label = str(raw_code.get("code_label") or raw_code.get("label") or "").strip()
        computer_label_raw = raw_code.get("computer_label") or raw_code.get("computer")
        computer_label = str(computer_label_raw).strip() if computer_label_raw is not None else ""
        full_label = str(raw_code.get("full_label") or raw_code.get("value") or "").strip()

        value = full_label
        if not value and label:
            value = f"{label}@{computer_label}" if computer_label else label
        if not value:
            continue

        if value in seen_values:
            continue
        seen_values.add(value)

        plugin_raw = (
            raw_code.get("plugin")
            or raw_code.get("default_plugin")
            or raw_code.get("default_calc_job_plugin")
            or raw_code.get("input_plugin")
        )
        plugin = str(plugin_raw).strip() if isinstance(plugin_raw, str) else None
        pk = _coerce_int(raw_code.get("pk") or raw_code.get("id"))
        is_compatible = _is_plugin_compatible(plugin, required_plugin)

        available_codes.append(
            {
                "value": value,
                "label": str(raw_code.get("label") or value).strip() or value,
                "code_label": label or value.split("@", 1)[0].strip() or value,
                "computer_label": computer_label or (value.split("@", 1)[1].strip() if "@" in value else None),
                "plugin": plugin,
                "pk": pk,
                "is_compatible": is_compatible,
            }
        )

    return _sort_available_codes(available_codes, required_plugin)


def _collect_available_codes_from_inputs(
    inputs: dict[str, Any],
    required_plugin: str | None,
) -> list[dict[str, Any]]:
    flattened = _flatten_input_ports(inputs)
    available_codes: list[dict[str, Any]] = []
    seen_values: set[str] = set()

    for path, raw_value in flattened.items():
        lowered_path = _normalize_key(path)
        leaf = lowered_path.rsplit(".", 1)[-1]
        if not _looks_like_code_key(leaf):
            continue

        value_text = ""
        code_label = ""
        computer_label: str | None = None
        plugin: str | None = required_plugin

        if isinstance(raw_value, dict):
            value_text = str(
                raw_value.get("value")
                or raw_value.get("label")
                or raw_value.get("full_label")
                or raw_value.get("code")
                or ""
            ).strip()
            code_label = str(raw_value.get("code_label") or raw_value.get("label") or "").strip()
            candidate_computer = raw_value.get("computer_label") or raw_value.get("computer")
            if isinstance(candidate_computer, str) and candidate_computer.strip():
                computer_label = candidate_computer.strip()
            candidate_plugin = raw_value.get("plugin") or raw_value.get("default_calc_job_plugin")
            if isinstance(candidate_plugin, str) and candidate_plugin.strip():
                plugin = candidate_plugin.strip()
        elif isinstance(raw_value, str):
            value_text = raw_value.strip()

        if not value_text and code_label and computer_label:
            value_text = f"{code_label}@{computer_label}"
        elif not value_text and code_label:
            value_text = code_label
        if not code_label and value_text:
            code_label = value_text.split("@", 1)[0].strip()
        if not computer_label and "@" in value_text:
            candidate = value_text.split("@", 1)[1].strip()
            computer_label = candidate or None
        if not value_text:
            continue

        if required_plugin and plugin and not _is_plugin_compatible(plugin, required_plugin):
            continue
        if value_text in seen_values:
            continue
        seen_values.add(value_text)
        available_codes.append(
            {
                "value": value_text,
                "label": value_text,
                "code_label": code_label or value_text,
                "computer_label": computer_label,
                "plugin": plugin,
                "pk": None,
            }
        )

    available_codes.sort(key=lambda item: str(item.get("label") or ""))
    return available_codes


def enrich_submission_draft_payload(submission_draft: dict[str, Any]) -> dict[str, Any]:
    payload = dict(submission_draft)
    
    meta = _as_dict(payload.get("meta"))
    if meta is None:
        meta = {}
        payload["meta"] = meta

    inputs = _as_dict(payload.get("inputs")) or {}
    existing_all_inputs = _as_dict(payload.get("all_inputs")) or _as_dict(meta.get("all_inputs"))
    existing_input_groups = payload.get("input_groups")
    if not isinstance(existing_input_groups, list):
        meta_input_groups = meta.get("input_groups")
        existing_input_groups = meta_input_groups if isinstance(meta_input_groups, list) else None
    
    validation = _as_dict(meta.get("validation"))
            
    builder_inputs: dict[str, Any] | None = None
    if isinstance(validation, dict) and isinstance(validation.get("builder_inputs"), dict):
        builder_inputs = validation["builder_inputs"]
    elif isinstance(meta.get("draft"), dict) and isinstance(meta["draft"].get("builder_inputs"), dict):
        builder_inputs = meta["draft"]["builder_inputs"]
        
    if builder_inputs:
        _merge_builder_inputs_into_inputs(inputs, builder_inputs)
        payload["inputs"] = inputs

    recommended_inputs = _as_dict(payload.get("recommended_inputs"))
    if recommended_inputs is None:
        recommended_inputs = _as_dict(payload.get("advanced_settings")) or {}
        payload["recommended_inputs"] = recommended_inputs

    derived_all_inputs = _build_all_inputs(inputs, recommended_inputs)
    if derived_all_inputs:
        payload["all_inputs"] = derived_all_inputs
        payload["input_groups"] = _build_input_groups(derived_all_inputs)
    else:
        payload["all_inputs"] = dict(existing_all_inputs) if isinstance(existing_all_inputs, dict) else {}
        payload["input_groups"] = list(existing_input_groups) if isinstance(existing_input_groups, list) else []

    if not isinstance(meta.get("recommended_inputs"), dict):
        meta["recommended_inputs"] = recommended_inputs
    if not isinstance(meta.get("all_inputs"), dict):
        meta["all_inputs"] = payload["all_inputs"]
    if not isinstance(meta.get("input_groups"), list):
        meta["input_groups"] = payload["input_groups"]

    entry_points = _expand_entry_point_candidates(_extract_candidate_entry_points(payload))
    port_spec = _build_port_spec_from_inputs(entry_points, inputs)
    if isinstance(port_spec, dict):
        meta["port_spec"] = port_spec
        if isinstance(port_spec.get("entry_point"), str):
            meta.setdefault("workchain_entry_point", port_spec.get("entry_point"))

    required_code_plugin = _resolve_required_code_plugin(entry_points, inputs, port_spec)
    meta["required_code_plugin"] = required_code_plugin
    available_codes = _query_available_codes(required_code_plugin)
    if not available_codes:
        available_codes = _collect_available_codes_from_inputs(inputs, required_code_plugin)
    meta["available_codes"] = available_codes

    structure_metadata = _extract_structure_metadata_entries(payload)
    meta["structure_metadata"] = structure_metadata
    if structure_metadata:
        first = structure_metadata[0]
        meta.setdefault("symmetry", first.get("symmetry"))
        meta.setdefault("num_atoms", first.get("num_atoms"))
        meta.setdefault("estimated_runtime", first.get("estimated_runtime"))

    validation_summary = _build_validation_summary(
        validation if isinstance(validation, dict) else None,
        _as_dict(meta.get("validation_summary")),
    )
    if isinstance(validation_summary, dict):
        meta["validation_summary"] = validation_summary

    return payload


__all__ = [
    "extract_submitted_pk",
    "format_single_submission_response",
    "format_batch_submission_response",
    "enrich_submission_draft_payload",
]
