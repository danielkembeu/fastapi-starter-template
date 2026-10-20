from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from app.core.clock import utc_now

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(SQLModel, table=True):
    """Journal d'audit : une ligne par opération, **en ajout seul**.

    Aucune route ni aucune méthode de service ne modifie ou ne supprime une ligne ; en PostgreSQL un
    déclencheur l'interdit aussi au niveau de la base (voir la migration). Les identifiants de
    l'acteur et de la ressource ne sont volontairement PAS des clés étrangères : la trace doit survivre
    à la suppression de ce qu'elle décrit.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)

    actor_type: str = Field(nullable=False)
    actor_id: UUID | None = Field(default=None)
    actor_role: str | None = Field(default=None)

    action: str = Field(nullable=False, index=True)
    outcome: str = Field(nullable=False, index=True)

    resource_type: str | None = Field(default=None)
    resource_id: UUID | None = Field(default=None)

    changes: dict[str, Any] | None = Field(default=None, sa_column=Column(_JSON))
    details: dict[str, Any] | None = Field(default=None, sa_column=Column(_JSON))

    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    request_id: str | None = Field(default=None, index=True)
