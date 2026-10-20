"""Logique métier du module d'exemple `projects`.

Ce module montre le motif complet à reproduire pour chaque ressource :
portée « own / all » (RBAC), machine à états, pagination filtrée, audit atomique.
"""

from uuid import UUID

from sqlmodel import Session, col, select

from app.core.authz import Permission, can, ensure_owner_or_permission
from app.core.clock import utc_now
from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams, apply_date_range, apply_sort, like_pattern, paginate
from app.modules.audit.enums import AuditAction
from app.modules.audit.service import AuditService
from app.modules.projects.enums import ProjectStatus
from app.modules.projects.models import Project
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectFilters,
    ProjectStatusUpdate,
    ProjectUpdate,
)
from app.modules.users.models import User

NOT_FOUND = "Projet introuvable"
NO_ACCESS = "Accès refusé"

# Transitions légales : tout le reste est refusé (409). C'est de la logique métier, pas du RBAC.
ALLOWED_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.DRAFT: {ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED},
    ProjectStatus.ACTIVE: {ProjectStatus.ARCHIVED},
    ProjectStatus.ARCHIVED: set(),
}


class ProjectService:
    @staticmethod
    def list_projects(session: Session, user: User, params: PageParams, filters: ProjectFilters):
        """Un utilisateur ne voit que ses projets ; un administrateur voit tout (filtre `owner_id`)."""
        sees_all = can(user, Permission.PROJECT_READ_ALL)
        if filters.owner_id is not None and not sees_all:
            raise AppError(
                403,
                ErrorCode.FILTER_FORBIDDEN,
                "Le filtre owner_id est réservé aux administrateurs",
            )

        stmt = select(Project)
        if not sees_all:
            stmt = stmt.where(Project.owner_id == user.id)
        elif filters.owner_id is not None:
            stmt = stmt.where(Project.owner_id == filters.owner_id)
        if filters.status is not None:
            stmt = stmt.where(Project.status == filters.status)
        if filters.q:
            stmt = stmt.where(col(Project.name).ilike(like_pattern(filters.q), escape="\\"))
        stmt = apply_date_range(stmt, Project.created_at, filters.created_from, filters.created_to)
        stmt = apply_sort(
            stmt,
            filters.sort,
            {"created_at": Project.created_at, "name": Project.name},
            tiebreaker=Project.id,
        )
        return paginate(session, stmt, params)

    @staticmethod
    def get(session: Session, user: User, project_id: UUID) -> Project:
        project = session.get(Project, project_id)
        if not project:
            raise AppError(404, ErrorCode.NOT_FOUND, NOT_FOUND)
        # 404 plutôt que 403 pour autrui : on ne révèle pas l'existence d'un projet qui n'est pas le sien.
        if project.owner_id != user.id and not can(user, Permission.PROJECT_READ_ALL):
            raise AppError(404, ErrorCode.NOT_FOUND, NOT_FOUND)
        return project

    @staticmethod
    def create(session: Session, user: User, payload: ProjectCreate) -> Project:
        project = Project(owner_id=user.id, name=payload.name, description=payload.description)
        session.add(project)
        session.flush()
        AuditService.log(
            session,
            AuditAction.PROJECT_CREATED,
            actor=user,
            resource=project,
            details={"name": project.name},
        )
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def update(session: Session, user: User, project_id: UUID, payload: ProjectUpdate) -> Project:
        project = ProjectService.get(session, user, project_id)
        ensure_owner_or_permission(user, project.owner_id, Permission.PROJECT_UPDATE_ALL, NO_ACCESS)

        data = payload.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is None:
            raise AppError(
                400,
                ErrorCode.VALIDATION_ERROR,
                "Le champ name ne peut pas être vide",
                details=[
                    {
                        "field": "body.name",
                        "message": "Valeur obligatoire",
                        "code": "null_not_allowed",
                    }
                ],
            )
        if project.status == ProjectStatus.ARCHIVED:
            raise AppError(
                409, ErrorCode.RESOURCE_LOCKED, "Un projet archivé n'est plus modifiable"
            )

        before = AuditService.snapshot(project, data.keys())
        for field, value in data.items():
            setattr(project, field, value)
        project.updated_at = utc_now()
        session.add(project)

        changes = AuditService.diff(before, project)
        if changes:
            AuditService.log(
                session, AuditAction.PROJECT_UPDATED, actor=user, resource=project, changes=changes
            )
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def change_status(
        session: Session, user: User, project_id: UUID, payload: ProjectStatusUpdate
    ) -> Project:
        project = ProjectService.get(session, user, project_id)
        ensure_owner_or_permission(user, project.owner_id, Permission.PROJECT_UPDATE_ALL, NO_ACCESS)

        if payload.status not in ALLOWED_TRANSITIONS[project.status]:
            raise AppError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Transition interdite : {project.status.value} → {payload.status.value}",
            )

        previous = project.status
        project.status = payload.status
        project.updated_at = utc_now()
        session.add(project)
        AuditService.log(
            session,
            AuditAction.PROJECT_STATUS_CHANGED,
            actor=user,
            resource=project,
            changes={"status": {"from": previous, "to": payload.status}},
        )
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def delete(session: Session, user: User, project_id: UUID) -> None:
        project = ProjectService.get(session, user, project_id)
        ensure_owner_or_permission(user, project.owner_id, Permission.PROJECT_DELETE_ALL, NO_ACCESS)

        AuditService.log(
            session,
            AuditAction.PROJECT_DELETED,
            actor=user,
            resource=project,
            details={"name": project.name, "status": project.status},
        )
        session.delete(project)
        session.commit()
