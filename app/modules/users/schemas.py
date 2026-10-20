"""Schéma de sortie d'un utilisateur (jamais de hash de mot de passe)."""

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.modules.users.enums import UserRole, UserStatus


class UserRead(SQLModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime | None = None
