"""Lecture du journal d'audit dans les tests."""

from sqlmodel import Session, col, select

from app.modules.audit.enums import AuditAction
from app.modules.audit.models import AuditLog


def entries(session: Session, action: AuditAction | None = None, **where) -> list[AuditLog]:
    """Entrées du journal (ordre chronologique), filtrées par action et/ou colonnes."""
    stmt = select(AuditLog).order_by(col(AuditLog.created_at), col(AuditLog.id))
    if action is not None:
        stmt = stmt.where(col(AuditLog.action) == action.value)
    for column, value in where.items():
        stmt = stmt.where(col(getattr(AuditLog, column)) == value)
    session.expire_all()
    return list(session.exec(stmt).all())


def actions(session: Session) -> list[str]:
    return [e.action for e in entries(session)]


def only(session: Session, action: AuditAction, **where) -> AuditLog:
    """L'unique entrée d'une action ; échoue si elle est absente ou multiple."""
    found = entries(session, action, **where)
    assert len(found) == 1, (
        f"{action.value}: {len(found)} entrée(s) au lieu d'une ({actions(session)})"
    )
    return found[0]
