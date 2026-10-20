"""Journal d'accès : UNE ligne de log structurée par requête, avec son issue.

Remplace le journal d'accès d'uvicorn (désactivé) : mêmes informations, plus l'identifiant de requête,
l'utilisateur et la durée, au format des autres logs. Niveau selon l'issue :

    < 400 → INFO (« succès »)     4xx → WARNING (erreur du client)     5xx → ERROR (notre erreur)

Jamais de query string (elle peut contenir un jeton), jamais d'en-têtes ni de corps. Les sondes `/health`
sont ignorées (une toutes les 10 s noierait le trafic réel).
"""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.access")

SKIPPED_PREFIXES = ("/health/",)


def _level_for(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(SKIPPED_PREFIXES):
            return await self.app(scope, receive, send)

        started = time.perf_counter()
        status = 500  # si l'application lève avant d'avoir répondu

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            state = scope.get("state", {})
            actor_id = state.get("actor_id")
            logger.log(
                _level_for(status),
                "%s %s → %s",
                scope.get("method"),
                path,
                status,
                extra={
                    "event": "http.request",
                    "method": scope.get("method"),
                    "path": path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "user_id": str(actor_id) if actor_id else None,
                    "request_id": state.get("request_id"),
                },
            )
