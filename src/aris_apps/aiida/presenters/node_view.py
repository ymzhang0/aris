from __future__ import annotations

import asyncio
from typing import Any, Literal

from src.aris_apps.aiida.client import BridgeAPIError, BridgeOfflineError, request_json
from ..schemas import NodeHoverMetadataResponse


def _normalize_process_state(state: str | None) -> str:
    return str(state or "unknown").strip().lower()


def _state_to_status_color(state: str | None) -> str:
    normalized = _normalize_process_state(state)
    if normalized in {"running", "created", "waiting"}:
        return "running"
    if normalized in {"finished", "completed"}:
        return "success"
    if normalized in {"failed", "excepted", "killed"}:
        return "error"
    return "idle"


def serialize_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for process in processes:
        process_state_raw = process.get("process_state")
        state = str(process_state_raw or process.get("state") or "unknown")
        process_label_raw = process.get("process_label")
        try:
            pk = int(process.get("pk", 0))
        except (TypeError, ValueError):
            pk = 0
        formula = process.get("formula")
        serialized: dict[str, Any] = {
            "pk": pk,
            "label": str(process.get("label") or "Unknown Task"),
            "state": state,
            "status_color": _state_to_status_color(state),
            "node_type": str(process.get("node_type") or "Node"),
            "process_state": str(process_state_raw) if process_state_raw is not None else None,
            "formula": str(formula) if formula else None,
        }
        if process_label_raw:
            serialized["process_label"] = str(process_label_raw)
        if "preview_info" in process:
            serialized["preview_info"] = process.get("preview_info")
        payload.append(serialized)
    return payload


