"""Limitation de débit (slowapi).

Deux clés selon l'enjeu :
- `ip_key` pour les endpoints publics (login, inscription) : l'attaquant n'a pas de compte ;
- `user_key` pour le reste : l'utilisateur authentifié (jeton signé), sinon l'adresse IP.
  Derrière un NAT d'opérateur mobile, des centaines d'utilisateurs partagent une IP ; limiter
  par utilisateur évite de les pénaliser les uns pour les autres.

Les compteurs doivent être partagés entre workers (Redis) dès qu'il y en a plusieurs.
"""

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _find_route_handler, _should_exempt
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import ErrorCode, build_error_response

logger = logging.getLogger(__name__)


def ip_key(request: Request) -> str:
    return f"ip:{request.client.host if request.client else 'unknown'}"


def user_key(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            payload = jwt.decode(
                header[7:], settings.SECRET_JWT, algorithms=[settings.JWT_ALGORITHM]
            )
            if payload.get("sub"):
                return f"user:{payload['sub']}"
        except JWTError:
            pass
    return ip_key(request)


class FailOpenLimiter(Limiter):
    """`Limiter` qui laisse passer la requête quand le stockage des compteurs est en panne.

    `swallow_errors=True` avale l'erreur de Redis, mais slowapi lit ensuite
    `request.state.view_rate_limit`, jamais renseigné dans ce cas : l'`AttributeError` donnait un 500.
    """

    def _check_request_limit(
        self, request: Request, endpoint_func: Any, in_middleware: bool = True
    ) -> None:
        try:
            super()._check_request_limit(request, endpoint_func, in_middleware)
        except RateLimitExceeded:
            raise
        except Exception:
            logger.exception("Limitation de débit indisponible : requête acceptée sans contrôle")
        if not hasattr(request.state, "view_rate_limit"):
            request.state.view_rate_limit = None


limiter = FailOpenLimiter(
    key_func=user_key,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    # Si le stockage des compteurs (Redis) tombe, on laisse passer plutôt que de faire tomber l'API :
    # la limitation de débit est une protection, pas une condition de service.
    # (Le verrouillage d'un compte après échecs répétés est en base et reste actif.)
    swallow_errors=True,
)


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    limit = cast(RateLimitExceeded, exc).limit
    retry_after = str(limit.limit.get_expiry()) if limit else "60"
    return build_error_response(
        request,
        429,
        ErrorCode.RATE_LIMITED,
        "Trop de requêtes, réessayez plus tard",
        headers={"Retry-After": retry_after},
    )


class RateLimitMiddleware:
    """Applique la limite par défaut aux routes sans limite propre.

    Remplace `SlowAPIMiddleware`, qui (a) plante quand le stockage des compteurs est en panne et
    (b) ignore un gestionnaire d'erreur asynchrone, renvoyant alors son propre format. Ici : réponse
    `429` au format de l'API, vérification hors de la boucle d'événements, ouverture en cas de panne.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        active_limiter: Limiter | None = (
            getattr(scope["app"].state, "limiter", None) if scope["type"] == "http" else None
        )
        if active_limiter is None or not active_limiter.enabled:
            return await self.app(scope, receive, send)

        handler = _find_route_handler(scope["app"].routes, scope)
        if _should_exempt(active_limiter, handler):  # route exemptée, ou limite propre (décorateur)
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)
        try:
            await run_in_threadpool(active_limiter._check_request_limit, request, handler, True)
        except RateLimitExceeded as exc:
            response = await rate_limit_exceeded_handler(request, exc)
            return await response(scope, receive, send)
        except Exception:
            logger.exception("Limitation de débit indisponible : requête acceptée sans contrôle")

        await self.app(scope, receive, send)


def register_rate_limit(app: FastAPI) -> None:
    if settings.is_production and settings.RATE_LIMIT_STORAGE_URI.startswith("memory://"):
        logger.warning(
            "Limitation de débit en mémoire : avec plusieurs workers, chaque processus "
            "compte séparément. Configurer RATE_LIMIT_STORAGE_URI vers Redis."
        )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(RateLimitMiddleware)
