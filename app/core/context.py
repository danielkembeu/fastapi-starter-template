"""Contexte de la requête en cours (adresse IP, navigateur, identifiant de requête).

Posé une fois par un middleware ASGI AVANT l'exécution de la route : les services peuvent ainsi
journaliser (audit, logs) sans recevoir l'objet `Request`. Les `ContextVar` sont copiées dans le
pool de threads de FastAPI, donc visibles des routes synchrones comme asynchrones.
"""

import logging
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    method: str | None = None
    path: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def current_context() -> RequestContext:
    return _current.get() or RequestContext()


def _tag_sentry(request_id: str) -> None:
    try:
        import sentry_sdk

        sentry_sdk.set_tag("request_id", request_id)
    except Exception:  # la supervision ne doit jamais casser une requête
        logging.getLogger(__name__).debug("Impossible d'étiqueter Sentry", exc_info=True)


class RequestContextMiddleware:
    """Renseigne le contexte et renvoie l'identifiant de requête dans l'en-tête `X-Request-ID`.

    Un identifiant fourni par le client (ou le reverse proxy) est conservé s'il est sain ; sinon il est
    généré. Il relie une réponse d'erreur, une ligne de log, un événement Sentry et une entrée d'audit.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        provided = headers.get(REQUEST_ID_HEADER, "")
        request_id = provided if _VALID_REQUEST_ID.match(provided) else uuid.uuid4().hex
        client = scope.get("client")
        user_agent = (headers.get("user-agent") or "")[:255] or None

        # Aussi dans l'état de la requête : une erreur 500 est mise en forme APRÈS la sortie de ce middleware
        # (le ContextVar est alors retiré), et doit pourtant porter l'identifiant.
        scope.setdefault("state", {})["request_id"] = request_id

        _tag_sentry(request_id)
        token = _current.set(
            RequestContext(
                ip_address=client[0] if client else None,
                user_agent=user_agent,
                request_id=request_id,
                method=scope.get("method"),
                path=scope.get("path"),
            )
        )

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _current.reset(token)
