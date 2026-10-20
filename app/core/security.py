import hashlib
from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import select

from app.core.clock import utc_now
from app.core.config import settings
from app.core.database import DBSessionDep
from app.core.errors import AppError, ErrorCode
from app.modules.users.enums import UserRole, UserStatus
from app.modules.users.models import User

# Endpoint OAuth2 utilisé par Swagger "Authorize".
# Doit être absolu et inclure le préfixe de version (settings.api_prefix).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/token")
OAuthBearerDep = Annotated[str, Depends(oauth2_scheme)]

# ==============================================================================================================================================================================

# Prepare JWT Token Usage
SECRET_KEY = settings.SECRET_JWT
ALGORITHM = settings.JWT_ALGORITHM

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


hasher = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, hash: str) -> bool:
    return hasher.verify(password, hash)


def hash_token(token: str) -> str:
    """Empreinte SHA-256 d'un refresh token.

    Les refresh tokens sont aléatoires (512 bits) : une empreinte rapide suffit et permet de
    les retrouver par index. Une fuite de la base ne donne alors aucune session utilisable.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: UUID | str, role: UserRole | None) -> str:
    """
    Create a JWT access token with user id and role embedded.

    Args:
        user_id (str): The user's unique identifier.
        role (UserRole): The user's role (type UserRole).
    Returns:
        str: JWT access token as a string.
    """
    data: dict[str, Any] = {
        "sub": str(user_id),
        "role": (role or UserRole.USER).value,
    }

    to_encode = data.copy()
    # UTC explicite : un datetime naïf serait lu comme de l'UTC par la bibliothèque JWT, décalant
    # l'expiration du décalage horaire du serveur.
    expire_time = utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire_time})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: OAuthBearerDep, session: DBSessionDep, request: Request) -> User:
    credentials_exception = AppError(
        401,
        ErrorCode.INVALID_TOKEN,
        "Informations d'authentification invalides",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")

        if not user_id_raw:
            raise credentials_exception

        user_id = UUID(user_id_raw)

    except JWTError:
        raise credentials_exception from None

    except (TypeError, ValueError):
        raise credentials_exception from None

    user = session.exec(select(User).where(User.id == user_id)).first()

    if not user:
        raise credentials_exception

    # Lu par le gestionnaire d'erreurs pour journaliser les accès refusés avec l'acteur.
    request.state.actor_id = user.id
    request.state.actor_role = user.role.value

    if user.status != UserStatus.ACTIVE:
        raise AppError(403, ErrorCode.ACCOUNT_BLOCKED, "Compte actuellement restreint")

    return user


OAUthCurrentUserDep = Annotated[User, Depends(get_current_user)]