def serialize_group_labels(labels: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in labels:
        text = _coerce_text(item)
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def serialize_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    seen: set[int] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = _coerce_text(group.get("label"))
        pk = _coerce_int(group.get("pk"))
        if not label or pk is None or pk in seen:
            continue
        seen.add(pk)
        count = _coerce_int(group.get("count")) or 0
        item: dict[str, Any] = {
            "pk": pk,
            "label": label,
            "count": max(0, count),
        }
        type_string = _coerce_text(group.get("type_string"))
        if type_string:
            item["type_string"] = type_string
        payload.append(item)
    return payload


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


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    elif isinstance(value, dict):
        values = value.keys()
    elif value is None:
        values = []
    else:
        values = [value]
    result: list[str] = []
    for item in values:
        text = _coerce_text(item)
        if text:
            result.append(text)
    return result


def _extract_filename_list(raw: Any, limit: int = 5) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        for key in ("files", "filenames", "items", "listing", "entries", "paths"):
            if key in raw:
                return _extract_filename_list(raw.get(key), limit=limit)
        # map-style fallback: {"file.txt": {...}, ...}
        if raw:
            return _extract_filename_list(list(raw.keys()), limit=limit)
        return []
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = _coerce_text(
                    item.get("name")
                    or item.get("filename")
                    or item.get("path")
                    or item.get("label")
                )
            else:
                name = _coerce_text(item)
            if name:
                values.append(name)
            if len(values) >= limit:
                break
        return values[:limit]
    single = _coerce_text(raw)
    return [single] if single else []


def _normalize_link_entry(raw: Any, fallback_label: str | None = None) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        nested_node: dict[str, Any] | None = None
        for key in ("node", "target", "source", "data", "value"):
            candidate = raw.get(key)
            if isinstance(candidate, dict):
                nested_node = candidate
                break

        pk = _coerce_int(
            raw.get("pk")
            or raw.get("node_pk")
            or raw.get("id")
            or (nested_node or {}).get("pk")
            or (nested_node or {}).get("id")
        )
        if pk is None:
            return None

        node_type = _coerce_text(
            raw.get("node_type")
            or raw.get("type")
            or raw.get("entry_type")
            or (nested_node or {}).get("node_type")
            or (nested_node or {}).get("type")
            or (nested_node or {}).get("entry_type")
            or "Node"
        )
        if not node_type:
            node_type = "Node"

        link_label = _coerce_text(
            raw.get("link_label")
            or raw.get("label")
            or raw.get("linkname")
            or raw.get("name")
            or fallback_label
            or f"link_{pk}"
        )
        return {
            "link_label": link_label or f"link_{pk}",
            "node_type": node_type,
            "pk": pk,
        }

    pk = _coerce_int(raw)
    if pk is None:
        return None
    return {
        "link_label": fallback_label or f"link_{pk}",
        "node_type": "Node",
        "pk": pk,
    }


def _normalize_links_payload(raw: Any, prefix: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if raw is None:
        return normalized

    if isinstance(raw, (list, tuple, set)):
        for idx, item in enumerate(raw, start=1):
            entry = _normalize_link_entry(item, fallback_label=f"{prefix}_{idx}")
            if entry:
                normalized.append(entry)
        return normalized

    if isinstance(raw, dict):
        direct_entry = _normalize_link_entry(raw, fallback_label=prefix)
        if direct_entry:
            return [direct_entry]

        container_keys = {"items", "links", "data", "entries", "results", "nodes"}
        for container_key in container_keys:
            if container_key in raw:
                normalized.extend(_normalize_links_payload(raw.get(container_key), prefix))

        for key, value in raw.items():
            if key in container_keys:
                continue
            fallback_label = _coerce_text(key) or prefix
            entry = _normalize_link_entry(value, fallback_label=fallback_label)
            if entry:
                normalized.append(entry)
        return normalized

    entry = _normalize_link_entry(raw, fallback_label=prefix)
    if entry:
        normalized.append(entry)
    return normalized


def _dedupe_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for link in links:
        pk = _coerce_int(link.get("pk"))
        if pk is None:
            continue
        node_type = _coerce_text(link.get("node_type")) or "Node"
        link_label = _coerce_text(link.get("link_label")) or f"link_{pk}"
        key = (pk, node_type, link_label)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {
            "link_label": link_label,
            "node_type": node_type,
            "pk": pk,
        }
        preview = link.get("preview_info")
        if isinstance(preview, dict) and preview:
            payload["preview_info"] = preview
        deduped.append(payload)
    return deduped


def _extract_directional_links(payload: dict[str, Any], direction: Literal["inputs", "outputs"]) -> list[dict[str, Any]]:
    if direction == "inputs":
        direct_keys = ("inputs", "incoming", "incoming_links", "input_links", "inbound")
        nested_keys = ("inputs", "incoming", "inbound")
    else:
        direct_keys = ("outputs", "outgoing", "outgoing_links", "output_links", "outbound")
        nested_keys = ("outputs", "outgoing", "outbound")

    links: list[dict[str, Any]] = []
    for key in direct_keys:
        if key in payload:
            raw_val = payload.get(key)
            if not isinstance(raw_val, int):
                links.extend(_normalize_links_payload(raw_val, direction[:-1]))

    calc_block = payload.get("calculation")
    if isinstance(calc_block, dict):
        for key in direct_keys:
            if key in calc_block:
                raw_val = calc_block.get(key)
                if not isinstance(raw_val, int):
                    links.extend(_normalize_links_payload(raw_val, direction[:-1]))

    links_block = payload.get("links")
    if isinstance(links_block, dict):
        for key in nested_keys:
            if key in links_block:
                links.extend(_normalize_links_payload(links_block.get(key), direction[:-1]))

    provenance_block = payload.get("provenance")
    if isinstance(provenance_block, dict):
        for key in nested_keys:
            if key in provenance_block:
                links.extend(_normalize_links_payload(provenance_block.get(key), direction[:-1]))

    return _dedupe_links(links)


def _collect_tree_node_ids(tree_root: Any) -> list[int]:
    if not isinstance(tree_root, dict):
        return []
    node_ids: list[int] = []
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        pk = _coerce_int(node.get("pk"))
        if pk is not None and pk not in seen:
            seen.add(pk)
            node_ids.append(pk)
        children = node.get("children")
        if isinstance(children, dict):
            for child in children.values():
                walk(child)
        elif isinstance(children, list):
            for child in children:
                walk(child)

    walk(tree_root)
    return node_ids


def _links_list_to_dict(links: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for link in links:
        label = str(link.get("link_label") or "unknown")
        unique_label = f"{label}_{counts[label]}" if label in counts else label
        counts[label] = counts.get(label, 0) + 1
        result[unique_label] = link
    return result


def attach_tree_links(
    tree_root: Any,
    links_by_pk: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]] | None, list[dict[str, Any]] | None]],
) -> None:
    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        pk = _coerce_int(node.get("pk"))
        if pk is not None:
            input_links, output_links, direct_inputs, direct_outputs = links_by_pk.get(pk, (None, None, None, None))
            # The provenance tree should show only direct port mappings for each process node.
            if direct_inputs is not None:
                node["inputs"] = _links_list_to_dict(direct_inputs)
                node["direct_inputs"] = _links_list_to_dict(direct_inputs)
            elif input_links:
                node["inputs"] = _links_list_to_dict(input_links)
            elif "inputs" not in node:
                node["inputs"] = {}

            if direct_outputs is not None:
                node["outputs"] = _links_list_to_dict(direct_outputs)
                node["direct_outputs"] = _links_list_to_dict(direct_outputs)
            elif output_links:
                node["outputs"] = _links_list_to_dict(output_links)
            elif "outputs" not in node:
                node["outputs"] = {}
        children = node.get("children")
        if isinstance(children, dict):
            for child in children.values():
                walk(child)
        elif isinstance(children, list):
            for child in children:
                walk(child)

    walk(tree_root)


