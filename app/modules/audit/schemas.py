from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel

from app.core.pagination import PageQuery
from app.modules.audit.enums import AuditAction, AuditOutcome


class AuditLogRead(SQLModel):
    id: UUID
    created_at: datetime = Field(description="Date de l'opération, en UTC.")
    actor_type: str = Field(description="`user`, `system` ou `anonymous`.")
    actor_id: UUID | None = None
    actor_role: str | None = None
    action: str
    outcome: str = Field(description="`success`, `denied` ou `failed`.")
    resource_type: str | None = None
    resource_id: UUID | None = None
    changes: dict[str, Any] | None = Field(
        default=None, description="Champs modifiés : `{champ: {from, to}}`."
    )
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = Field(
        default=None, description="Identifiant de requête (en-tête `X-Request-ID`)."
    )


class AuditFilters(PageQuery):
    """Filtres de `GET {préfixe}/admin/audit-logs`."""

    actor_id: UUID | None = Field(default=None, description="Les opérations d'un utilisateur.")
    action: AuditAction | None = Field(
        default=None, description="Une action précise, ex. `project.created`."
    )
    resource_type: str | None = Field(
        default=None, max_length=40, description="`project`, `user`, `session`…"
    )
    resource_id: UUID | None = Field(
        default=None, description="L'historique complet d'une ressource."
    )
    outcome: AuditOutcome | None = None
    request_id: str | None = Field(
        default=None, max_length=64, description="Toutes les entrées d'une même requête."
    )
    created_from: datetime | None = Field(default=None, description="À partir de (UTC, inclus).")
    created_to: datetime | None = Field(default=None, description="Jusqu'à (UTC, inclus).")
    sort: Literal["-created_at", "created_at"] = "-created_at"
