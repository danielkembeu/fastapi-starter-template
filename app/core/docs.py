"""Exposition de la documentation interactive selon l'environnement.

- local / ci : /docs (Swagger UI), /redoc (ReDoc) et /openapi.json ouverts.
- staging    : protégés par HTTP Basic (DOCS_USERNAME / DOCS_PASSWORD).
- production : routes absentes (404) — la cartographie de l'API n'est pas publique.
"""

import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import Environment, Settings
from app.core.errors import AppError, ErrorCode

_basic = HTTPBasic(auto_error=False)


def _basic_guard(settings: Settings) -> Callable[..., None]:
    def guard(credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)]) -> None:
        valid = (
            credentials is not None
            and secrets.compare_digest(
                credentials.username.encode(), settings.DOCS_USERNAME.encode()
            )
            and secrets.compare_digest(
                credentials.password.encode(), settings.DOCS_PASSWORD.encode()
            )
        )
        if not valid:
            raise AppError(
                401,
                ErrorCode.UNAUTHORIZED,
                "Accès à la documentation refusé",
                headers={"WWW-Authenticate": "Basic"},
            )

    return guard


def register_docs(app: FastAPI, settings: Settings) -> None:
    """Branche /docs, /redoc et /openapi.json selon `settings.ENVIRONMENT`.

    `app` doit être créée avec `docs_url=None, redoc_url=None, openapi_url=None`.
    """
    if settings.ENVIRONMENT is Environment.PRODUCTION:
        return

    dependencies = []
    if settings.ENVIRONMENT is Environment.STAGING:
        dependencies = [Depends(_basic_guard(settings))]

    @app.get("/openapi.json", include_in_schema=False, dependencies=dependencies)
    async def openapi_schema() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False, dependencies=dependencies)
    async def swagger_ui(req: Request) -> HTMLResponse:
        root_path = req.scope.get("root_path", "").rstrip("/")

        return get_swagger_ui_html(
            openapi_url=root_path + "/openapi.json",
            title=app.title + " - Swagger UI",
            swagger_favicon_url="/static/favicon.png",
            swagger_ui_parameters=app.swagger_ui_parameters,
        )

    @app.get("/redoc", include_in_schema=False, dependencies=dependencies)
    async def redoc_ui(req: Request) -> HTMLResponse:
        root_path = req.scope.get("root_path", "").rstrip("/")

        return get_redoc_html(
            openapi_url=root_path + "/openapi.json",
            title=app.title + " - ReDoc",
            redoc_favicon_url="/static/favicon.png",
        )
