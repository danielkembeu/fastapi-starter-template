"""Endpoints du module d'exemple `projects`."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.authz import Permission, Requires, RequiresAny
from app.core.database import DBSessionDep
from app.core.errors import err
from app.core.pagination import Page
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectFilters,
    ProjectRead,
    ProjectStatusUpdate,
    ProjectUpdate,
)
from app.modules.projects.service import ProjectService
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["Projects"], responses=err(400, 500))

ReaderDep = Annotated[User, RequiresAny(Permission.PROJECT_READ_OWN, Permission.PROJECT_READ_ALL)]
CreatorDep = Annotated[User, Requires(Permission.PROJECT_CREATE)]
EditorDep = Annotated[
    User, RequiresAny(Permission.PROJECT_UPDATE_OWN, Permission.PROJECT_UPDATE_ALL)
]
DeleterDep = Annotated[
    User, RequiresAny(Permission.PROJECT_DELETE_OWN, Permission.PROJECT_DELETE_ALL)
]


@router.get("", response_model=Page[ProjectRead], responses=err(401, 403))
def list_projects(
    session: DBSessionDep, user: ReaderDep, filters: Annotated[ProjectFilters, Query()]
):
    """Liste paginée des projets : les siens, ou tous pour un administrateur.

    Filtres : `q`, `status`, `owner_id` (admin), `created_from`, `created_to` ; tri : `sort`.
    """
    result = ProjectService.list_projects(session, user, filters.page, filters)
    result["items"] = [ProjectRead.model_validate(p) for p in result["items"]]
    return result


@router.post("", response_model=ProjectRead, status_code=201, responses=err(401, 403))
def create_project(payload: ProjectCreate, session: DBSessionDep, user: CreatorDep):
    """Crée un projet (statut `draft`) appartenant à l'utilisateur authentifié."""
    return ProjectRead.model_validate(ProjectService.create(session, user, payload))


@router.get("/{project_id}", response_model=ProjectRead, responses=err(401, 403, 404))
def get_project(project_id: UUID, session: DBSessionDep, user: ReaderDep):
    """Renvoie un projet. 404 si ce n'est pas le sien (sauf administrateur)."""
    return ProjectRead.model_validate(ProjectService.get(session, user, project_id))


@router.patch("/{project_id}", response_model=ProjectRead, responses=err(401, 403, 404, 409))
def update_project(
    project_id: UUID, payload: ProjectUpdate, session: DBSessionDep, user: EditorDep
):
    """Modifie le nom ou la description. 409 si le projet est archivé."""
    return ProjectRead.model_validate(ProjectService.update(session, user, project_id, payload))


@router.post("/{project_id}/status", response_model=ProjectRead, responses=err(401, 403, 404, 409))
def change_project_status(
    project_id: UUID, payload: ProjectStatusUpdate, session: DBSessionDep, user: EditorDep
):
    """Change le statut : `draft → active | archived`, `active → archived`. 409 sinon."""
    return ProjectRead.model_validate(
        ProjectService.change_status(session, user, project_id, payload)
    )


@router.delete("/{project_id}", status_code=204, responses=err(401, 403, 404))
def delete_project(project_id: UUID, session: DBSessionDep, user: DeleterDep):
    """Supprime un projet (le journal d'audit en garde la trace)."""
    ProjectService.delete(session, user, project_id)
