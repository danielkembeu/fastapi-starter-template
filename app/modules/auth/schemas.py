"""Schémas Pydantic d'entrée/sortie pour la feature d'authentification."""

from typing import Annotated

from pydantic import Field, StringConstraints
from sqlmodel import SQLModel

from app.core.validators import NormalizedEmail, Password, PersonName
from app.modules.users.schemas import UserRead


class LoginPayload(SQLModel):
    """Identifiants de connexion (la politique de mot de passe ne s'applique pas ici)."""

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class LoginResponse(SQLModel):
    """Réponse renvoyée après une connexion ou un rafraîchissement réussi."""

    access_token: str
    refresh_token: str
    token_type: str
    user: UserRead


class UserRegisterCreate(SQLModel):
    """Payload d'inscription."""

    email: NormalizedEmail
    password: Password
    first_name: PersonName
    last_name: PersonName


class UserRegisterResponse(SQLModel):
    """Réponse d'inscription."""

    success: bool
    message: str
    user: UserRead


class RefreshTokenPayload(SQLModel):
    """Payload de rafraîchissement des jetons."""

    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    device: Annotated[str, StringConstraints(max_length=255)] | None = None
    ip_address: str | None = Field(
        default=None, description="Ignoré : l'adresse IP est lue côté serveur."
    )


class LogoutPayload(SQLModel):
    """Payload de déconnexion : on indique le refresh_token de la session à clore."""

    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class LogoutResponse(SQLModel):
    """Réponse d'une déconnexion réussie."""

    success: bool
    message: str