def _extract_remote_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    remote_path = _coerce_text(payload.get("remote_path") or payload.get("path"))
    computer_name = _coerce_text(payload.get("computer_name") or payload.get("computer_label"))
    computer = payload.get("computer")
    if not computer_name and isinstance(computer, dict):
        computer_name = _coerce_text(
            computer.get("label")
            or computer.get("name")
            or computer.get("hostname")
            or computer.get("host")
        )
    if not computer_name:
        computer_name = _coerce_text(payload.get("hostname") or payload.get("host"))
    if not remote_path and not computer_name:
        return None
    return {
        "remote_path": remote_path,
        "computer_name": computer_name,
    }


def extract_folder_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [
        payload.get("filenames"),
        payload.get("files"),
        payload.get("items"),
        payload.get("listing"),
        payload.get("entries"),
        payload.get("paths"),
        payload.get("children"),
        payload.get("objects"),
    ]

    repository = payload.get("repository")
    if repository is not None:
        candidates.append(repository)
        if isinstance(repository, dict):
            for key in ("filenames", "files", "items", "listing", "entries", "paths"):
                if key in repository:
                    candidates.append(repository.get(key))

    for candidate in candidates:
        filenames = _extract_filename_list(candidate, limit=5)
        if filenames:
            return {"filenames": filenames[:5]}
    return None


def _extract_xy_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    x_label = _coerce_text(payload.get("x_label") or payload.get("x_name") or payload.get("x"))
    x_length = _coerce_int(payload.get("x_length") or payload.get("x_len") or payload.get("x_size"))

    y_labels = _coerce_string_list(payload.get("y_labels") or payload.get("y_names") or payload.get("y"))
    y_arrays: list[dict[str, Any]] = []

    y_lengths_raw = payload.get("y_lengths")
    y_lengths_by_label: dict[str, int | None] = {}
    if isinstance(y_lengths_raw, dict):
        for key, value in y_lengths_raw.items():
            y_key = _coerce_text(key)
            if y_key:
                y_lengths_by_label[y_key] = _coerce_int(value)
    elif isinstance(y_lengths_raw, (list, tuple)):
        for idx, value in enumerate(y_lengths_raw):
            if idx < len(y_labels):
                y_lengths_by_label[y_labels[idx]] = _coerce_int(value)

    arrays_raw = payload.get("arrays")
    if isinstance(arrays_raw, list):
        for item in arrays_raw:
            if not isinstance(item, dict):
                continue
            label = _coerce_text(item.get("name") or item.get("label"))
            length = _coerce_int(item.get("length") or item.get("size"))
            if length is None and isinstance(item.get("shape"), (list, tuple)):
                shape = item.get("shape")
                if shape:
                    length = _coerce_int(shape[0])
            if label:
                if label == x_label and x_length is None:
                    x_length = length
                elif label in y_labels:
                    y_lengths_by_label[label] = length

    for label in y_labels:
        y_arrays.append({"label": label, "length": y_lengths_by_label.get(label)})

    if not x_label and not y_arrays:
        return None
    return {
        "x_label": x_label,
        "x_length": x_length,
        "y_arrays": y_arrays,
    }


