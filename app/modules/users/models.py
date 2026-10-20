from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel

from app.core.clock import utc_now

from .enums import UserRole, UserStatus

if TYPE_CHECKING:
    from app.modules.auth.models import UserSession
    from app.modules.projects.models import Project


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)

    email: EmailStr = Field(index=True, unique=True)
    password_hash: str = Field()

    first_name: str = Field(nullable=False)
    last_name: str = Field(nullable=False)

    role: UserRole = Field(default=UserRole.USER)
    status: UserStatus = Field(default=UserStatus.ACTIVE)

    # Verrouillage anti brute-force : voir AuthService.authenticate.
    failed_login_attempts: int = Field(default=0, nullable=False)
    locked_until: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime | None = Field(default_factory=utc_now)

    sessions: list["UserSession"] = Relationship(back_populates="user")
    projects: list["Project"] = Relationship(back_populates="owner")
