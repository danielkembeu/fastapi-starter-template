from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel

from app.core.clock import utc_now

from .enums import ProjectStatus

if TYPE_CHECKING:
    from app.modules.users.models import User


class Project(SQLModel, table=True):
    """Ressource d'exemple : modèle à copier pour vos propres entités métier."""

    __tablename__ = "projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)

    owner_id: UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(nullable=False, index=True)
    description: str | None = Field(default=None)
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT, index=True)

    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime | None = Field(default_factory=utc_now)

    owner: Optional["User"] = Relationship(back_populates="projects")
