"""Fabriques de données, créées directement en base (plus rapides que par l'API)."""

from itertools import count

from sqlmodel import Session

from app.modules.projects.enums import ProjectStatus
from app.modules.projects.models import Project
from app.modules.users.models import User

_n = count(1)


def make_project(
    session: Session,
    owner: User,
    *,
    name: str | None = None,
    description: str | None = None,
    status: ProjectStatus = ProjectStatus.DRAFT,
) -> Project:
    project = Project(
        owner_id=owner.id,
        name=name or f"Projet {next(_n)}",
        description=description,
        status=status,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project
