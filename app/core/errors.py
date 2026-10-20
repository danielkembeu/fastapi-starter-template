"""Gestion centralisée des erreurs : un format unique, des codes stables, aucune fuite.

Toute réponse d'erreur a la même forme :

    {
      "error": {
        "code": "validation_error",          # identifiant STABLE, fait pour le code client (switch)
        "message": "Les données envoyées sont invalides",   # phrase lisible, affichable
        "status": 400,                        # rappel du code HTTP
        "request_id": "9f2c…",                # à communiquer au support ; relie logs, Sentry et audit
        "details": [{"field": "body.name", "message": "…", "code": "string_too_short"}],  # ou null
        "debug": {"exception": "…", "trace": ["…"]}     # SEULEMENT si ERROR_DEBUG (local/ci par défaut)
      }
    }

Règles :
- le client se base sur `code` (jamais sur `message`, qui peut être reformulé) ;
- `details` est du contenu sûr pour le client (champs invalides) ; `debug` ne sort jamais en production ;
- une erreur 5xx ne révèle rien (message générique) ; la cause est dans les logs et Sentry, retrouvée par `request_id` ;
- une valeur saisie par l'utilisateur n'est jamais renvoyée (un mot de passe mal formé ne doit pas revenir en clair).

Lever une erreur métier : `raise AppError(404, ErrorCode.NOT_FOUND, "Projet introuvable")`.
"""

import logging
import traceback
from enum import StrEnum
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.context import REQUEST_ID_HEADER, current_context

logger = logging.getLogger("app.errors")


class ErrorCode(StrEnum):
    """Codes d'erreur stables. En ajouter un = une valeur ici + (si utile) une ligne dans le client."""

    # Génériques (un par famille de statut)
    BAD_REQUEST = "bad_request"
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    # Authentification
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_TOKEN = "invalid_token"  # noqa: S105 — code d'erreur, pas un secret
    TOKEN_EXPIRED = "token_expired"  # noqa: S105 — code d'erreur, pas un secret
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_BLOCKED = "account_blocked"
    REGISTRATION_CLOSED = "registration_closed"
    EMAIL_ALREADY_USED = "email_already_used"
    WEAK_PASSWORD = "weak_password"  # noqa: S105 — code d'erreur, pas un secret
    # Requêtes de liste
    INVALID_SORT = "invalid_sort"
    INVALID_DATE_RANGE = "invalid_date_range"
    FILTER_FORBIDDEN = "filter_forbidden"
    # Règles métier
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    RESOURCE_LOCKED = "resource_locked"
    # Fichiers
    INVALID_FILE = "invalid_file"
    STORAGE_UNAVAILABLE = "storage_unavailable"


_DEFAULT_CODE_BY_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}

# Messages de repli quand une bibliothèque lève une HTTPException anglophone.
_FRENCH_MESSAGES: dict[str, str] = {
    "Not authenticated": "Authentification requise",
    "Not Found": "Ressource introuvable",
    "Method Not Allowed": "Méthode non autorisée",
    "Forbidden": "Accès refusé",
}

GENERIC_500_MESSAGE = "Une erreur interne est survenue"


class AppError(HTTPException):
    """Erreur métier avec un code stable. Sous-classe de `HTTPException` : tout le code existant la comprend."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode | str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = str(code)
        self.message = message
        self.details = details


# ---- Modèles (documentation OpenAPI) -------------------------------------------------


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    code: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    status: int
    request_id: str | None = None
    details: list[ErrorDetail] | None = None
    debug: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Forme standard de toute réponse d'erreur : `{"error": {code, message, status, request_id, details}}`."""

    error: ErrorBody


ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Requête invalide (données mal formées ou règle métier non respectée). `error.details` liste les champs.",
    401: "Authentification manquante ou invalide (jeton absent, expiré ou incorrect).",
    403: "Authentifié mais permissions insuffisantes pour cette action.",
    404: "Ressource introuvable.",
    409: "Conflit avec l'état actuel de la ressource (doublon, transition interdite).",
    413: "Fichier envoyé trop volumineux.",
    415: "Type de fichier non supporté.",
    429: "Trop de requêtes : limite de débit atteinte, réessayer après le délai `Retry-After`.",
    500: "Erreur interne du serveur (message générique ; communiquer `error.request_id` au support).",
    502: "Le service externe sollicité a renvoyé une erreur.",
    503: "Service externe temporairement indisponible.",
}


def err(*codes: int) -> dict:
    """Construit un dict `responses=` pour documenter des codes d'erreur dans Swagger/ReDoc.

    Exemple: `@router.get(..., responses=err(401, 403, 404))`
    """
    return {
        code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]} for code in codes
    }


# ---- Construction de la réponse ------------------------------------------------------


def _request_id(request: Request) -> str | None:
    """Identifiant de requête. Lu dans `request.state` : pour une erreur 500, le contexte est déjà retiré."""
    return getattr(request.state, "request_id", None) or current_context().request_id


def _debug_block(exc: BaseException) -> dict[str, Any]:
    return {
        "exception": type(exc).__name__,
        "message": str(exc),
        "trace": traceback.format_exception(exc)[-12:],
    }