def _extract_embedded_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    preview = payload.get("preview_info")
    return preview if isinstance(preview, dict) and preview else None


def _extract_preview_for_node_type(node_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    embedded_preview = _extract_embedded_preview(payload)
    if embedded_preview:
        return embedded_preview
    if node_type == "RemoteData":
        return _extract_remote_preview(payload)
    if node_type == "FolderData":
        return extract_folder_preview(payload)
    if node_type == "XyData":
        return _extract_xy_preview(payload)
    return None


async def _request_optional_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any | None:
    try:
        return await request_json(method, path, params=params)
    except (BridgeOfflineError, BridgeAPIError):
        return None
    except Exception:
        return None


async def _fetch_node_payload(pk: int, cache: dict[int, dict[str, Any] | None]) -> dict[str, Any] | None:
    if pk in cache:
        return cache[pk]
    payload = await _request_optional_json("GET", f"/management/nodes/{pk}")
    cache[pk] = payload if isinstance(payload, dict) else None
    return cache[pk]


async def _fetch_data_node_payload(pk: int, cache: dict[int, dict[str, Any] | None]) -> dict[str, Any] | None:
    if pk in cache:
        return cache[pk]
    payload = await _request_optional_json("GET", f"/data/node/{pk}")
    cache[pk] = payload if isinstance(payload, dict) else None
    return cache[pk]


async def _fetch_repository_filenames(pk: int, cache: dict[int, list[str]]) -> list[str]:
    if pk in cache:
        return cache[pk]
    payload = await _request_optional_json("GET", f"/data/repository/{pk}/files", params={"source": "folder"})
    if payload is None:
        payload = await _request_optional_json("GET", f"/data/repository/{pk}/files")
    filenames = _extract_filename_list(payload, limit=5)
    cache[pk] = filenames[:5]
    return cache[pk]


async def _enrich_link_preview(
    link: dict[str, Any],
    node_payload_cache: dict[int, dict[str, Any] | None],
    data_payload_cache: dict[int, dict[str, Any] | None],
    repo_listing_cache: dict[int, list[str]],
) -> None:
    node_type = _coerce_text(link.get("node_type")) or "Node"
    normalized_type = node_type.strip().lower()
    if "data" not in normalized_type and node_type not in {"Dict", "List", "Int", "Float", "Str", "Bool"}:
        return
    pk = _coerce_int(link.get("pk"))
    if pk is None:
        return

    preview: dict[str, Any] | None = None
    node_payload = await _fetch_node_payload(pk, node_payload_cache)
    if node_payload:
        preview = _extract_preview_for_node_type(node_type, node_payload)

    if not preview:
        data_payload = await _fetch_data_node_payload(pk, data_payload_cache)
        if data_payload:
            preview = _extract_preview_for_node_type(node_type, data_payload)

    if node_type == "FolderData":
        filenames = preview.get("filenames") if isinstance(preview, dict) else None
        if not filenames:
            filenames = await _fetch_repository_filenames(pk, repo_listing_cache)
            if filenames:
                preview = dict(preview or {})
                preview["filenames"] = filenames[:5]

    if preview:
        link["preview_info"] = preview


async def _enrich_links_with_previews(
    links: list[dict[str, Any]],
    *,
    node_payload_cache: dict[int, dict[str, Any] | None],
    data_payload_cache: dict[int, dict[str, Any] | None],
    repo_listing_cache: dict[int, list[str]],
) -> None:
    tasks = [
        _enrich_link_preview(
            link,
            node_payload_cache=node_payload_cache,
            data_payload_cache=data_payload_cache,
            repo_listing_cache=repo_listing_cache,
        )
        for link in links
    ]
    if tasks:
        await asyncio.gather(*tasks)


async def enrich_process_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    detail = payload
    summary = detail.get("summary")
    root_pk = _coerce_int(summary.get("pk")) if isinstance(summary, dict) else None
    tree_root = (
        detail.get("workchain", {}).get("provenance_tree")
        if isinstance(detail.get("workchain"), dict)
        else None
    )
    tree_node_ids = _collect_tree_node_ids(tree_root)

    node_ids: list[int] = []
    if root_pk is not None:
        node_ids.append(root_pk)
    for pk in tree_node_ids:
        if pk not in node_ids:
            node_ids.append(pk)

    node_payload_cache: dict[int, dict[str, Any] | None] = {}
    data_payload_cache: dict[int, dict[str, Any] | None] = {}
    repo_listing_cache: dict[int, list[str]] = {}
    links_by_pk: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]] | None, list[dict[str, Any]] | None]] = {}

    if node_ids:
        summaries = await asyncio.gather(*[_fetch_node_payload(pk, node_payload_cache) for pk in node_ids])
        for pk, node_payload in zip(node_ids, summaries):
            if isinstance(node_payload, dict):
                input_links = _extract_directional_links(node_payload, "inputs")
                output_links = _extract_directional_links(node_payload, "outputs")
                direct_inputs = node_payload.get("direct_inputs") if "direct_inputs" in node_payload else None
                direct_outputs = node_payload.get("direct_outputs") if "direct_outputs" in node_payload else None
                if isinstance(direct_inputs, dict):
                    direct_inputs = _dedupe_links(_normalize_links_payload(direct_inputs, "inputs"))
                elif direct_inputs is not None:
                    direct_inputs = _dedupe_links(list(direct_inputs))
                if isinstance(direct_outputs, dict):
                    direct_outputs = _dedupe_links(_normalize_links_payload(direct_outputs, "outputs"))
                elif direct_outputs is not None:
                    direct_outputs = _dedupe_links(list(direct_outputs))
            else:
                input_links = []
                output_links = []
                direct_inputs = None
                direct_outputs = None
            links_by_pk[pk] = (input_links, output_links, direct_inputs, direct_outputs)

    detail_inputs = _extract_directional_links(detail, "inputs")
    detail_outputs = _extract_directional_links(detail, "outputs")
    
    # Process explicit direct inputs from the root detail if available
    detail_direct_inputs = detail.get("direct_inputs", [])
    detail_direct_outputs = detail.get("direct_outputs", [])
    if isinstance(detail_direct_inputs, dict):
        detail_direct_inputs = _dedupe_links(_normalize_links_payload(detail_direct_inputs, "inputs"))
    if isinstance(detail_direct_outputs, dict):
        detail_direct_outputs = _dedupe_links(_normalize_links_payload(detail_direct_outputs, "outputs"))
        
    if root_pk is not None and root_pk in links_by_pk:
        root_input_links, root_output_links, root_direct_in, root_direct_out = links_by_pk[root_pk]
        detail_inputs = _dedupe_links(detail_inputs + root_input_links)
        detail_outputs = _dedupe_links(detail_outputs + root_output_links)
        detail_direct_inputs = _dedupe_links(detail_direct_inputs + (root_direct_in or []))
        detail_direct_outputs = _dedupe_links(detail_direct_outputs + (root_direct_out or []))
    else:
        detail_inputs = _dedupe_links(detail_inputs)
        detail_outputs = _dedupe_links(detail_outputs)
        detail_direct_inputs = _dedupe_links(detail_direct_inputs)
        detail_direct_outputs = _dedupe_links(detail_direct_outputs)

    all_link_lists: list[list[dict[str, Any]]] = [detail_inputs, detail_outputs, detail_direct_inputs, detail_direct_outputs]
    for input_links, output_links, direct_in, direct_out in links_by_pk.values():
        all_link_lists.append(input_links)
        all_link_lists.append(output_links)
        if direct_in:
            all_link_lists.append(direct_in)
        if direct_out:
            all_link_lists.append(direct_out)

    await asyncio.gather(
        *[
            _enrich_links_with_previews(
                links,
                node_payload_cache=node_payload_cache,
                data_payload_cache=data_payload_cache,
                repo_listing_cache=repo_listing_cache,
            )
            for links in all_link_lists
            if links
        ]
    )

    if getattr(detail_inputs, "__len__", lambda: 0)() > 0 or "inputs" not in detail:
        detail["inputs"] = _links_list_to_dict(detail_inputs)
    if getattr(detail_outputs, "__len__", lambda: 0)() > 0 or "outputs" not in detail:
        detail["outputs"] = _links_list_to_dict(detail_outputs)
        
    if getattr(detail_direct_inputs, "__len__", lambda: 0)() > 0 or "direct_inputs" not in detail:
        detail["direct_inputs"] = _links_list_to_dict(detail_direct_inputs)
    if getattr(detail_direct_outputs, "__len__", lambda: 0)() > 0 or "direct_outputs" not in detail:
        detail["direct_outputs"] = _links_list_to_dict(detail_direct_outputs)

    if isinstance(tree_root, dict):
        attach_tree_links(tree_root, links_by_pk)
    return detail


