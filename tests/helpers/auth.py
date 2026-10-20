"""Fabriques de comptes de test : on crée les utilisateurs directement en base."""

from itertools import count

from sqlmodel import Session

from app.core.security import create_access_token, hash_password
from app.modules.users.enums import UserRole, UserStatus
from app.modules.users.models import User

PASSWORD = "Secret123!"

_sequence = count(1)


def register_payload(email: str = "test@example.com") -> dict:
    return {
        "email": email,
        "password": PASSWORD,
        "first_name": "Test",
        "last_name": "User",
    }


def register_and_login(client, email: str = "test@example.com") -> str:
    payload = register_payload(email=email)
    client.post("/api/v1/auth/register", json=payload)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
    )
    return r.json()["access_token"]


def bearer(user: User) -> dict[str, str]:
    """En-tête Authorization valide pour `user`."""
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


class TestUsers:
    """Crée des comptes de chaque rôle dans la session de test."""

    __test__ = False  # pas une classe de tests pour pytest

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        role: UserRole = UserRole.USER,
        *,
        email: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        n = next(_sequence)
        user = User(
            email=email or f"{role.value}{n}@example.com",
            password_hash=hash_password(PASSWORD),
            first_name="Prénom",
            last_name="Nom",
            role=role,
            status=status,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def user(self, **kwargs) -> User:
        return self.create(UserRole.USER, **kwargs)

    def admin(self, **kwargs) -> User:
        return self.create(UserRole.ADMIN, **kwargs)