def build_error_response(
    request: Request,
    status_code: int,
    code: ErrorCode | str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    exc: BaseException | None = None,
) -> JSONResponse:
    """Réponse d'erreur au format standard. `exc` n'est exposé (`debug`) que si `ERROR_DEBUG` l'autorise."""
    request_id = _request_id(request)
    body: dict[str, Any] = {
        "code": str(code),
        "message": message,
        "status": status_code,
        "request_id": request_id,
        "details": details or None,
    }
    if exc is not None and settings.expose_error_debug:
        body["debug"] = _debug_block(exc)

    out_headers = dict(headers or {})
    if request_id:
        out_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content={"error": body}, headers=out_headers)


# ---- Validation ----------------------------------------------------------------------

_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "Champ obligatoire",
    "string_too_short": "Valeur trop courte",
    "string_too_long": "Valeur trop longue",
    "string_type": "Une chaîne de caractères est attendue",
    "int_parsing": "Un entier est attendu",
    "int_type": "Un entier est attendu",
    "float_parsing": "Un nombre est attendu",
    "bool_parsing": "Un booléen est attendu",
    "enum": "Valeur non autorisée",
    "literal_error": "Valeur non autorisée",
    "uuid_parsing": "Identifiant invalide",
    "datetime_parsing": "Date invalide",
    "greater_than_equal": "Valeur trop petite",
    "less_than_equal": "Valeur trop grande",
    "greater_than": "Valeur trop petite",
    "less_than": "Valeur trop grande",
    "json_invalid": "Corps JSON invalide",
    "string_pattern_mismatch": "Format invalide",
    "extra_forbidden": "Champ non autorisé",
}


def _field_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Erreurs de validation SANS la valeur saisie (`input`) ni le contexte (`ctx`) : ils peuvent contenir un secret."""
    items = []
    for error in exc.errors():
        kind = str(error.get("type", "invalid"))
        message = _VALIDATION_MESSAGES.get(kind)
        if message is None:  # validateurs maison : « Value error, <notre message en français> »
            message = str(error.get("msg", "Valeur invalide")).removeprefix("Value error, ")
        items.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", ())) or None,
                "message": message,
                "code": kind,
            }
        )
    return items


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Un seul code (400) pour toute entrée invalide, au lieu du 422 par défaut de FastAPI.
    return build_error_response(
        request,
        400,
        ErrorCode.VALIDATION_ERROR,
        "Les données envoyées sont invalides",
        details=_field_errors(cast(RequestValidationError, exc)),
    )


# ---- HTTPException et erreurs non gérées ---------------------------------------------


async def _audit_access_denied(request: Request, exc: StarletteHTTPException) -> None:
    """Journalise (audit) tout refus d'accès d'un utilisateur authentifié (rôle, propriété ou règle métier).

    Un seul point de capture : aucun contrôle d'accès ne peut échapper au journal. Les refus sans
    acteur identifié (ex. connexion d'un compte bloqué) sont déjà tracés par leur propre action.
    """
    actor_id = getattr(request.state, "actor_id", None)
    if actor_id is None:
        return
    from fastapi.concurrency import run_in_threadpool

    from app.modules.audit.enums import AuditAction, AuditOutcome
    from app.modules.audit.service import AuditService

    await run_in_threadpool(
        lambda: AuditService.log_detached(
            AuditAction.ACCESS_DENIED,
            actor_id=actor_id,
            actor_role=getattr(request.state, "actor_role", None),
            outcome=AuditOutcome.DENIED,
            details={"reason": exc.detail, "method": request.method, "path": request.url.path},
        )
    )


def _message_of(exc: StarletteHTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        return _FRENCH_MESSAGES.get(detail, detail)
    return ERROR_DESCRIPTIONS.get(exc.status_code, "Erreur")


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    if http_exc.status_code == 403:
        await _audit_access_denied(request, http_exc)

    code = getattr(http_exc, "code", None) or _DEFAULT_CODE_BY_STATUS.get(
        http_exc.status_code,
        ErrorCode.INTERNAL_ERROR if http_exc.status_code >= 500 else ErrorCode.BAD_REQUEST,
    )
    message = getattr(http_exc, "message", None) or _message_of(http_exc)
    request_id = _request_id(request)

    # Les 4xx ordinaires sont déjà dans le journal d'accès ; on ne détaille que ce qui compte.
    if http_exc.status_code >= 500:
        logger.error(
            "%s",
            message,
            extra={"event": "error.http", "code": str(code), "request_id": request_id},
        )
    elif http_exc.status_code in (401, 403, 429):
        logger.warning(
            "Accès refusé : %s",
            code,
            extra={
                "event": "error.access",
                "code": str(code),
                "status": http_exc.status_code,
                "request_id": request_id,
            },
        )

    return build_error_response(
        request,
        http_exc.status_code,
        code,
        message,
        details=getattr(http_exc, "details", None),
        headers=dict(http_exc.headers) if http_exc.headers else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # La trace va dans les logs (selon LOG_STACKTRACES) et dans Sentry, jamais dans la réponse en production.
    logger.error(
        "Erreur non gérée sur %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
        extra={
            "event": "error.unhandled",
            "exception": type(exc).__name__,
            "request_id": _request_id(request),
        },
    )
    return build_error_response(
        request, 500, ErrorCode.INTERNAL_ERROR, GENERIC_500_MESSAGE, exc=exc
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