def _coerce_chat_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key, value in raw.items():
        cleaned_key = str(key).strip()
        if not cleaned_key:
            continue
        metadata[cleaned_key] = value
    return metadata


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _find_first_named_value(payload: Any, candidate_keys: set[str], depth: int = 0) -> Any:
    if depth > 8:
        return None

    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in candidate_keys and not _is_empty_value(value):
                return value
            nested = _find_first_named_value(value, candidate_keys, depth + 1)
            if nested is not None:
                return nested
        return None

    if isinstance(payload, (list, tuple, set)):
        for entry in payload:
            nested = _find_first_named_value(entry, candidate_keys, depth + 1)
            if nested is not None:
                return nested

    return None


def _format_spacegroup_value(value: Any) -> str | None:
    if isinstance(value, dict):
        symbol = _coerce_text(
            value.get("symbol")
            or value.get("international_short")
            or value.get("international_symbol")
            or value.get("spacegroup")
            or value.get("space_group")
            or value.get("name")
        )
        number = _coerce_text(
            value.get("number")
            or value.get("spacegroup_number")
            or value.get("international_number")
        )
        if symbol and number:
            return f"{symbol} ({number})"
        return symbol or number

    if isinstance(value, (list, tuple, set)):
        for entry in value:
            formatted = _format_spacegroup_value(entry)
            if formatted:
                return formatted
        return None

    return _coerce_text(value)


