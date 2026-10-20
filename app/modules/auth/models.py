from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel

from app.core.clock import utc_now

if TYPE_CHECKING:
    from app.modules.users.models import User


class UserSession(SQLModel, table=True):
    __tablename__ = "user_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)

    user_id: UUID = Field(foreign_key="users.id")

    # Empreintes SHA-256 : le refresh token en clair n'est jamais stocké.
    refresh_token_hash: str = Field(unique=True, index=True)
    # Empreinte du jeton précédent : si elle est présentée, le jeton a été volé (réutilisation
    # d'un jeton déjà tourné) et toute la session est révoquée.
    previous_refresh_token_hash: str | None = Field(default=None, index=True)
    device: str | None = Field(default=None)
    ip_address: str | None = Field(default=None)

    expires_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)

    user: Optional["User"] = Relationship(back_populates="sessions")
