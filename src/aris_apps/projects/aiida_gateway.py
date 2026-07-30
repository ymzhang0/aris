"""Gateway for communicating with aiida-worker for project-related operations."""

from typing import Dict, Optional, Tuple
from src.aris_apps.aiida.client import aiida_worker_client


class AiiDAGatewayError(Exception):
    pass


async def ensure_project_group(project_id: str, project_name: str, profile: str = "default") -> Tuple[Optional[str], Optional[str]]:
    """Ensure a project group exists in AiiDA and returns (group_uuid, group_label)."""
    try:
        response = await aiida_worker_client.call_rpc(
            "group.ensure_project",
            {"project_id": project_id, "project_name": project_name, "profile": profile},
            timeout=15.0
        )
        if not response or "result" not in response:
            raise AiiDAGatewayError("Invalid response from worker")
        
        result = response["result"]
        return result.get("group_uuid"), result.get("group_label")
    except Exception as e:
        raise AiiDAGatewayError(f"Failed to ensure AiiDA project group: {e}")

async def relink_project_group(project_id: str, group_uuid: str) -> Tuple[Optional[str], Optional[str]]:
    """Relink an existing AiiDA group to a project."""
    try:
        response = await aiida_worker_client.call_rpc(
            "group.relink_project",
            {"project_id": project_id, "group_uuid": group_uuid},
            timeout=15.0
        )
        if not response or "result" not in response:
            raise AiiDAGatewayError("Invalid response from worker")
        
        result = response["result"]
        return result.get("group_uuid"), result.get("group_label")
    except Exception as e:
        raise AiiDAGatewayError(f"Failed to relink AiiDA project group: {e}")

async def inspect_project_group(group_uuid: str) -> bool:
    """Check if the project group exists and is valid."""
    try:
        response = await aiida_worker_client.call_rpc(
            "group.inspect",
            {"group_uuid": group_uuid},
            timeout=10.0
        )
        if not response or "result" not in response:
            return False
        return response["result"].get("exists", False)
    except Exception:
        return False
