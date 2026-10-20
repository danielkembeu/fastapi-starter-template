"""Journal d'audit : qui a fait quoi, sur quoi, quand, d'où, et avec quel résultat.

Deux modes d'écriture, choisis selon ce qu'on veut garantir :

- `log(session, ...)` : la ligne rejoint la transaction EN COURS (aucun commit ici). Le journal est
  donc *atomique* avec l'opération : si l'opération échoue et est annulée, aucune trace fantôme ; si
  elle réussit, la trace est garantie. C'est le mode des opérations réussies.
- `log_detached(...)` : session et transaction indépendantes, *au mieux* (une erreur est journalisée
  mais n'interrompt jamais la requête). C'est le mode des refus et échecs, qui lèvent une erreur HTTP
  et annulent la transaction principale — c'est précisément ce qu'on veut quand même tracer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, col, select

from app.core import database
from app.core.context import current_context
from app.core.pagination import PageParams, apply_date_range, apply_sort, paginate
from app.core.redaction import (  # noqa: F401 — réexportés
    MAX_STRING_LENGTH,
    REDACTED,
    SENSITIVE_KEYS,
    redact,
)
from app.modules.audit.enums import ActorType, AuditAction, AuditOutcome
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditFilters

logger = logging.getLogger(__name__)

# Nom stable de la ressource dans le journal, indépendant du nom de la classe ou de la table.
RESOURCE_TYPES = {
    "User": "user",
    "UserSession": "session",
    "Project": "project",
}


def _clean(value: Any) -> Any:
    """Rend `value` sérialisable en JSON, masque les clés sensibles, tronque les longues chaînes."""
    return redact(jsonable_encoder(value))


def resource_type_of(resource: Any) -> str:
    name = type(resource).__name__
    return RESOURCE_TYPES.get(name, name.lower())


class AuditService:
    # ---- Construction -------------------------------------------------------------

    @staticmethod
    def _actor(actor: Any) -> tuple[ActorType | None, UUID | None, str | None]:
        """Accepte un `User` ou `None`."""
        if actor is None:
            return None, None, None
        role = getattr(actor, "role", None)
        return ActorType.USER, actor.id, getattr(role, "value", role)

    @staticmethod
    def build(
        action: AuditAction,
        *,
        actor: Any = None,
        actor_id: UUID | None = None,
        actor_role: str | None = None,
        actor_type: ActorType | None = None,
        resource: Any = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        changes: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        found_type, found_id, found_role = AuditService._actor(actor)
        if actor_id is not None:  # acteur déjà identifié (ex. lu sur la requête)
            found_type, found_id, found_role = ActorType.USER, actor_id, actor_role
        if resource is not None:
            resource_type = resource_type or resource_type_of(resource)
            resource_id = resource_id or getattr(resource, "id", None)
        context = current_context()
        return AuditLog(
            actor_type=(actor_type or found_type or ActorType.ANONYMOUS).value,
            actor_id=found_id,
            actor_role=found_role,
            action=action.value,
            outcome=outcome.value,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=_clean(changes) if changes else None,
            details=_clean(details) if details else None,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
        )

    # ---- Écriture -----------------------------------------------------------------

    @staticmethod
    def log(session: Session, action: AuditAction, **kwargs: Any) -> AuditLog:
        """Ajoute l'entrée à la transaction en cours (sans commit)."""
        entry = AuditService.build(action, **kwargs)
        session.add(entry)
        return entry

    @staticmethod
    def log_detached(action: AuditAction, **kwargs: Any) -> None:
        """Écrit l'entrée dans sa propre transaction ; ne lève jamais d'exception."""
        try:
            entry = AuditService.build(action, **kwargs)
            with Session(database.engine) as own_session:
                own_session.add(entry)
                own_session.commit()
        except Exception:
            logger.exception("Écriture du journal d'audit impossible (action=%s)", action.value)

    # ---- Aide aux modifications ---------------------------------------------------

    @staticmethod
    def snapshot(resource: Any, fields: Iterable[str]) -> dict[str, Any]:
        """Valeurs actuelles de `fields`, à prendre AVANT de modifier la ressource."""
        return {f: getattr(resource, f, None) for f in fields}

    @staticmethod
    def diff(before: Mapping[str, Any], resource: Any) -> dict[str, dict[str, Any]]:
        """Champs réellement modifiés depuis `before` : `{champ: {"from": ancien, "to": nouveau}}`."""
        after = AuditService.snapshot(resource, before.keys())
        return {f: {"from": before[f], "to": after[f]} for f in before if before[f] != after[f]}

    # ---- Lecture ------------------------------------------------------------------

    @staticmethod
    def list_logs(session: Session, params: PageParams, filters: AuditFilters) -> dict[str, Any]:
        stmt = select(AuditLog)
        if filters.actor_id:
            stmt = stmt.where(col(AuditLog.actor_id) == filters.actor_id)
        if filters.action:
            stmt = stmt.where(col(AuditLog.action) == filters.action.value)
        if filters.resource_type:
            stmt = stmt.where(col(AuditLog.resource_type) == filters.resource_type)
        if filters.resource_id:
            stmt = stmt.where(col(AuditLog.resource_id) == filters.resource_id)
        if filters.outcome:
            stmt = stmt.where(col(AuditLog.outcome) == filters.outcome.value)
        if filters.request_id:
            stmt = stmt.where(col(AuditLog.request_id) == filters.request_id)
        created_from: datetime | None = filters.created_from
        stmt = apply_date_range(stmt, AuditLog.created_at, created_from, filters.created_to)
        stmt = apply_sort(
            stmt, filters.sort, {"created_at": AuditLog.created_at}, tiebreaker=AuditLog.id
        )
        return paginate(session, stmt, params)
