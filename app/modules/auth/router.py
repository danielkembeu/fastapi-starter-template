"""Endpoints d'authentification : inscription, connexion, rafraîchissement, déconnexion."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings
from app.core.database import DBSessionDep
from app.core.errors import err
from app.core.ratelimit import ip_key, limiter
from app.core.security import OAUthCurrentUserDep
from app.modules.auth.schemas import (
    LoginPayload,
    LoginResponse,
    LogoutPayload,
    LogoutResponse,
    RefreshTokenPayload,
    UserRegisterCreate,
    UserRegisterResponse,
)
from app.modules.users.schemas import UserRead

from .service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"], responses=err(400, 500))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _device(request: Request) -> str:
    return request.headers.get("user-agent", "Unknown device")


def _login_response(session, request: Request, user) -> JSONResponse:
    result = AuthService.issue_session(
        session, user, device=_device(request), ip_address=_client_ip(request)
    )
    result["user"] = UserRead.model_validate(result["user"]).model_dump(mode="json")
    return JSONResponse(content=result)


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=201,
    responses=err(403, 409, 429),
)
@limiter.limit(lambda: settings.RATE_LIMIT_REGISTER, key_func=ip_key)
def register(request: Request, payload: UserRegisterCreate, session: DBSessionDep):
    """Inscrit un nouvel utilisateur (le rôle est toujours `user`).

    Mot de passe : 8 caractères minimum, au moins une lettre et un chiffre. L'e-mail est
    normalisé en minuscules. Le client doit ensuite appeler `/login` pour obtenir des jetons.
    Limite : `RATE_LIMIT_REGISTER` par adresse IP.
    """
    result = AuthService.register(session, payload)
    result["user"] = UserRead.model_validate(result["user"]).model_dump(mode="json")
    return JSONResponse(status_code=201, content=result)


@router.post("/login", response_model=LoginResponse, responses=err(401, 403, 429))
@limiter.limit(lambda: settings.RATE_LIMIT_AUTH, key_func=ip_key)
def login(request: Request, payload: LoginPayload, session: DBSessionDep):
    """Authentifie un utilisateur (email + mot de passe) et émet ses jetons.

    `device` est dérivé de l'en-tête `User-Agent`, `ip_address` de la connexion. Retourne un
    `access_token` (à mettre dans `Authorization: Bearer …`) et un `refresh_token` à conserver.

    Protections : 401 identique pour e-mail inconnu et mauvais mot de passe ; verrouillage du
    compte après `MAX_LOGIN_ATTEMPTS` échecs (429 + `Retry-After`) ; limite par adresse IP.
    """
    return _login_response(session, request, AuthService.authenticate(session, payload))


@router.post(
    "/token",
    response_model=LoginResponse,
    include_in_schema=False,
    responses=err(401, 403, 429),
)
@limiter.limit(lambda: settings.RATE_LIMIT_AUTH, key_func=ip_key)
def oauth2_token(
    request: Request,
    session: DBSessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Endpoint OAuth2 Password Flow pour Swagger Authorize.

    `username` doit contenir l'email de connexion.
    """
    payload = LoginPayload(email=form_data.username, password=form_data.password)
    return _login_response(session, request, AuthService.authenticate(session, payload))


@router.post("/refresh", response_model=LoginResponse, responses=err(401, 429))
@limiter.limit(lambda: settings.RATE_LIMIT_AUTH, key_func=ip_key)
def refresh(request: Request, payload: RefreshTokenPayload, session: DBSessionDep):
    """Régénère un nouvel access_token et refresh_token.

    Le refresh_token courant est **invalidé** (rotation). Présenter à nouveau un jeton déjà
    utilisé révoque la session (détection de vol). 401 si le jeton est inconnu, expiré, ou si
    le compte n'est plus actif.
    """
    result = AuthService.refresh_tokens(
        session,
        refresh_token=payload.refresh_token,
        device=payload.device or _device(request),
        ip_address=_client_ip(request),
    )
    result["user"] = UserRead.model_validate(result["user"]).model_dump(mode="json")
    return JSONResponse(content=result)


@router.post("/logout", response_model=LogoutResponse, responses=err(404))
def logout(payload: LogoutPayload, session: DBSessionDep):
    """Déconnecte la session associée au refresh_token fourni."""
    return JSONResponse(content=AuthService.logout(session, payload.refresh_token))


@router.get("/me", response_model=UserRead, responses=err(401, 403))
def me(auth_user: OAUthCurrentUserDep):
    """Renvoie l'utilisateur authentifié, déduit de l'access_token."""
    return UserRead.model_validate(auth_user)
