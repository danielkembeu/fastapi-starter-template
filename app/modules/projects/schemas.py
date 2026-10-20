"""Schémas d'entrée/sortie du module d'exemple `projects`."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints
from sqlmodel import SQLModel

from app.core.pagination import PageQuery
from app.modules.projects.enums import ProjectStatus

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ProjectCreate(SQLModel):
    name: ProjectName
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None


class ProjectUpdate(SQLModel):
    """PATCH partiel : seuls les champs fournis sont modifiés."""

    name: ProjectName | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None


class ProjectStatusUpdate(SQLModel):
    status: ProjectStatus


class ProjectRead(SQLModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None = None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime | None = None


class ProjectFilters(PageQuery):
    """Filtres de `GET {préfixe}/projects`."""

    q: Annotated[str, Field(max_length=80)] | None = Field(
        default=None, description="Recherche dans le nom."
    )
    status: ProjectStatus | None = None
    owner_id: UUID | None = Field(
        default=None, description="Réservé aux administrateurs (403 sinon)."
    )
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: Literal["created_at", "-created_at", "name", "-name"] = "-created_at"
