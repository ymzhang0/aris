"""Gateway for communicating with aiida-worker for project-related operations."""

from typing import Dict, Optional, Tuple
from src.aris_apps.aiida.client import aiida_worker_client


class AiiDAGatewayError(Exception):
    pass


async def ensure_project_group(project_id: str, project_name: str, profile: str = "default") -> Tuple[Optional[str], Optional[str]]:
    """Ensure a project group exists in AiiDA and returns (group_uuid, group_label)."""
    try:
        result = await aiida_worker_client.call(
            "group.ensure_project",
            {"project_id": project_id, "project_name": project_name, "profile": profile},
            timeout=15.0
        )
        if not isinstance(result, dict):
            raise AiiDAGatewayError("Invalid response from worker")
        return result.get("group_uuid"), result.get("group_label")
    except Exception as e:
        raise AiiDAGatewayError(f"Failed to ensure AiiDA project group: {e}")

async def relink_project_group(project_id: str, group_uuid: str) -> Tuple[Optional[str], Optional[str]]:
    """Relink an existing AiiDA group to a project."""
    try:
        result = await aiida_worker_client.call(
            "group.relink_project",
            {"project_id": project_id, "group_uuid": group_uuid},
            timeout=15.0
        )
        if not isinstance(result, dict):
            raise AiiDAGatewayError("Invalid response from worker")
        return result.get("group_uuid"), result.get("group_label")
    except Exception as e:
        raise AiiDAGatewayError(f"Failed to relink AiiDA project group: {e}")

async def inspect_project_group(group_uuid: str) -> bool:
    """Check if the project group exists and is valid."""
    try:
        result = await aiida_worker_client.call(
            "group.inspect",
            {"group_uuid": group_uuid},
            timeout=10.0
        )
        if not isinstance(result, dict):
            return False
        return result.get("exists", False)
    except Exception:
        return False
