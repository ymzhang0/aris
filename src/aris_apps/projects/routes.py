"""REST routes for ARIS projects."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from src.aris_apps.projects.models import Project
from src.aris_apps.projects.service import ProjectService, ProjectError
from src.aris_apps.projects.config_store import ConfigStore
from src.aris_apps.projects.repository import ProjectRepository
from pydantic import BaseModel
from pathlib import Path

router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_project_service() -> ProjectService:
    # Quick DI
    global_index = Path.home() / ".aris" / "projects" / "index.json"
    store = ConfigStore(global_index)
    repo = ProjectRepository(store)
    return ProjectService(store, repo)


class CreateProjectRequest(BaseModel):
    folder_path: str
    name: str
    aiida_enabled: bool = True
    aiida_profile: str = "default"


class LoadProjectRequest(BaseModel):
    folder_path: str


class RenameProjectRequest(BaseModel):
    new_name: str


class RelinkGroupRequest(BaseModel):
    group_uuid: str


@router.get("", response_model=List[Project])
async def list_projects(service: ProjectService = Depends(get_project_service)):
    return service.list_projects()


@router.post("", response_model=Project)
async def create_project(req: CreateProjectRequest, service: ProjectService = Depends(get_project_service)):
    try:
        return await service.create_project(
            folder_path=req.folder_path,
            name=req.name,
            aiida_enabled=req.aiida_enabled,
            aiida_profile=req.aiida_profile
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load", response_model=Project)
async def load_project(req: LoadProjectRequest, service: ProjectService = Depends(get_project_service)):
    try:
        return await service.load_project(folder_path=req.folder_path)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, service: ProjectService = Depends(get_project_service)):
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=Project)
async def rename_project(project_id: str, req: RenameProjectRequest, service: ProjectService = Depends(get_project_service)):
    try:
        return service.rename_project(project_id, req.new_name)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{project_id}/registration")
async def remove_project_from_aris(project_id: str, service: ProjectService = Depends(get_project_service)):
    service.remove_from_aris(project_id)
    return {"status": "ok"}


@router.post("/{project_id}/relink_group", response_model=Project)
async def relink_project_group(project_id: str, req: RelinkGroupRequest, service: ProjectService = Depends(get_project_service)):
    try:
        return await service.relink_aiida_group(project_id, req.group_uuid)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