def extract_node_hover_metadata(node_payload: dict[str, Any], pk: int) -> NodeHoverMetadataResponse:
    formula = _coerce_text(node_payload.get("formula") or node_payload.get("chemical_formula"))
    if formula is None:
        formula = _coerce_text(
            _find_first_named_value(
                node_payload,
                {
                    "formula",
                    "chemical_formula",
                    "formula_hill",
                    "formula_reduced",
                    "reduced_formula",
                },
            )
        )

    node_type = _coerce_text(node_payload.get("node_type") or node_payload.get("type"))
    if node_type is None:
        node_type = _coerce_text(
            _find_first_named_value(
                node_payload,
                {"node_type", "type"},
            )
        )

    raw_spacegroup = _find_first_named_value(
        node_payload,
        {
            "spacegroup",
            "space_group",
            "spacegroup_symbol",
            "spacegroup_number",
            "international_symbol",
            "international_number",
            "symmetry",
        },
    )
    spacegroup = _format_spacegroup_value(raw_spacegroup)

    return NodeHoverMetadataResponse(
        pk=pk,
        formula=formula,
        spacegroup=spacegroup,
        node_type=node_type or "Unknown",
    )


__all__ = [
    "serialize_processes",
    "serialize_group_labels",
    "serialize_groups",
    "extract_folder_preview",
    "attach_tree_links",
    "enrich_process_detail_payload",
    "extract_node_hover_metadata",
    "_coerce_chat_metadata",
]
